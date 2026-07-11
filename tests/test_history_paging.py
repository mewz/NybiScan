"""History paging: limit, offset, unlimited, and the X-Total-Count header."""

from __future__ import annotations

from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core import project as core_project
from nybiscan.core.store import repository

from .conftest import make_record

TOKEN = "paging-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _seed(proj, n):
    for i in range(n):
        proj.writer.enqueue(make_record(url=f"/p/{i}"))
    proj.writer.flush()


def test_repository_limit_offset_and_all(tmp_path):
    proj = core_project.create_project(tmp_path / "pg.nybiscan", name="PG")
    _seed(proj, 250)

    assert repository.count_history_where(proj.read_conn) == 250
    assert len(repository.get_history(proj.read_conn, limit=200, ctx=proj.ctx)) == 200
    # limit <= 0 means "all"
    assert len(repository.get_history(proj.read_conn, limit=0, ctx=proj.ctx)) == 250
    # offset paging
    page = repository.get_history(proj.read_conn, limit=100, offset=240, ctx=proj.ctx)
    assert len(page) == 10
    assert page[0].url == "/p/240"
    proj.close()


def test_api_total_count_header_and_paging(tmp_path):
    client = TestClient(create_app(AppState(TOKEN)))
    with client:
        client.post(
            "/projects", json={"path": str(tmp_path / "api.nybiscan"), "name": "A"}, headers=AUTH
        )
        state = client.app.state.app_state
        _seed(state.project, 250)

        # Default limit caps the page but the header reports the true total.
        r = client.get("/history?limit=200", headers=AUTH)
        assert len(r.json()) == 200
        assert r.headers["X-Total-Count"] == "250"

        # Unlimited.
        r = client.get("/history?limit=0", headers=AUTH)
        assert len(r.json()) == 250

        # Offset page.
        r = client.get("/history?limit=100&offset=240", headers=AUTH)
        body = r.json()
        assert len(body) == 10
        assert body[0]["url"] == "/p/240"
