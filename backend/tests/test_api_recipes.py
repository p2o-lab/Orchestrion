"""Recipe CRUD over HTTP — create/list/get/update/delete + validation against project PEAs."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from orchestrion.db.engine import get_session
from orchestrion.main import app

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def pea(client):
    """A project with one imported HC30 PEA. Returns (project_id, pea_id)."""
    project_id = client.post("/api/projects", json={"name": "Line A"}).json()["id"]
    r = client.post(
        f"/api/projects/{project_id}/peas",
        data={"name": "Reactor_A"},
        files={"file": ("HC30.aml", LOCAL_AML.read_bytes(), "application/xml")},
    )
    assert r.status_code == 201, r.text
    return project_id, r.json()["id"]


def _recipe(pea_id: int, *, service="Stirring", procedure_id=1, state="COMPLETED") -> dict:
    return {
        "header": {"name": "Batch-42", "version": 1, "author": "Marwen"},
        "formula": {"stir_minutes": 5.0},
        "steps": [{"id": "s1", "pea_id": pea_id, "service": service,
                   "procedure_id": procedure_id, "params": {}}],
        "transitions": [{"from_ids": ["s1"], "to_ids": ["END"],
                         "condition": {"type": "StateReached", "pea_id": pea_id, "service": service, "state": state}}],
    }


def test_create_list_get_recipe(pea, client):
    project_id, pea_id = pea
    r = client.post(f"/api/projects/{project_id}/recipes", json=_recipe(pea_id))
    assert r.status_code == 201, r.text
    recipe_id = r.json()["id"]
    assert r.json()["name"] == "Batch-42"
    assert r.json()["step_count"] == 1

    listed = client.get(f"/api/projects/{project_id}/recipes").json()
    assert [x["id"] for x in listed] == [recipe_id]

    detail = client.get(f"/api/projects/{project_id}/recipes/{recipe_id}").json()
    assert detail["definition"]["steps"][0]["service"] == "Stirring"
    assert detail["definition"]["transitions"][0]["condition"]["state"] == "COMPLETED"


def test_canvas_positions_survive_save_and_reload(pea, client):
    """The layout an author arranged must come back — for **both** node kinds.

    Steps have carried `x`/`y` since M5.4; transitions did not, so every one you dragged was
    recomputed from its neighbours on the next visit and the chart rearranged itself. This
    pins the whole chain the position travels: POST -> stored JSON -> GET.
    """
    project_id, pea_id = pea
    body = _recipe(pea_id)
    body["steps"][0]["x"], body["steps"][0]["y"] = 120.0, 40.0
    body["transitions"][0]["x"], body["transitions"][0]["y"] = 310.0, -64.0

    recipe_id = client.post(f"/api/projects/{project_id}/recipes", json=body).json()["id"]
    definition = client.get(
        f"/api/projects/{project_id}/recipes/{recipe_id}"
    ).json()["definition"]

    assert (definition["steps"][0]["x"], definition["steps"][0]["y"]) == (120.0, 40.0)
    assert (definition["transitions"][0]["x"], definition["transitions"][0]["y"]) == (310.0, -64.0)


def test_a_recipe_without_positions_is_still_accepted(pea, client):
    """They are optional, so every recipe saved before transitions had coordinates loads."""
    project_id, pea_id = pea
    recipe_id = client.post(
        f"/api/projects/{project_id}/recipes", json=_recipe(pea_id)
    ).json()["id"]
    transition = client.get(
        f"/api/projects/{project_id}/recipes/{recipe_id}"
    ).json()["definition"]["transitions"][0]
    assert transition["x"] is None and transition["y"] is None


def test_update_and_delete_recipe(pea, client):
    project_id, pea_id = pea
    recipe_id = client.post(f"/api/projects/{project_id}/recipes", json=_recipe(pea_id)).json()["id"]

    body = _recipe(pea_id)
    body["header"]["version"] = 2
    up = client.put(f"/api/projects/{project_id}/recipes/{recipe_id}", json=body)
    assert up.status_code == 200 and up.json()["version"] == 2

    assert client.delete(f"/api/projects/{project_id}/recipes/{recipe_id}").status_code == 204
    assert client.get(f"/api/projects/{project_id}/recipes/{recipe_id}").status_code == 404


def test_unknown_pea_rejected(pea, client):
    project_id, pea_id = pea
    r = client.post(f"/api/projects/{project_id}/recipes", json=_recipe(pea_id + 999))
    assert r.status_code == 422 and "not in this project" in r.text


def test_unknown_service_rejected(pea, client):
    project_id, pea_id = pea
    r = client.post(f"/api/projects/{project_id}/recipes", json=_recipe(pea_id, service="Nope"))
    assert r.status_code == 422 and "service 'Nope'" in r.text


def test_unknown_procedure_rejected(pea, client):
    project_id, pea_id = pea
    r = client.post(f"/api/projects/{project_id}/recipes", json=_recipe(pea_id, procedure_id=999))
    assert r.status_code == 422 and "procedure 999" in r.text


def test_bad_state_name_rejected(pea, client):
    project_id, pea_id = pea
    r = client.post(f"/api/projects/{project_id}/recipes", json=_recipe(pea_id, state="RUNNING"))
    assert r.status_code == 422 and "Table 14" in r.text  # RUNNING is ISA-88, MTP uses EXECUTE


def test_unknown_value_in_threshold_rejected(pea, client):
    project_id, pea_id = pea
    body = {
        "header": {"name": "vt"},
        "steps": [{"id": "s1", "pea_id": pea_id, "service": "Stirring", "procedure_id": 1, "params": {}}],
        "transitions": [{"from_ids": ["s1"], "to_ids": ["END"], "condition": {
            "type": "ValueThreshold", "pea_id": pea_id, "value_name": "NoSuchValue",
            "op": ">", "threshold": 1.0}}],
    }
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422 and "NoSuchValue" in r.text


def test_structural_validation_still_applies(pea, client):
    project_id, pea_id = pea
    body = _recipe(pea_id)
    body["transitions"][0]["to_ids"] = ["ghost"]  # unknown step id — caught by the model
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422 and "unknown step id" in r.text


# ── graph shape ─────────────────────────────────────────────────────────────────────
#
# The engine guards these too, but a recipe can be POSTed straight past the builder —
# which is exactly how the integration test works — so the API is the real gate. HC30
# ships procedure 1 = Continous (not self-completing) and 2 = Duration (self-completing).

CONTINUOUS, SELF_COMPLETING = 1, 2


def _steps(pea_id: int, *ids: str, procedure_id: int = SELF_COMPLETING) -> list[dict]:
    return [
        {"id": i, "pea_id": pea_id, "service": "Stirring",
         "procedure_id": procedure_id, "params": {}}
        for i in ids
    ]


def _always(from_ids: list[str], to_ids: list[str]) -> dict:
    return {"from_ids": from_ids, "to_ids": to_ids, "condition": {"type": "Always"}}


def test_zero_initial_steps_rejected(pea, client):
    """A closed loop leaves no step untargeted — and the engine would then report
    `completed` having done nothing. [IEC 61512-1] item 1337 wants a defined beginning."""
    project_id, pea_id = pea
    body = {"header": {"name": "cycle"}, "steps": _steps(pea_id, "s1", "s2"),
            "transitions": [_always(["s1"], ["s2"]), _always(["s2"], ["s1"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "exactly one initial step" in r.text and "found none" in r.text


def test_several_initial_steps_rejected(pea, client):
    """Two beginnings would start both on live equipment at once."""
    project_id, pea_id = pea
    body = {"header": {"name": "two-beginnings"}, "steps": _steps(pea_id, "s1", "s2"),
            "transitions": [_always(["s1"], ["END"]), _always(["s2"], ["END"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "exactly one initial step" in r.text and "['s1', 's2']" in r.text


def test_a_downstream_cycle_is_rejected_and_named(pea, client):
    """s1 is a valid beginning, so the initial-step rule passes — but s2 and s3 loop.
    The error has to name them or it is not actionable."""
    project_id, pea_id = pea
    body = {"header": {"name": "loop"}, "steps": _steps(pea_id, "s1", "s2", "s3"),
            "transitions": [_always(["s1"], ["s2"]), _always(["s2"], ["s3"]),
                            _always(["s3"], ["s2"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "loops back on itself" in r.text and "['s2', 's3']" in r.text


def test_a_parallel_diamond_is_not_mistaken_for_a_cycle(pea, client):
    """A split and re-join is not a loop — the cycle check must not over-reach."""
    project_id, pea_id = pea
    body = {"header": {"name": "diamond"}, "steps": _steps(pea_id, "s0", "sA", "sB", "s4"),
            "transitions": [_always(["s0"], ["sA", "sB"]), _always(["sA", "sB"], ["s4"]),
                            _always(["s4"], ["END"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 201, r.text


def test_always_on_a_continuous_step_rejected(pea, client):
    """`Always` on a continuous step would start the service and complete it in the same
    instant — its receptivity IS the completion criterion (step model §2)."""
    project_id, pea_id = pea
    body = {"header": {"name": "bad-continuous"},
            "steps": _steps(pea_id, "s1", procedure_id=CONTINUOUS),
            "transitions": [_always(["s1"], ["END"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "continuous procedure" in r.text and "'s1'" in r.text


def test_always_on_a_self_completing_step_is_fine(pea, client):
    """The same chart with the self-completing procedure is exactly what `Always` is for."""
    project_id, pea_id = pea
    body = {"header": {"name": "good"}, "steps": _steps(pea_id, "s1"),
            "transitions": [_always(["s1"], ["END"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 201, r.text


def test_always_is_rejected_on_a_join_fed_by_a_continuous_step(pea, client):
    """The rule is stated over the whole `from_ids`, not one step's exit — a continuous
    step may also feed an AND-join (chart §4, §5(b))."""
    project_id, pea_id = pea
    steps = _steps(pea_id, "s0", "sB", "s4") + _steps(pea_id, "sA", procedure_id=CONTINUOUS)
    body = {"header": {"name": "mixed-join"}, "steps": steps,
            "transitions": [_always(["s0"], ["sA", "sB"]), _always(["sA", "sB"], ["s4"]),
                            _always(["s4"], ["END"])]}
    r = client.post(f"/api/projects/{project_id}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "continuous procedure" in r.text and "'sA'" in r.text
