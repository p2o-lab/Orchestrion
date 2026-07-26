"""Service control endpoints — start a service (with a procedure) and send commands.

These act on the PEA's **persistent** connection (the registry); the PEA must already
be connected. All the 2658-4 handshake logic lives in `opcua.control`; this layer only
resolves the service, guards inputs, and maps failures to HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from orchestrion.api.live import registry
from orchestrion.api.mtp_import import parse_aml
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea
from orchestrion.events import EventKind
from orchestrion.mtp.model import Pea as PeaModel, Service, ValueObject
from orchestrion.opcua import control
from orchestrion.opcua.connection import OpcUaConnectionError
from orchestrion.state.codes import Command

router = APIRouter(tags=["control"])


class StartRequest(BaseModel):
    procedure_id: int
    values: dict[str, float] = {}  # parameter name -> value (controlled value assignment)


class CommandRequest(BaseModel):
    command: str  # a [2658-4 Table 14] command name, e.g. "STOP", "ABORT", "COMPLETE"


class ValueWrite(BaseModel):
    value: bool | float | str  # coerced to the node's server type on write


def _pea(session: Session, pea_id: int) -> PeaModel:
    row = session.get(Pea, pea_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"PEA {pea_id} not found")
    return parse_aml(row.aml_content.encode("utf-8"), row.aml_filename)


def _service(session: Session, pea_id: int, service_name: str) -> Service:
    for service in _pea(session, pea_id).services:
        if service.name == service_name:
            return service
    raise HTTPException(status_code=404, detail=f"service {service_name!r} not found")


def _writable_process_value(pea: PeaModel, name: str) -> ValueObject:
    """An incoming process value the POL may write (§6.3.3), PEA-wide or per-procedure.

    Config parameters are also writable but use controlled value assignment (§8.1.3) and
    are not handled by this endpoint yet; read-only values (out) never match here.
    """
    candidates = list(pea.process_values_in)
    for service in pea.services:
        for procedure in service.procedures:
            candidates.extend(procedure.process_values_in)
    for value in candidates:
        if value.name == name:
            return value
    raise HTTPException(
        status_code=404,
        detail=f"{name!r} is not a writable incoming process value on this PEA",
    )


def _require_connection(pea_id: int):
    conn = registry.connection(pea_id)
    if conn is None:
        raise HTTPException(status_code=409, detail="connect the PEA before controlling it")
    return conn


@router.post("/api/peas/{pea_id}/services/{service_name}/start")
async def start(
    pea_id: int, service_name: str, body: StartRequest,
    session: Session = Depends(get_session),
) -> dict:
    service = _service(session, pea_id, service_name)
    conn = _require_connection(pea_id)
    try:
        changed = await control.start_service(conn, service, body.procedure_id, body.values)
    except control.ServiceControlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # [2658-4:2022 §6.2.1] the POL took the service to Automatic + External — logged only
    # when the handshake actually transitioned it (not on the idempotent re-assert).
    if changed:
        registry.record_event(
            pea_id, EventKind.MODE, f"{service.name}: → {' + '.join(changed)}"
        )
    # [2658-4:2022 §8.2.2.5] Start with the selected procedure — an operator action.
    procedure = next(
        (p for p in service.procedures if p.procedure_id == body.procedure_id), None
    )
    procedure_label = procedure.name if procedure is not None else str(body.procedure_id)
    registry.record_event(
        pea_id, EventKind.COMMAND, f"{service.name}: Start {procedure_label}"
    )
    return {"ok": True}


@router.post("/api/peas/{pea_id}/services/{service_name}/command")
async def command(
    pea_id: int, service_name: str, body: CommandRequest,
    session: Session = Depends(get_session),
) -> dict:
    service = _service(session, pea_id, service_name)
    conn = _require_connection(pea_id)
    try:
        cmd = Command[body.command.upper()]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"unknown command {body.command!r}; expected one of "
            f"{[c.name for c in Command]}",
        ) from None
    try:
        changed = await control.command_service(conn, service, cmd)
    except control.ServiceControlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # [2658-4:2022 §6.2.1] mode change first, only if the handshake transitioned it.
    if changed:
        registry.record_event(
            pea_id, EventKind.MODE, f"{service.name}: → {' + '.join(changed)}"
        )
    # [2658-4:2022 §8.2.2.3] a command the POL issued on CommandExt — an operator action.
    registry.record_event(pea_id, EventKind.COMMAND, f"{service.name}: {cmd.name}")
    return {"ok": True}


@router.post("/api/peas/{pea_id}/values/{value_name}")
async def write_value(
    pea_id: int, value_name: str, body: ValueWrite,
    session: Session = Depends(get_session),
) -> dict:
    """Write an incoming process value (§6.3.3). 409 if not connected, 404 if the value
    is not a writable incoming process value, 502 on a write failure."""
    value = _writable_process_value(_pea(session, pea_id), value_name)
    conn = _require_connection(pea_id)
    try:
        await control.write_process_value(conn, value, body.value)
    except (control.ServiceControlError, OpcUaConnectionError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # [2658-4:2022 §6.3.3] the POL wrote an incoming process value — an operator action.
    registry.record_event(pea_id, EventKind.VALUE_WRITE, f"{value_name} := {body.value}")
    return {"ok": True}
