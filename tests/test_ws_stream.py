"""WebSocket history stream: auth, and entry_created before entry_updated."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState

from ._proxyhelpers import Origin, free_port, proxy_opener

TOKEN = "ws-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client():
    return TestClient(create_app(AppState(TOKEN)))


def test_ws_receives_created_then_updated(tmp_path):
    client = _client()
    with client:
        r = client.post(
            "/projects", json={"path": str(tmp_path / "w.nybiscan"), "name": "W"}, headers=AUTH
        )
        assert r.status_code == 200

        pport = free_port()
        r = client.post("/proxy/start", json={"port": pport}, headers=AUTH)
        assert r.status_code == 200

        origin = Origin()
        try:
            with client.websocket_connect(
                "/ws/history", subprotocols=["nybiscan", TOKEN]
            ) as wsconn:
                proxy_opener(pport).open(origin.url("/json"), timeout=10).read()
                first = wsconn.receive_json()
                second = wsconn.receive_json()
        finally:
            origin.stop()

    assert first["type"] == "entry_created"
    assert second["type"] == "entry_updated"
    assert first["flow_id"] == second["flow_id"]
    assert second["capture_status"] == "complete"


def test_ws_rejects_unauthenticated(tmp_path):
    client = _client()
    with client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/history"):
                pass


def test_ws_rejects_query_param_token(tmp_path):
    # Query-param auth is deliberately unsupported (secrets in URLs).
    client = _client()
    with client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/history?token={TOKEN}"):
                pass
