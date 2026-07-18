"""PEA import + CRUD over HTTP — the workspace import flow, in-memory DB."""

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
def project(client):
    return client.post("/api/projects", json={"name": "Line A"}).json()["id"]


def _import(client, project_id, name="Stirrer", content=None, filename="HC30.aml"):
    content = content if content is not None else LOCAL_AML.read_bytes()
    return client.post(
        f"/api/projects/{project_id}/peas",
        data={"name": name},
        files={"file": (filename, content, "application/xml")},
    )


def test_import_valid_mtp_stores_and_returns_summary(client, project):
    resp = _import(client, project)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Stirrer"
    assert body["endpoint_url"] == "opc.tcp://127.0.0.1:48050"
    assert body["project_id"] == project

    # it now shows up in the project's PEA list + bumps the project's pea_count
    listed = client.get(f"/api/projects/{project}/peas").json()
    assert [p["name"] for p in listed] == ["Stirrer"]
    assert client.get(f"/api/projects/{project}").json()["pea_count"] == 1


def test_import_invalid_mtp_is_rejected_with_a_highlightable_error(client, project):
    resp = _import(client, project, content=b"<not-an-mtp/>", filename="bad.aml")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "MtpStructureError"
    assert "CAEXFile" in detail["detail"]           # the message the UI highlights
    # nothing was stored
    assert client.get(f"/api/projects/{project}/peas").json() == []


def test_pea_detail_exposes_services_procedures_and_nodes(client, project):
    pea_id = _import(client, project).json()["id"]
    detail = client.get(f"/api/peas/{pea_id}").json()

    assert len(detail["services"]) == 1
    service = detail["services"][0]
    assert service["name"] == "Stirring"
    assert {p["procedure_id"] for p in service["procedures"]} == {1, 2}
    node_names = {n["name"] for n in service["control_nodes"]}
    assert {"StateCur", "CommandExt", "StateAutOp", "SrcExtOp"} <= node_names
    statecur = next(n for n in service["control_nodes"] if n["name"] == "StateCur")
    assert statecur["access"] == "READ"
    assert statecur["identifier_type"] == "STRING"


def test_pea_detail_exposes_the_value_model(client, project):
    """PEA-wide process values carry kind/direction/writable for the UI to render."""
    pea_id = _import(client, project).json()["id"]
    detail = client.get(f"/api/peas/{pea_id}").json()

    values = {v["name"]: v for v in detail["process_values"]}
    assert set(values) == {
        "HC30_Target_Full", "HC30_Self_Full", "HC30_FlowView_F13", "HC30_LevelView_L10",
    }
    # the incoming one is writable (POL→PEA); outgoing ones are read-only.
    assert values["HC30_Target_Full"] == {
        "name": "HC30_Target_Full", "kind": "binary", "direction": "in", "writable": True,
    }
    assert values["HC30_FlowView_F13"]["kind"] == "analog"
    assert values["HC30_FlowView_F13"]["direction"] == "out"
    assert values["HC30_FlowView_F13"]["writable"] is False

    # HC30 declares no config params / report values — the fields exist and are empty.
    service = detail["services"][0]
    assert service["config_parameters"] == []
    for procedure in service["procedures"]:
        assert procedure["report_values"] == []
        assert procedure["process_values"] == []


def test_rename_and_delete_pea(client, project):
    pea_id = _import(client, project).json()["id"]
    assert client.patch(f"/api/peas/{pea_id}", json={"name": "Mixer"}).json()["name"] == "Mixer"
    assert client.delete(f"/api/peas/{pea_id}").status_code == 204
    assert client.get(f"/api/peas/{pea_id}").status_code == 404
