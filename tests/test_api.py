"""Control API: /health is open; project routes require the bearer token."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import AppState, create_app

TOKEN = "test-session-token"


@pytest.fixture
def client():
    app = create_app(AppState(TOKEN))
    return TestClient(app)


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_unauthenticated(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["project_open"] is False
    # /health must not leak project detail.
    assert set(body) == {"status", "version", "project_open"}


def test_projects_current_requires_token(client):
    assert client.get("/projects/current").status_code == 401
    assert client.get("/projects/current", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_project_create_open_close(client, tmp_path):
    bundle = str(tmp_path / "api.nybiscan")
    r = client.post("/projects", json={"path": bundle, "name": "ApiProj"}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["project_open"] is True
    assert r.json()["name"] == "ApiProj"

    # /health now reflects the open project without leaking its name.
    assert client.get("/health").json()["project_open"] is True

    r = client.get("/projects/current", headers=_auth())
    assert r.json()["record_count"] == 0

    assert client.post("/projects/close", headers=_auth()).json()["project_open"] is False


def test_open_encrypted_wrong_passphrase_401(client, tmp_path):
    bundle = str(tmp_path / "apienc.nybiscan")
    client.post(
        "/projects",
        json={"path": bundle, "name": "Enc", "passphrase": "right"},
        headers=_auth(),
    )
    client.post("/projects/close", headers=_auth())
    r = client.post(
        "/projects/open", json={"path": bundle, "passphrase": "wrong"}, headers=_auth()
    )
    assert r.status_code == 401
