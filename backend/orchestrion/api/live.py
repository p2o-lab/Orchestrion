"""Live PEA state: explicit connect/disconnect (persistent) + a WebSocket viewer.

The persistent OPC UA connection is owned by the registry and controlled only by the
POST connect/disconnect endpoints — it survives across navigation and browser reloads
until the user disconnects or the PEA dies. The WebSocket merely *views* the current
connection: opening or closing it (navigating away) never starts or stops the
connection.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from orchestrion.api.mtp_import import parse_aml
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea
from orchestrion.mtp.model import Pea as PeaModel
from orchestrion.opcua.connection import OpcUaConnectionError
from orchestrion.opcua.registry import PeaRegistry

router = APIRouter(tags=["live"])

# One registry for the app's lifetime. main.lifespan closes it on exit.
registry = PeaRegistry()


def _load_model(session: Session, pea_id: int) -> PeaModel:
    row = session.get(Pea, pea_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"PEA {pea_id} not found")
    return parse_aml(row.aml_content.encode("utf-8"), row.aml_filename)


def _payload(snapshot) -> dict:
    if snapshot is None:
        return {"connected": False, "states": {}, "command_en": {}}
    return {"connected": True, "states": snapshot.states, "command_en": snapshot.command_en}


@router.get("/api/peas/{pea_id}/live")
def live_snapshot(pea_id: int, session: Session = Depends(get_session)) -> dict:
    """Current live state — `connected: false` if no session is open."""
    _load_model(session, pea_id)  # 404 if unknown
    return _payload(registry.snapshot(pea_id))


@router.post("/api/peas/{pea_id}/connect")
async def connect_pea(pea_id: int, session: Session = Depends(get_session)) -> dict:
    """Open (or reuse) the persistent OPC UA connection. 502 if the PEA is unreachable."""
    pea = _load_model(session, pea_id)
    try:
        snapshot = await registry.connect(pea_id, pea)
    except OpcUaConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _payload(snapshot)


@router.post("/api/peas/{pea_id}/disconnect")
async def disconnect_pea(pea_id: int, session: Session = Depends(get_session)) -> dict:
    _load_model(session, pea_id)  # 404 if unknown
    await registry.disconnect(pea_id)
    return {"connected": False, "states": {}, "command_en": {}}


@router.websocket("/api/peas/{pea_id}/ws")
async def pea_ws(websocket: WebSocket, pea_id: int) -> None:
    """Stream live updates for a PEA that is already connected (view only)."""
    await websocket.accept()

    snapshot = registry.snapshot(pea_id)
    if snapshot is None:
        # Not connected — nothing to stream. Tell the viewer and close.
        await websocket.send_json({"type": "snapshot", "connected": False, "states": {}, "command_en": {}})
        await websocket.close()
        return

    await websocket.send_json(
        {"type": "snapshot", "connected": True, "states": snapshot.states,
         "command_en": snapshot.command_en}
    )

    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
    registry.add_listener(pea_id, queue)
    receiver = asyncio.create_task(_drain_incoming(websocket))
    try:
        while not receiver.done():
            get = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({get, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if get not in done:
                get.cancel()
                break  # client disconnected
            message = get.result()
            if message.get("kind") == "closed":
                # The registry dropped the connection (PEA died) — tell the viewer.
                await websocket.send_json({"type": "error", "detail": message.get("detail", "")})
                break
            await websocket.send_json(
                {"type": "update", "service": message["service"],
                 **({"state": message["state"]} if message["kind"] == "state" else {}),
                 **({"command_en": message["command_en"]} if message["kind"] == "command_en" else {})}
            )
    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
        registry.remove_listener(pea_id, queue)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _drain_incoming(websocket: WebSocket) -> None:
    with contextlib.suppress(Exception):
        while True:
            await websocket.receive()
