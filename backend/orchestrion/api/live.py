"""Live PEA state — a WebSocket stream and a REST snapshot, backed by the registry.

Opening the WebSocket connects the POL to the PEA's OPC UA server (if not already),
subscribes to its services, pushes an initial snapshot, then streams each state change.
If the PEA is unreachable (the common case when its server is not running) the socket
reports an error and closes cleanly rather than hanging.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from orchestrion.api.mtp_import import parse_aml
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea
from orchestrion.mtp.model import Pea as PeaModel
from orchestrion.opcua.connection import OpcUaConnectionError
from orchestrion.opcua.registry import PeaRegistry

router = APIRouter(tags=["live"])

# One registry for the app's lifetime, on the single asyncio loop. main.lifespan
# calls registry.shutdown() to close every session on exit.
registry = PeaRegistry()


def _load_model(session: Session, pea_id: int) -> PeaModel:
    row = session.get(Pea, pea_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"PEA {pea_id} not found")
    return parse_aml(row.aml_content.encode("utf-8"), row.aml_filename)


@router.get("/api/peas/{pea_id}/live")
def live_snapshot(pea_id: int, session: Session = Depends(get_session)) -> dict:
    """Current live state, or `connected: false` if no session is open."""
    _load_model(session, pea_id)          # 404 if the PEA does not exist
    snapshot = registry.snapshot(pea_id)
    if snapshot is None:
        return {"connected": False, "states": {}, "command_en": {}}
    return {
        "connected": True,
        "states": snapshot.states,
        "command_en": snapshot.command_en,
    }


@router.websocket("/api/peas/{pea_id}/ws")
async def pea_ws(
    websocket: WebSocket, pea_id: int, session: Session = Depends(get_session)
) -> None:
    row = session.get(Pea, pea_id)
    if row is None:
        await websocket.close(code=4404)
        return
    parsed = parse_aml(row.aml_content.encode("utf-8"), row.aml_filename)

    await websocket.accept()
    try:
        snapshot = await registry.connect(pea_id, parsed)
    except OpcUaConnectionError as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})
        await websocket.close()
        return

    await websocket.send_json(
        {
            "type": "snapshot",
            "connected": True,
            "states": snapshot.states,
            "command_en": snapshot.command_en,
        }
    )

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    registry.add_listener(pea_id, queue)
    try:
        while True:
            message = await queue.get()
            await websocket.send_json({"type": "update", **message})
    except WebSocketDisconnect:
        pass
    finally:
        registry.remove_listener(pea_id, queue)
