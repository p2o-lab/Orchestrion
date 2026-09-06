"""Service control — the [2658-4:2022] handshake the POL must perform before it can
command a service.

A PEA honours `CommandExt` **only** in Automatic mode + External source (§8.2.2.3,
Table 13). So to control a service the POL must, in order:
  1. switch operation mode to **Automatic** (write `StateAutOp`, confirm `StateAutAct`),
  2. switch source to **External** (write `SrcExtOp`, confirm `SrcExtAct`),
  3. select a **procedure** (write `ProcedureExt`, confirm `ProcedureReq`),
  4. only then write the command to **`CommandExt`**.
Each request is confirmed via its `*Act` / `ProcedureReq` readback (the request is a
0->1 edge the PEA acknowledges). Getting the channel/order wrong means the command is
silently dropped — research §4.3.1's #1 integration failure.

Writes use the operator channel (`*Op`) since a conformant PEA defaults `StateChannel`
/ `SrcChannel` to 0 (Table 13: "*Op relevant if StateChannel is false").

Two further rules, both from §6.2.2.4 and both added with the step-model correction:
  - **Every command is checked against `CommandEn` first.** A command whose bit is clear
    is not merely unwise — the PEA "shall not execute" it, silently. See
    `require_command_enabled`.
  - **The mode handshake precedes even `RESET`.** Pre-flight (`ensure_idle`) therefore
    goes through `command_service`, never bare `send_command`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from orchestrion.mtp.model import ProcedureParameter, Service, ValueObject
from orchestrion.opcua.connection import PeaConnection
from orchestrion.state.classification import is_final
from orchestrion.state.codes import Command, ServiceState, decode_command_en

_CONFIRM_TIMEOUT = 6.0   # generous — real PEAs (and a loaded test box) can be slow
_POLL = 0.1

# RESETTING "prepares the procedural element and equipment for the next execution"
# ([IEC 61512-1] Table B.2) — on real equipment that can mean physical cleanup, so it
# gets a longer budget than a mode/procedure readback.
_RESET_TIMEOUT = 15.0


class ServiceControlError(RuntimeError):
    """A control step could not be confirmed (mode/source/procedure not accepted)."""


async def _confirm(
    conn: PeaConnection,
    service: Service,
    attr: str,
    ok: Callable[[object], bool],
    what: str,
) -> None:
    """Poll a readback node until `ok`, or raise after the timeout."""
    deadline = time.monotonic() + _CONFIRM_TIMEOUT
    while True:
        if ok(await conn.read_control(service, attr)):
            return
        if time.monotonic() >= deadline:
            raise ServiceControlError(f"{service.name}: timed out confirming {what}")
        await asyncio.sleep(_POLL)


async def ensure_automatic_external(conn: PeaConnection, service: Service) -> list[str]:
    """[§6.2.1] Ensure the service is in Automatic mode + External source.

    Idempotent: only requests a change when the corresponding `*Act` is not already set.
    Returns the channels it **actually** flipped (`["Automatic", "External"]`, or fewer,
    or `[]` if already there) so the caller can log a mode change only when one happened.
    """
    changed: list[str] = []
    if not bool(await conn.read_control(service, "StateAutAct")):
        await conn.write_control(service, "StateAutOp", True)          # [§6.2.1.1]
        await _confirm(conn, service, "StateAutAct", lambda v: bool(v), "Automatic mode")
        changed.append("Automatic")
    if not bool(await conn.read_control(service, "SrcExtAct")):
        await conn.write_control(service, "SrcExtOp", True)            # [§6.2.1.2]
        await _confirm(conn, service, "SrcExtAct", lambda v: bool(v), "External source")
        changed.append("External")
    return changed


async def select_procedure(conn: PeaConnection, service: Service, procedure_id: int) -> None:
    """[§8.2.2.5] Request a procedure and confirm via the `ProcedureReq` readback.

    Only a valid, service-defined ID is accepted; an invalid one leaves ProcedureReq 0.
    """
    valid = {p.procedure_id for p in service.procedures}
    if procedure_id not in valid:
        raise ServiceControlError(
            f"{service.name}: procedure {procedure_id} is not one of {sorted(valid)}"
        )
    await conn.write_control(service, "ProcedureExt", procedure_id)
    await _confirm(
        conn, service, "ProcedureReq", lambda v: int(v) == procedure_id,
        f"procedure {procedure_id}",
    )


async def read_command_en(conn: PeaConnection, service: Service) -> frozenset[Command]:
    """The commands the PEA currently allows — [2658-4:2022] §6.2.2.4.

    Read, never computed: §6.2.2.4 says the PEA may lock a transition "based on existing
    process values or interlocks at the control module level", so `StateCur` alone cannot
    predict it. Only the PEA writes `CommandEn`; the POL has read access only.
    """
    return decode_command_en(int(await conn.read_control(service, "CommandEn")))


async def require_command_enabled(
    conn: PeaConnection, service: Service, command: Command
) -> None:
    """Raise unless `command`'s `CommandEn` bit is set — [2658-4:2022] §6.2.2.4.

    "If the value of CommandEn indicates that a command is not requestable, this command
    should not be able to be initiated by the operator or the POL. The command shall
    first be enabled by the PEA."

    Without this the write is accepted by the server and **silently discarded** by the
    PEA, which is exactly how a `Start` issued to a service sitting in `COMPLETED`
    produced a recipe that ran one step and reported success.
    """
    enabled = await read_command_en(conn, service)
    if command in enabled:
        return
    state = await conn.read_state(service)
    allowed = ", ".join(sorted(c.name for c in enabled)) or "nothing"
    raise ServiceControlError(
        f"{service.name}: {command.name} is not enabled — the PEA would ignore it "
        f"(state {state.name}; CommandEn allows {allowed})"
    )


async def send_command(conn: PeaConnection, service: Service, command: Command) -> None:
    """[§8.2.2.3] Write a command to `CommandExt` (honoured in Automatic + External).

    Guarded by `CommandEn` first (§6.2.2.4) — see `require_command_enabled`. The check is
    advisory in the sense that the PEA enforces it too, but doing it here turns a silent
    no-op into a named error, which is the whole point.
    """
    await require_command_enabled(conn, service, command)
    await conn.write_control(service, "CommandExt", int(command))


async def _confirm_node(conn, node, ok: Callable[[object], bool], what: str) -> None:
    deadline = time.monotonic() + _CONFIRM_TIMEOUT
    while True:
        if ok(await conn.read_value(node)):
            return
        if time.monotonic() >= deadline:
            raise ServiceControlError(f"timed out confirming {what}")
        await asyncio.sleep(_POLL)


async def set_parameter(
    conn: PeaConnection, parameter: ProcedureParameter, value: float
) -> None:
    """Controlled value assignment for an analog/integer parameter — §8.1.3, §8.2.2.9.

    Ensures the parameter is in Automatic + External, writes `VExt`, confirms the PEA
    accepted it into `VReq` (a value outside VMin/VMax will not appear and this times
    out → error), then triggers `ApplyExt` (gated by `ApplyEn`) and confirms `VOut`.
    Handles the V-channel parameters (Ana/DInt); Bin/String would use their own
    channels — not needed for HC30.
    """
    n = parameter.data.nodes

    def node(attr: str):
        if attr not in n:
            raise ServiceControlError(f"parameter {parameter.name!r} has no {attr!r}")
        return n[attr]

    if not bool(await conn.read_value(node("StateAutAct"))):
        await conn.write_value(node("StateAutOp"), True)
        await _confirm_node(conn, node("StateAutAct"), lambda v: bool(v),
                            f"{parameter.name} Automatic")
    if not bool(await conn.read_value(node("SrcExtAct"))):
        await conn.write_value(node("SrcExtOp"), True)
        await _confirm_node(conn, node("SrcExtAct"), lambda v: bool(v),
                            f"{parameter.name} External")

    await conn.write_value(node("VExt"), value)
    await _confirm_node(conn, node("VReq"), lambda v: abs(float(v) - float(value)) < 1e-6,
                        f"{parameter.name} value {value} (within VMin/VMax?)")

    if not bool(await conn.read_value(node("ApplyEn"))):
        raise ServiceControlError(f"{parameter.name}: apply is not enabled (ApplyEn=false)")
    await conn.write_value(node("ApplyExt"), True)
    await _confirm_node(conn, node("VOut"), lambda v: abs(float(v) - float(value)) < 1e-6,
                        f"{parameter.name} applied to VOut")


async def write_process_value(
    conn: PeaConnection, value: ValueObject, raw: object
) -> None:
    """Write an incoming process value's `V` — [2658-4:2022] §6.3.3 (POL→PEA).

    A ProcessValueIn is written **directly**, unlike a parameter: there is no
    VExt/VReq/Apply handshake — `V` is "input of the current value" (Tables 23-26) and
    is written continuously by the POL. The server's declared type coerces `raw` (BOOL
    for BinProcessValueIn, Float/DInt for Ana/DInt, STRING for String). VQC (the value's
    quality, §8.3.2) is left to a later refinement — its code encoding is standard-defined
    and not to be guessed here.
    """
    node = value.data.nodes.get("V")
    if node is None:
        raise ServiceControlError(f"value {value.name!r} has no writable V channel")
    await conn.write_value(node, raw)


async def start_service(
    conn: PeaConnection,
    service: Service,
    procedure_id: int,
    values: dict[str, float] | None = None,
) -> list[str]:
    """Full start: Automatic + External -> select procedure -> set parameter values
    (§4.3.1: before EXECUTE) -> Start on CommandExt.

    Returns the mode/source channels the handshake actually flipped (see
    `ensure_automatic_external`) so the API layer can log a mode change when one occurred."""
    changed = await ensure_automatic_external(conn, service)
    await select_procedure(conn, service, procedure_id)
    if values:
        procedure = next((p for p in service.procedures if p.procedure_id == procedure_id), None)
        if procedure is not None:
            for parameter in procedure.parameters:
                if parameter.name in values:
                    await set_parameter(conn, parameter, values[parameter.name])
    await send_command(conn, service, Command.START)
    return changed


async def command_service(
    conn: PeaConnection, service: Service, command: Command
) -> list[str]:
    """Send a command (Stop/Hold/Pause/Resume/Complete/Abort/Reset/Restart).

    Ensures Automatic + External first so the command is on the honoured channel; the
    PEA still only acts if the command's `CommandEn` bit is set (§6.2.2.4). Returns any
    mode/source channels the handshake flipped, so the API layer can log a mode change.
    """
    changed = await ensure_automatic_external(conn, service)
    await send_command(conn, service, command)
    return changed


# ---------------------------------------------------------------------------------
# Pre-flight — what must be true before a recipe step may issue `Start`.
# `POL_Step_Model_ISA88.md` §1 (initiate + await termination) and §4 (the four cases).
# These are primitives; the recipe engine composes them. `start_service` above is left
# as the bare handshake+Start it has always been, so the M3 HMI path is unchanged.
# ---------------------------------------------------------------------------------


async def await_state(
    conn: PeaConnection,
    service: Service,
    accept: Callable[[ServiceState], bool],
    what: str,
    *,
    timeout: float = _CONFIRM_TIMEOUT,
) -> ServiceState:
    """Poll `StateCur` until `accept` says yes; raise on timeout. Returns the state seen.

    Reads the node directly rather than a subscription cache: the caller needs the state
    *at a known instant*, and a cache can have moved on (`POL_Step_Model_ISA88.md` §5).

    Not for awaiting *termination* — a step may legitimately run for hours. This budget
    is for handshake-scale waits only; the engine polls for termination itself.
    """
    deadline = time.monotonic() + timeout
    while True:
        state = await conn.read_state(service)
        if accept(state):
            return state
        if time.monotonic() >= deadline:
            raise ServiceControlError(
                f"{service.name}: timed out waiting for {what} (still {state.name})"
            )
        await asyncio.sleep(_POLL)


async def await_started(conn: PeaConnection, service: Service) -> ServiceState:
    """Wait until the service has left `IDLE` after a `Start`.

    **Any** state other than `IDLE` counts as started — including a *final* state.
    A self-completing procedure can run to `COMPLETED` between two polls (the VirtualPEA
    publishes `EXECUTE` for a single 50 ms scan and never publishes `STARTING` at all),
    so waiting for an *acting* state would hang forever on exactly
    the case the step model exists to fix.
    """
    return await await_state(
        conn, service, lambda s: s is not ServiceState.IDLE, "the service to leave IDLE"
    )


async def ensure_idle(conn: PeaConnection, service: Service) -> None:
    """Bring the service to `IDLE`, or fail loudly — `POL_Step_Model_ISA88.md` §4.

    | service is | do |
    |---|---|
    | `IDLE` | nothing |
    | a final state | `RESET`, wait for `IDLE` |
    | `RESETTING` | already on its way — wait for `IDLE` |
    | anything else | raise: somebody else is using this service |

    [IEC 61512-1] Table B.2 makes the second row mandatory, not housekeeping: `COMPLETE`
    "waits in the final state for a RESET command", and RESETTING "always becomes active
    between executions of the Process-oriented task".

    `COMPLETING`/`STOPPING`/`ABORTING` are deliberately **not** waited on even though they
    also lead somewhere resettable: each means another owner started this service and it
    is now finishing. Waiting would queue us behind them and seize the equipment the
    moment they let go. **Ownership, not reachability, is the test.**
    """
    state = await conn.read_state(service)
    if state is ServiceState.IDLE:
        return

    if is_final(state):
        # RESET rides CommandExt, which the PEA honours only in the matching operation
        # mode (§8.2.2.3) — so this MUST go through `command_service` (which runs the
        # idempotent handshake first), never bare `send_command`.
        await command_service(conn, service, Command.RESET)
        await await_state(
            conn, service, lambda s: s is ServiceState.IDLE,
            "IDLE after RESET", timeout=_RESET_TIMEOUT,
        )
        return

    if state is ServiceState.RESETTING:
        await await_state(
            conn, service, lambda s: s is ServiceState.IDLE,
            "IDLE (already RESETTING)", timeout=_RESET_TIMEOUT,
        )
        return

    raise ServiceControlError(
        f"{service.name} is {state.name} (in use) — cannot start it"
    )
