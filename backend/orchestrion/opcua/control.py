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

from orchestrion.mtp.model import Service
from orchestrion.opcua.connection import PeaConnection
from orchestrion.state.codes import Command

_CONFIRM_TIMEOUT = 4.0
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


async def start_service(conn: PeaConnection, service: Service, procedure_id: int) -> None:
    """Full start: Automatic + External -> select procedure -> Start on CommandExt."""
    await ensure_automatic_external(conn, service)
    await select_procedure(conn, service, procedure_id)
    await send_command(conn, service, Command.START)


async def command_service(conn: PeaConnection, service: Service, command: Command) -> None:
    """Send a command (Stop/Hold/Pause/Resume/Complete/Abort/Reset/Restart).

    Ensures Automatic + External first so the command is on the honoured channel; the
    PEA still only acts if the command's `CommandEn` bit is set (§6.2.2.4).
    """
    await ensure_automatic_external(conn, service)
    await send_command(conn, service, command)
