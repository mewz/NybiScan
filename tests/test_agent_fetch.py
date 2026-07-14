"""POST /agent/fetch: scope-gated direct fetch recorded as source='agent'."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState

from ._spiderhelpers import MapOrigin, anchors

TOKEN = "agent-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        r = c.post("/projects", json={"path": str(tmp_path / "p.nybiscan"), "name": "P"}, headers=AUTH)
        assert r.status_code == 200
        yield c


def test_agent_fetch_requires_scope(client):
    origin = MapOrigin({"/": ("text/html", "<html>hi</html>")})
    try:
        url = f"http://127.0.0.1:{origin.port}/"
        # Out of scope -> refused with an actionable message.
        r = client.post("/agent/fetch", json={"url": url}, headers=AUTH)
        assert r.status_code == 400
        assert "not in scope" in r.json()["detail"] and "retry" in r.json()["detail"]

        client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        r = client.post("/agent/fetch", json={"url": url}, headers=AUTH)
        assert r.status_code == 200
        entry = r.json()
        assert entry["source"] == "agent"
        assert entry["status"] == 200
        assert base64.b64decode(entry["resp_body_b64"]).startswith(b"<html>")
    finally:
        origin.stop()


def test_agent_fetch_lands_in_history_and_sitemap(client):
    origin = MapOrigin({"/page": ("text/html", anchors("/x"))})
    try:
        client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        url = f"http://127.0.0.1:{origin.port}/page"
        client.post("/agent/fetch", json={"url": url}, headers=AUTH)

        # Appears in history tagged agent...
        hist = client.get("/history?limit=0", headers=AUTH).json()
        agent_rows = [e for e in hist if e["source"] == "agent"]
        assert len(agent_rows) == 1 and agent_rows[0]["url"] == "/page"
        # ...and in the site-map.
        hosts = client.get("/sitemap", headers=AUTH).json()
        h = next(x for x in hosts if x["host"] == "127.0.0.1")

        def find(node, full):
            if node["full_path"] == full:
                return node
            for c in node["children"]:
                got = find(c, full)
                if got:
                    return got
            return None

        node = find(h["root"], "/page")
        assert node is not None and node["sources"] == ["agent"]
    finally:
        origin.stop()


def test_agent_fetch_forwards_headers(client):
    origin = MapOrigin({"/": ("text/html", "<html></html>")})
    try:
        client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        url = f"http://127.0.0.1:{origin.port}/"
        client.post("/agent/fetch",
                    json={"url": url, "headers": {"X-Agent": "nybi", "Cookie": "s=1"}},
                    headers=AUTH)
        seen = origin.headers_seen["/"]
        assert seen.get("X-Agent") == "nybi" and seen.get("Cookie") == "s=1"
    finally:
        origin.stop()


def test_agent_fetch_no_project(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        r = c.post("/agent/fetch", json={"url": "http://x/"}, headers=AUTH)
        assert r.status_code == 409
