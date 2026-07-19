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
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from orchestrion.mtp.model import ProcedureParameter, Service, ValueObject
from orchestrion.opcua.connection import PeaConnection
from orchestrion.state.codes import Command

_CONFIRM_TIMEOUT = 6.0   # generous — real PEAs (and a loaded test box) can be slow
_POLL = 0.1


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


async def ensure_automatic_external(conn: PeaConnection, service: Service) -> None:
    """[§6.2.1] Ensure the service is in Automatic mode + External source.

    Idempotent: only requests a change when the corresponding `*Act` is not already set.
    """
    if not bool(await conn.read_control(service, "StateAutAct")):
        await conn.write_control(service, "StateAutOp", True)          # [§6.2.1.1]
        await _confirm(conn, service, "StateAutAct", lambda v: bool(v), "Automatic mode")
    if not bool(await conn.read_control(service, "SrcExtAct")):
        await conn.write_control(service, "SrcExtOp", True)            # [§6.2.1.2]
        await _confirm(conn, service, "SrcExtAct", lambda v: bool(v), "External source")


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


async def send_command(conn: PeaConnection, service: Service, command: Command) -> None:
    """[§8.2.2.3] Write a command to `CommandExt` (honoured in Automatic + External)."""
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
) -> None:
    """Full start: Automatic + External -> select procedure -> set parameter values
    (§4.3.1: before EXECUTE) -> Start on CommandExt."""
    await ensure_automatic_external(conn, service)
    await select_procedure(conn, service, procedure_id)
    if values:
        procedure = next((p for p in service.procedures if p.procedure_id == procedure_id), None)
        if procedure is not None:
            for parameter in procedure.parameters:
                if parameter.name in values:
                    await set_parameter(conn, parameter, values[parameter.name])
    await send_command(conn, service, Command.START)


async def command_service(conn: PeaConnection, service: Service, command: Command) -> None:
    """Send a command (Stop/Hold/Pause/Resume/Complete/Abort/Reset/Restart).

    Ensures Automatic + External first so the command is on the honoured channel; the
    PEA still only acts if the command's `CommandEn` bit is set (§6.2.2.4).
    """
    await ensure_automatic_external(conn, service)
    await send_command(conn, service, command)
