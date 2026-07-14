"""MCP tool logic, hermetic: a TestClient-backed Caller against a real temp project.
No live server, no MCP SDK. Proves the tools are thin wrappers that surface the core's
enforcement (and the one agent-path bench scope-gate)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core.schemas import CaptureStatus, HistoryRecord
from nybiscan.mcp import tools
from nybiscan.mcp.caller import Result

from ._spiderhelpers import MapOrigin, anchors

TOKEN = "mcp-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class TCCaller:
    """A Caller backed by a FastAPI TestClient (in-process, hermetic)."""

    def __init__(self, client: TestClient, token: str = TOKEN):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    def request(self, method, path, json_body=None, params=None):
        p = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self.client.request(method, path, json=json_body, params=p or None, headers=self.headers)
        try:
            body = resp.json()
        except Exception:
            body = None
        return Result(resp.status_code, body, dict(resp.headers))


@pytest.fixture
def caller(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        assert c.post("/projects", json={"path": str(tmp_path / "p.nybiscan"), "name": "P"},
                      headers=AUTH).status_code == 200
        yield TCCaller(c)


def _seed(caller, host="ex.test", url="/api", body=b'{"user":"admin"}', mime="application/json",
          source="browser"):
    state = caller.client.app.state.app_state
    state.project.writer.enqueue(HistoryRecord(
        scheme="https", host=host, port=443, method="GET", url=url,
        status=200, mime_type=mime, resp_body=body, source=source,
        capture_status=CaptureStatus.complete))
    state.project.writer.flush()
    return caller.client.get("/history", headers=AUTH).json()[-1]["id"]


# ----- read tools -----


def test_list_history_and_scope_and_sitemap(caller):
    _seed(caller, host="a.test", url="/x")
    _seed(caller, host="b.test", url="/y")
    assert {e["host"] for e in tools.list_history(caller)} == {"a.test", "b.test"}
    assert [e["host"] for e in tools.list_history(caller, host="a.test")] == ["a.test"]

    caller.client.post("/scope", json={"host": "a.test"}, headers=AUTH)
    assert [e["host"] for e in tools.get_scope(caller)] == ["a.test"]

    hosts = {h["host"] for h in tools.get_sitemap(caller)}
    assert {"a.test", "b.test"} <= hosts


def test_get_request_response_decodes_body(caller):
    eid = _seed(caller, body=b'{"secret":"decoded-not-base64"}')
    out = tools.get_request_response(caller, eid)
    assert out["response"]["body"]["text"] == '{"secret":"decoded-not-base64"}'  # decoded to text
    assert out["source"] == "browser"


def test_get_request_response_large_body_full_and_range(caller):
    big = "y" * 300_000
    eid = _seed(caller, body=big.encode(), mime="text/plain")
    default = tools.get_request_response(caller, eid)
    assert default["response"]["body"]["truncated"] is True
    assert default["response"]["body"]["total_chars"] == 300_000
    full = tools.get_request_response(caller, eid, full=True)
    assert full["response"]["body"]["text"] == big  # fully retrievable
    window = tools.get_request_response(caller, eid, offset=10, length=20)
    assert window["response"]["body"]["text"] == big[10:30]


# ----- active tools + scope enforcement -----


def test_spider_start_out_of_scope_surfaces_core_refusal(caller):
    eid = _seed(caller, host="ex.test", url="/")
    with pytest.raises(tools.ToolError) as ei:
        tools.spider_start(caller, eid, rate_limit_ms=0)
    assert "not in scope" in str(ei.value) and "retry" in str(ei.value)
    # The refusal came from the core (400), not from the MCP: adding scope lets it start.
    caller.client.post("/scope", json={"host": "ex.test"}, headers=AUTH)
    st = tools.spider_start(caller, eid, rate_limit_ms=0)
    assert st["run_id"]
    tools.spider_stop(caller)


def test_bench_send_agent_path_scope_gate(caller):
    origin = MapOrigin({"/": ("text/html", anchors("/a"))})
    try:
        tab = tools.bench_create(caller)
        # Out-of-scope target host -> refused, NO send happens.
        with pytest.raises(tools.ToolError) as ei:
            tools.bench_send(caller, tab["id"], raw_request="GET / HTTP/1.1\r\nHost: h\r\n\r\n",
                             host="127.0.0.1", port=origin.port, tls=False)
        assert "not in scope" in str(ei.value)
        assert origin.requested == []  # never sent

        # Direct/GUI Bench send to the SAME out-of-scope host still works (unrestricted).
        caller.client.post(f"/bench/tabs/{tab['id']}/send", headers=AUTH)
        assert origin.requested  # the direct path sent

        # In scope -> the MCP bench send goes through.
        caller.client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        out = tools.bench_send(caller, tab["id"])
        assert out["status"] == 200
        assert out["resp_body"]["text"].startswith("<html>")
    finally:
        origin.stop()


def test_agent_fetch_tool_scope_gated_and_decoded(caller):
    origin = MapOrigin({"/": ("text/html", "<html>hey</html>")})
    try:
        url = f"http://127.0.0.1:{origin.port}/"
        with pytest.raises(tools.ToolError):
            tools.agent_fetch(caller, url)  # out of scope
        caller.client.post("/scope", json={"host": "127.0.0.1"}, headers=AUTH)
        out = tools.agent_fetch(caller, url)
        assert out["source"] == "agent"
        assert out["resp_body"]["text"] == "<html>hey</html>"
    finally:
        origin.stop()


def test_no_project_surfaces_clear_error(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        caller = TCCaller(c)
        with pytest.raises(tools.ToolError) as ei:
            tools.list_history(caller)
        assert "no project open" in str(ei.value)


def test_scope_is_read_only_to_the_agent():
    # No scope-write tools are exposed - scope is a human-owned boundary.
    for name in ("scope_add", "scope_update", "scope_remove", "add_scope", "remove_scope"):
        assert not hasattr(tools, name)
    assert hasattr(tools, "get_scope")
