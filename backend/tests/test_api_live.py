"""Live WebSocket + snapshot: the POL streams a PEA's state to the UI.

Runs a real VirtualPEA in a background thread (its own loop) so the app — driven by
TestClient in its own loop — reaches it over TCP, exactly as in production.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from orchestrion.api import live
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea, Project
from orchestrion.main import app
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


def _aml_text(port: int) -> str:
    return LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )


class _ServerThread:
    """Runs a VirtualPEA on its own asyncio loop in a daemon thread."""

    def __init__(self, aml_path: Path) -> None:
        self._aml = aml_path
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()
        assert self._ready.wait(15), "VirtualPEA did not start"

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        pea = VirtualPEA(self._aml)
        self._loop.run_until_complete(pea.build())
        self._loop.run_until_complete(pea.start())
        self._ready.set()
        self._loop.run_forever()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield engine
    app.dependency_overrides.clear()
    live.registry._entries.clear()      # drop stale connections between tests


def _insert_pea(engine, aml_text: str) -> int:
    with Session(engine) as s:
        project = Project(name="Line")
        s.add(project)
        s.commit()
        s.refresh(project)
        pea = Pea(
            project_id=project.id,
            name="Stirrer",
            aml_filename="HC30.aml",
            aml_content=aml_text,
            endpoint_url="",
        )
        s.add(pea)
        s.commit()
        s.refresh(pea)
        return pea.id


def test_websocket_streams_initial_snapshot(db_engine):
    port = 48096
    tmp = Path(LOCAL_AML.parent) / "_ws_test.aml"
    tmp.write_text(_aml_text(port), encoding="utf-8")
    server = _ServerThread(tmp)
    server.start()
    try:
        pea_id = _insert_pea(db_engine, _aml_text(port))
        client = TestClient(app)
        with client.websocket_connect(f"/api/peas/{pea_id}/ws") as ws:
            message = ws.receive_json()
            assert message["type"] == "snapshot"
            assert message["connected"] is True
            assert message["states"]["Stirring"] == "IDLE"
    finally:
        server.stop()
        tmp.unlink(missing_ok=True)


def test_websocket_reports_error_when_pea_unreachable(db_engine):
    # A port with nothing listening -> connect fails -> clean error, not a hang.
    pea_id = _insert_pea(db_engine, _aml_text(48097))
    client = TestClient(app)
    with client.websocket_connect(f"/api/peas/{pea_id}/ws") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
