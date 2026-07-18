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
from orchestrion.mtp.model import Service
from orchestrion.opcua import control
from orchestrion.state.codes import Command

router = APIRouter(tags=["control"])


class StartRequest(BaseModel):
    procedure_id: int


class CommandRequest(BaseModel):
    command: str  # a [2658-4 Table 14] command name, e.g. "STOP", "ABORT", "COMPLETE"


def _service(session: Session, pea_id: int, service_name: str) -> Service:
    row = session.get(Pea, pea_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"PEA {pea_id} not found")
    pea = parse_aml(row.aml_content.encode("utf-8"), row.aml_filename)
    for service in pea.services:
        if service.name == service_name:
            return service
    raise HTTPException(status_code=404, detail=f"service {service_name!r} not found")


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
        await control.start_service(conn, service, body.procedure_id)
    except control.ServiceControlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
        await control.command_service(conn, service, cmd)
    except control.ServiceControlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}
