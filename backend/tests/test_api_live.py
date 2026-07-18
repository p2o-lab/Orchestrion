"""Live connection: persistent connect/disconnect + WebSocket viewer.

A real VirtualPEA runs in a background thread (its own loop) so the app — driven by
TestClient in its own loop — reaches it over TCP, exactly as in production.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import threading
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

# A distinct port per test so a lingering socket can never block the next one.
_PORTS = itertools.count(48120)


def _aml_text(port: int) -> str:
    return LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )


class _ServerThread:
    """Runs a VirtualPEA on its own asyncio loop in a daemon thread."""

    def __init__(self, aml_path: Path) -> None:
        self._aml = aml_path
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pea: VirtualPEA | None = None
        self._ready = threading.Event()
        self._stopped = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()
        assert self._ready.wait(15), "VirtualPEA did not start"

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._pea = VirtualPEA(self._aml)
        self._loop.run_until_complete(self._pea.build())
        self._loop.run_until_complete(self._pea.start())
        self._ready.set()
        self._loop.run_forever()

    def stop(self) -> None:
        # Always close the OPC UA server socket (frees the port for the next test and
        # lets a client see the drop fast). Safe to call more than once.
        if self._loop is None or self._stopped:
            return
        self._stopped = True
        if self._pea is not None:
            fut = asyncio.run_coroutine_threadsafe(self._pea.stop(), self._loop)
            with contextlib.suppress(Exception):
                fut.result(timeout=5)
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
    live.registry._entries.clear()  # drop any persistent connections between tests


def _insert_pea(engine, aml_text: str) -> int:
    with Session(engine) as s:
        project = Project(name="Line")
        s.add(project)
        s.commit()
        s.refresh(project)
        pea = Pea(project_id=project.id, name="Stirrer", aml_filename="HC30.aml",
                  aml_content=aml_text, endpoint_url="")
        s.add(pea)
        s.commit()
        s.refresh(pea)
        return pea.id


@pytest.fixture
def running_pea(db_engine):
    """A started VirtualPEA + an imported PEA row pointing at it. Yields (client, id)."""
    port = next(_PORTS)
    tmp = Path(LOCAL_AML.parent) / f"_ws_test_{port}.aml"
    tmp.write_text(_aml_text(port), encoding="utf-8")
    server = _ServerThread(tmp)
    server.start()
    pea_id = _insert_pea(db_engine, _aml_text(port))
    try:
        yield TestClient(app), pea_id, server
    finally:
        server.stop()
        tmp.unlink(missing_ok=True)


def test_connect_then_ws_streams_snapshot(running_pea):
    client, pea_id, _ = running_pea
    resp = client.post(f"/api/peas/{pea_id}/connect")
    assert resp.status_code == 200 and resp.json()["connected"] is True

    with client.websocket_connect(f"/api/peas/{pea_id}/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert msg["connected"] is True
        assert msg["states"]["Stirring"] == "IDLE"
    client.post(f"/api/peas/{pea_id}/disconnect")


def test_connection_persists_across_ws_open_close(running_pea):
    client, pea_id, _ = running_pea
    client.post(f"/api/peas/{pea_id}/connect")
    # open and close a viewer (i.e. navigate away)
    with client.websocket_connect(f"/api/peas/{pea_id}/ws") as ws:
        ws.receive_json()
    # the persistent connection is still up — navigating away did not drop it
    assert client.get(f"/api/peas/{pea_id}/live").json()["connected"] is True
    client.post(f"/api/peas/{pea_id}/disconnect")


def test_disconnect_stops_the_connection(running_pea):
    client, pea_id, _ = running_pea
    client.post(f"/api/peas/{pea_id}/connect")
    assert client.get(f"/api/peas/{pea_id}/live").json()["connected"] is True
    client.post(f"/api/peas/{pea_id}/disconnect")
    assert client.get(f"/api/peas/{pea_id}/live").json()["connected"] is False


def test_ws_on_a_not_connected_pea_reports_disconnected(running_pea):
    client, pea_id, _ = running_pea  # never connected
    with client.websocket_connect(f"/api/peas/{pea_id}/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot" and msg["connected"] is False


def test_connect_to_unreachable_pea_returns_502(db_engine):
    pea_id = _insert_pea(db_engine, _aml_text(48099))  # nothing listening
    client = TestClient(app)
    assert client.post(f"/api/peas/{pea_id}/connect").status_code == 502


# NOTE: the actual start-via-API happy path is NOT tested through TestClient — it runs
# each request on its own event loop, but the registry's asyncua connection is bound to
# the loop it was created on, so real OPC UA I/O in a later request crashes at the socket
# layer. This is a TestClient artifact (production runs one uvicorn loop). The control
# logic is covered against a real VirtualPEA in test_control.py; here we only assert the
# API's connection guard.
def test_control_requires_a_connection(running_pea):
    client, pea_id, _ = running_pea  # not connected
    r = client.post(f"/api/peas/{pea_id}/services/Stirring/command", json={"command": "STOP"})
    assert r.status_code == 409

# NOTE: "PEA dies mid-session -> dropped + reported" is covered reliably in
# test_registry.py against the registry directly (one event loop). Driving it through
# TestClient + an in-process asyncua server was flaky in-sequence and is not worth the
# fragility for behaviour already tested elsewhere.
