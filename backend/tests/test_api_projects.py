"""Project CRUD over HTTP, against an in-memory DB (get_session overridden)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from orchestrion.db.engine import get_session
from orchestrion.main import app


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


def test_create_and_list_projects(client):
    assert client.get("/api/projects").json() == []

    created = client.post("/api/projects", json={"name": "Reactor Line A"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Reactor Line A"
    assert body["pea_count"] == 0
    assert body["id"]

    listed = client.get("/api/projects").json()
    assert [p["name"] for p in listed] == ["Reactor Line A"]


def test_get_missing_project_is_404(client):
    assert client.get("/api/projects/999").status_code == 404


def test_rename_project(client):
    pid = client.post("/api/projects", json={"name": "old"}).json()["id"]
    renamed = client.patch(f"/api/projects/{pid}", json={"name": "new"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "new"
    assert client.get(f"/api/projects/{pid}").json()["name"] == "new"


def test_delete_project(client):
    pid = client.post("/api/projects", json={"name": "temp"}).json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404
