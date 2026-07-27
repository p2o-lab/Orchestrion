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
