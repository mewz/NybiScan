"""Control API: spider start/stop/status, scope gating, direct recording."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core.schemas import HistoryRecord

from ._spiderhelpers import MapOrigin, anchors

TOKEN = "spider-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        r = c.post("/projects", json={"path": str(tmp_path / "p.nybiscan"), "name": "P"}, headers=AUTH)
        assert r.status_code == 200
        yield c


def _seed(client, origin, path="/"):
    rec = HistoryRecord(scheme="http", host="127.0.0.1", port=origin.port,
                        method="GET", url=path, status=200)
    state = client.app.state.app_state
    state.project.writer.enqueue(rec)
    state.project.writer.flush()
    return client.get("/history", headers=AUTH).json()[-1]["id"]


def _wait_idle(client, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get("/spider/status", headers=AUTH).json()
        if not st["running"]:
            return st
        time.sleep(0.03)
    return client.get("/spider/status", headers=AUTH).json()


def test_spider_start_gated_by_scope(client):
    origin = MapOrigin({"/": ("text/html", anchors("/a"))})
    try:
        hid = _seed(client, origin)
        # Seed host not in scope -> refused.
        r = client.post("/spider/start", json={"seed_history_id": hid, "rate_limit_ms": 0}, headers=AUTH)
        assert r.status_code == 400 and "scope" in r.json()["detail"].lower()

        # Add to scope, then it starts.
        client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        r = client.post("/spider/start", json={"seed_history_id": hid, "rate_limit_ms": 0}, headers=AUTH)
        assert r.status_code == 200
        st = _wait_idle(client)
        assert st["found"] >= 1 and st["saved"] == st["found"]
    finally:
        origin.stop()


def test_spider_records_directly_source_spider(client):
    origin = MapOrigin({"/": ("text/html", anchors("/a", "/b"))})
    try:
        hid = _seed(client, origin)
        client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        client.post("/spider/start",
                    json={"seed_history_id": hid, "rate_limit_ms": 0, "max_depth": 2},
                    headers=AUTH)
        _wait_idle(client)
        entries = client.get("/history?limit=0", headers=AUTH).json()
        spider_paths = {e["url"] for e in entries if e["source"] == "spider"}
        assert {"/", "/a", "/b"} <= spider_paths  # crawled + recorded as spider
        # The seed row we inserted is browser-sourced; the crawl is separate.
        assert any(e["source"] == "browser" for e in entries)
    finally:
        origin.stop()


def test_spider_rejects_malformed_regex_exclude(client):
    origin = MapOrigin({"/": ("text/html", "<html></html>")})
    try:
        hid = _seed(client, origin)
        client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        r = client.post("/spider/start", json={
            "seed_history_id": hid, "rate_limit_ms": 0,
            "exclude": [{"pattern": "(unclosed", "is_regex": True}],
        }, headers=AUTH)
        assert r.status_code == 400 and "regex" in r.json()["detail"].lower()
    finally:
        origin.stop()


def test_spider_status_and_stop_when_idle(client):
    st = client.get("/spider/status", headers=AUTH).json()
    assert st == {"running": False, "found": 0, "saved": 0, "cap": 0, "current": None, "run_id": None}
    assert client.post("/spider/stop", headers=AUTH).json() == {"running": False}
