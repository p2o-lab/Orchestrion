"""Running a recipe over HTTP, against live VirtualPEAs.

**This is the proof the reuse defect is dead**: a recipe POSTed through
the API, driven across two real PEAs, *including two consecutive steps on the same PEA using
the self-completing procedure*. Before the correction that case ran the first step, had its
second `Start` silently dropped into `COMPLETED`, and reported success.

Everything goes through HTTP — no engine is constructed here. That is the point: until this
suite existed, `RecipeEngine` had no production caller at all, so nothing proved the wiring.

The VirtualPEAs run on their own loops in background threads (the pattern from
`test_api_live.py`), so the app — driven by TestClient in its own loop — reaches them over
TCP exactly as in production.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from orchestrion.api import live, recipes
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea, Project
from orchestrion.main import app
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"

_PORTS = itertools.count(48180)

CONTINUOUS, SELF_COMPLETING = 1, 2   # HC30: 1 = Continous, 2 = Duration


def _aml_text(port: int) -> str:
    return LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )


class _ServerThread:
    """A VirtualPEA on its own asyncio loop in a daemon thread."""

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
        if self._loop is None or self._stopped:
            return
        self._stopped = True
        if self._pea is not None:
            fut = asyncio.run_coroutine_threadsafe(self._pea.stop(), self._loop)
            with contextlib.suppress(Exception):
                fut.result(timeout=5)
        self._loop.call_soon_threadsafe(self._loop.stop)


@pytest.fixture
def plant():
    """A project with two connected HC30 PEAs. Yields (client, project_id, [pea_ids])."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session

    servers: list[_ServerThread] = []
    temps: list[Path] = []
    pea_ids: list[int] = []
    with Session(engine) as s:
        project = Project(name="Line A")
        s.add(project)
        s.commit()
        s.refresh(project)
        project_id = project.id
        for name in ("Reactor_A", "Reactor_B"):
            port = next(_PORTS)
            tmp = LOCAL_AML.parent / f"_ws_test_run_{port}.aml"
            tmp.write_text(_aml_text(port), encoding="utf-8")
            temps.append(tmp)
            server = _ServerThread(tmp)
            server.start()
            servers.append(server)
            row = Pea(project_id=project_id, name=name, aml_filename="HC30.aml",
                      aml_content=_aml_text(port), endpoint_url="")
            s.add(row)
            s.commit()
            s.refresh(row)
            pea_ids.append(row.id)

    # `with` is load-bearing, not tidiness. Used bare, `TestClient` spins up a **fresh
    # portal — and therefore a fresh event loop — for every request**. The OPC UA session
    # opened by `/connect` would be bound to a loop that then dies, and the engine task
    # created by `/run` would be torn down the moment that request returned. As a context
    # manager the client keeps one loop for its lifetime (and runs the app's lifespan), so
    # a run genuinely outlives the request that started it — which is the whole point.
    with TestClient(app) as client:
        for pea_id in pea_ids:
            assert client.post(f"/api/peas/{pea_id}/connect").status_code == 200
        try:
            yield client, project_id, pea_ids
        finally:
            for pea_id in pea_ids:
                with contextlib.suppress(Exception):
                    client.post(f"/api/peas/{pea_id}/disconnect")

    for server in servers:
        server.stop()
    for tmp in temps:
        tmp.unlink(missing_ok=True)
    app.dependency_overrides.clear()
    live.registry._entries.clear()
    recipes.runs._runs.clear()


def _step(step_id: str, pea_id: int, procedure_id: int = SELF_COMPLETING) -> dict:
    return {"id": step_id, "pea_id": pea_id, "service": "Stirring",
            "procedure_id": procedure_id, "params": {}}


def _always(from_ids: list[str], to_ids: list[str]) -> dict:
    return {"from_ids": from_ids, "to_ids": to_ids, "condition": {"type": "Always"}}


def _await_run(client, project_id: int, run_id: int, *, timeout: float = 60.0) -> dict:
    """Poll until the run leaves `running`/`held`/`paused`, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/projects/{project_id}/runs/{run_id}").json()
        if body["status"] not in ("running", "held", "paused"):
            return body
        time.sleep(0.1)
    pytest.fail(f"run {run_id} never finished; last state: {body}")


def test_three_step_recipe_runs_end_to_end_over_http(plant):
    """**The proof.** Three steps across two PEAs, where **s2 and s3 are consecutive on
    the same PEA using the self-completing procedure** — the exact defect.

    Every step must terminate for real, and the run must reach `completed` with nothing
    left running.
    """
    client, project_id, (pea_a, pea_b) = plant
    body = {
        "header": {"name": "Batch-42", "version": 1, "author": "Marwen"},
        "steps": [
            _step("s1", pea_a),
            _step("s2", pea_b),
            _step("s3", pea_b),      # same PEA, same service, immediately after s2
        ],
        "transitions": [
            _always(["s1"], ["s2"]),
            _always(["s2"], ["s3"]),
            _always(["s3"], ["END"]),
        ],
    }
    created = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert created.status_code == 201, created.text
    recipe_id = created.json()["id"]

    started = client.post(f"/api/projects/{project_id}/recipes/{recipe_id}/run")
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]

    final = _await_run(client, project_id, run_id)
    assert final["status"] == "completed", final
    # Every step really terminated — `done` means the transition fired *after* a latched
    # final state, not "a condition happened to be true".
    assert final["steps"] == {"s1": "done", "s2": "done", "s3": "done"}, final["steps"]
    assert final["terminal"] == {"s1": "COMPLETED", "s2": "COMPLETED", "s3": "COMPLETED"}
    assert final["finished_at"] is not None


def test_a_continuous_step_runs_over_http(plant):
    """The other procedure kind, through the API: the receptivity ends it."""
    client, project_id, (pea_a, pea_b) = plant
    body = {
        "header": {"name": "continuous"},
        "steps": [_step("s1", pea_a, CONTINUOUS), _step("s2", pea_b)],
        "transitions": [
            {"from_ids": ["s1"], "to_ids": ["s2"],
             "condition": {"type": "Elapsed", "seconds": 1.0}},
            _always(["s2"], ["END"]),
        ],
    }
    recipe_id = client.post(f"/api/projects/{project_id}/recipes", json=body).json()["id"]
    run_id = client.post(
        f"/api/projects/{project_id}/recipes/{recipe_id}/run"
    ).json()["run_id"]

    final = _await_run(client, project_id, run_id)
    assert final["status"] == "completed", final
    assert final["terminal"]["s1"] == "COMPLETED"   # ended by COMPLETE, not by itself
    assert any("Complete sent" in e["message"] for e in final["events"]), final["events"]


def test_the_run_reports_its_event_trail(plant):
    """The run's own timeline — what M5.5's live view will render."""
    client, project_id, (pea_a, _) = plant
    body = {"header": {"name": "one-step"}, "steps": [_step("s1", pea_a)],
            "transitions": [_always(["s1"], ["END"])]}
    recipe_id = client.post(f"/api/projects/{project_id}/recipes", json=body).json()["id"]
    run_id = client.post(
        f"/api/projects/{project_id}/recipes/{recipe_id}/run"
    ).json()["run_id"]

    final = _await_run(client, project_id, run_id)
    messages = [e["message"] for e in final["events"]]
    assert any("started" in m for m in messages)
    assert any("s1 terminated: COMPLETED" in m for m in messages), messages
    assert any("transition fired" in m for m in messages)
    assert any("completed" in m for m in messages)
    assert all("timestamp" in e for e in final["events"])
    # The wire contract M5.5's chart reads. `interrupted` is empty here — nothing was held —
    # but it must be *present*, or the view cannot tell "nothing held" from "old backend".
    assert final["interrupted"] == {}
    assert set(final) >= {"status", "steps", "terminal", "interrupted", "error", "events"}


def test_running_the_same_recipe_twice_is_refused(plant):
    """One live run per recipe — equipment allocation is not modelled (step model §12
    item 3), so the obvious collision is refused rather than raced."""
    client, project_id, (pea_a, _) = plant
    body = {"header": {"name": "slow"}, "steps": [_step("s1", pea_a, CONTINUOUS)],
            "transitions": [{"from_ids": ["s1"], "to_ids": ["END"],
                             "condition": {"type": "Elapsed", "seconds": 30.0}}]}
    recipe_id = client.post(f"/api/projects/{project_id}/recipes", json=body).json()["id"]
    first = client.post(f"/api/projects/{project_id}/recipes/{recipe_id}/run")
    assert first.status_code == 201, first.text

    second = client.post(f"/api/projects/{project_id}/recipes/{recipe_id}/run")
    assert second.status_code == 409, second.text
    assert "already running" in second.text

    aborted = client.post(
        f"/api/projects/{project_id}/runs/{first.json()['run_id']}/abort"
    )
    assert aborted.status_code == 200, aborted.text
    final = _await_run(client, project_id, first.json()["run_id"])
    assert final["status"] == "aborted", final
    # §7/§10 — abort commands no PEA, so it must say what it left behind.
    assert "still executing" in (final["error"] or ""), final["error"]


def test_running_with_a_disconnected_pea_is_refused_before_it_starts(plant):
    """A PEA that is not connected fails at the door, not three steps in."""
    client, project_id, (pea_a, pea_b) = plant
    body = {"header": {"name": "needs-b"},
            "steps": [_step("s1", pea_a), _step("s2", pea_b)],
            "transitions": [_always(["s1"], ["s2"]), _always(["s2"], ["END"])]}
    recipe_id = client.post(f"/api/projects/{project_id}/recipes", json=body).json()["id"]

    assert client.post(f"/api/peas/{pea_b}/disconnect").status_code == 200
    refused = client.post(f"/api/projects/{project_id}/recipes/{recipe_id}/run")
    assert refused.status_code == 409, refused.text
    assert "connect these PEAs" in refused.text and str(pea_b) in refused.text


def test_unknown_run_is_404(plant):
    client, project_id, _ = plant
    assert client.get(f"/api/projects/{project_id}/runs/999").status_code == 404
    assert client.post(f"/api/projects/{project_id}/runs/999/abort").status_code == 404
