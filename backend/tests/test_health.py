"""Tests for the health endpoint."""

from fastapi.testclient import TestClient

from orchestrion.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_not_served_on_the_bare_path() -> None:
    # The Vite dev proxy forwards /api/* without a rewrite, so health must live
    # behind /api or the browser never reaches it. Pinning the 404 states that
    # the prefix is the contract, not an accident of routing.
    assert client.get("/health").status_code == 404
