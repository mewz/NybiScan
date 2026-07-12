"""GET /ca/info (authed, read-only): reports the resolving CA without generating."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core import ca as core_ca
from nybiscan.core import project as core_project

TOKEN = "ca-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    return TestClient(create_app(AppState(TOKEN)))


def test_ca_info_requires_auth(client):
    assert client.get("/ca/info").status_code == 401


def test_ca_info_none_when_no_ca(client):
    body = client.get("/ca/info", headers=AUTH).json()
    assert body["scope"] == "none"
    assert body["exists"] is False


def test_ca_info_global(client):
    core_ca.generate_global()  # creates the global CA (hermetic via NYBISCAN_CA_DIR)
    body = client.get("/ca/info", headers=AUTH).json()
    assert body["scope"] == "global"
    assert body["exists"] is True
    assert len(body["fingerprint_sha256"]) == 64
    assert body["cn"]


def test_ca_export_public_cert_only(client):
    core_ca.generate_global()
    import base64

    # PEM
    r = client.post("/ca/export", json={"format": "pem"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "pem"
    pem = base64.b64decode(body["cert_b64"])
    assert pem.startswith(b"-----BEGIN CERTIFICATE-----")
    # Never the private key.
    assert b"PRIVATE KEY" not in pem

    # DER
    r = client.post("/ca/export", json={"format": "der"}, headers=AUTH)
    der = base64.b64decode(r.json()["cert_b64"])
    assert der[0] == 0x30  # DER SEQUENCE
    assert b"PRIVATE KEY" not in der


def test_ca_export_requires_auth_and_ca(client):
    assert client.post("/ca/export", json={"format": "pem"}).status_code == 401
    # No CA generated yet -> 404.
    assert client.post("/ca/export", json={"format": "pem"}, headers=AUTH).status_code == 404


def test_ca_info_project_override(client, tmp_path):
    core_ca.generate_global()
    proj = core_project.create_project(tmp_path / "p.nybiscan", name="P")
    core_ca.generate_project(proj.bundle)  # project CA overrides global
    proj.close()

    with client:
        client.post(
            "/projects/open", json={"path": str(tmp_path / "p.nybiscan")}, headers=AUTH
        )
        body = client.get("/ca/info", headers=AUTH).json()
    assert body["scope"] == "project"
    assert body["exists"] is True
