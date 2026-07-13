"""Control API: scope CRUD + sitemap query. Authed; project-scoped."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core.schemas import HistoryRecord

TOKEN = "plan5-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        r = c.post("/projects", json={"path": str(tmp_path / "p.nybiscan"), "name": "P"}, headers=AUTH)
        assert r.status_code == 200
        yield c


def _seed_history(client, rec: HistoryRecord) -> int:
    state = client.app.state.app_state
    state.project.writer.enqueue(rec)
    state.project.writer.flush()
    return client.get("/history", headers=AUTH).json()[-1]["id"]


def test_scope_requires_auth(client):
    assert client.get("/scope").status_code == 401
    assert client.post("/scope", json={"host": "x"}).status_code == 401


def test_scope_add_list_update_delete(client):
    r = client.post("/scope", json={"host": "a.test", "headers": "Cookie: s=1\r\n"}, headers=AUTH)
    assert r.status_code == 200
    entries = r.json()
    assert [e["host"] for e in entries] == ["a.test"]
    assert entries[0]["headers"] == "Cookie: s=1\r\n"

    # Update session (refresh headers).
    r = client.put("/scope/a.test", json={"headers": "Cookie: s=2\r\n"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()[0]["headers"] == "Cookie: s=2\r\n"
    assert client.put("/scope/missing.test", json={"headers": "x"}, headers=AUTH).status_code == 404

    # Delete removes the row.
    assert client.delete("/scope/a.test", headers=AUTH).json() == {"deleted": True}
    assert client.get("/scope", headers=AUTH).json() == []


def test_delete_scope_leaves_spider_findings(client):
    client.post("/scope", json={"host": "a.test"}, headers=AUTH)
    _seed_history(client, HistoryRecord(
        scheme="https", host="a.test", port=443, method="GET", url="/found",
        status=200, source="spider", spider_run_id="run-x",
    ))
    client.delete("/scope/a.test", headers=AUTH)
    assert client.get("/scope", headers=AUTH).json() == []
    # The spider finding persists in history / the site-map.
    entries = client.get("/history", headers=AUTH).json()
    assert any(e["host"] == "a.test" and e["url"] == "/found" for e in entries)


def test_sitemap_tree_and_sources(client):
    _seed_history(client, HistoryRecord(scheme="https", host="www.test", port=443,
                                        method="GET", url="/index.html", status=200))
    _seed_history(client, HistoryRecord(scheme="https", host="www.test", port=443,
                                        method="GET", url="/cgi/u.php", status=200,
                                        source="spider", spider_run_id="r1"))
    hosts = client.get("/sitemap", headers=AUTH).json()
    www = next(h for h in hosts if h["host"] == "www.test")
    assert www["entry_count"] == 2

    host_map = client.get("/sitemap/www.test", headers=AUTH).json()
    # Walk to the /cgi/u.php node and confirm source attribution + entry ids.
    def find(node, full):
        if node["full_path"] == full:
            return node
        for c in node["children"]:
            hit = find(c, full)
            if hit:
                return hit
        return None

    php = find(host_map["root"], "/cgi/u.php")
    assert php is not None
    assert php["sources"] == ["spider"]
    assert len(php["entry_ids"]) == 1
    assert client.get("/sitemap/nope.test", headers=AUTH).status_code == 404
