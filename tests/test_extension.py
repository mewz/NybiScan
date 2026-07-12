"""parse_extension edge cases + capture wiring + /history exposure."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core import project as core_project
from nybiscan.core.proxy.capture import parse_extension

from .conftest import make_record


@pytest.mark.parametrize(
    "url,expected",
    [
        ("/foo.php?x=1", "php"),          # query stripped
        ("/report.7z", "7z"),
        ("/style.CSS", "css"),            # lowercased
        ("/a.b.c/d.min.js", "js"),        # last segment, last dot
        ("/", None),
        ("/api/users", None),
        ("/path/", None),                 # trailing slash, empty segment
        ("/api/v2.1/users", None),        # version in a non-last segment
        ("/api/v2.1", None),              # numeric candidate rejected
        ("/backup.2024", None),           # date/version, not an extension
        ("/.htaccess", None),             # dotfile, no basename
        ("/file.", None),                 # empty candidate after the dot
        ("/download?file=x.zip", None),   # never from a query value
        ("/x.superlongext123", None),     # over the length cap
    ],
)
def test_parse_extension(url, expected):
    assert parse_extension(url) == expected


def test_record_from_request_sets_extension():
    from mitmproxy.test import tflow

    flow = tflow.tflow()
    flow.request.path = "/assets/app.min.js?v=3"
    from nybiscan.core.proxy import capture

    rec = capture.record_from_request(flow)
    assert rec.extension == "js"


def test_history_endpoint_exposes_extension(tmp_path):
    token = "ext-token"
    client = TestClient(create_app(AppState(token)))
    auth = {"Authorization": f"Bearer {token}"}
    with client:
        client.post(
            "/projects", json={"path": str(tmp_path / "e.nybiscan"), "name": "E"}, headers=auth
        )
        state = client.app.state.app_state
        state.project.writer.enqueue(make_record(url="/app.js", extension="js"))
        state.project.writer.enqueue(make_record(url="/api/users", extension=None))
        state.project.writer.flush()

        rows = client.get("/history", headers=auth).json()
    by_url = {r["url"]: r["extension"] for r in rows}
    assert by_url["/app.js"] == "js"
    assert by_url["/api/users"] is None
