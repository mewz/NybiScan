"""GET /config and POST /config/acknowledge (authed), with on-disk persistence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core import config as core_config

TOKEN = "config-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    return TestClient(create_app(AppState(TOKEN)))


def test_config_requires_auth(client):
    assert client.get("/config").status_code == 401
    assert client.post("/config/acknowledge").status_code == 401


def test_config_defaults(client):
    r = client.get("/config", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["authorized_use_ack"] is False
    assert body["default_listen_ip"] == "127.0.0.1"
    assert body["default_listen_port"] == 8080


def test_acknowledge_persists_to_disk(client):
    r = client.post("/config/acknowledge", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["authorized_use_ack"] is True

    # Prove it hit disk: read the file fresh, bypassing any in-memory state.
    reloaded = core_config.load_global_config()
    assert reloaded["authorized_use_ack"] is True
    assert core_config.global_config_path().exists()

    # And a fresh app instance sees it too.
    fresh = TestClient(create_app(AppState(TOKEN)))
    assert fresh.get("/config", headers=AUTH).json()["authorized_use_ack"] is True
