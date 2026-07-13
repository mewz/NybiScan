"""Scope-gated crawl engine: in-scope BFS, depth, seed subtree, exclude, binary skip,
cross-host scope, request cap, prompt stop, per-host session headers, direct recording."""

from __future__ import annotations

import time

from nybiscan.core import project as core_project
from nybiscan.core.schemas import CaptureStatus, HistoryRecord
from nybiscan.core.spider.engine import SpiderConfig, SpiderEngine

from ._spiderhelpers import MapOrigin, anchors


def _proj(tmp_path):
    return core_project.create_project(tmp_path / "p.nybiscan", name="P")


def _seed(origin, path="/", host="127.0.0.1"):
    return HistoryRecord(
        scheme="http", host=host, port=origin.port, method="GET", url=path,
        capture_status=CaptureStatus.complete,
    )


def _run(engine, timeout=10.0):
    engine.start()
    deadline = time.time() + timeout
    while engine.running and time.time() < deadline:
        time.sleep(0.02)
    engine.stop()


def _spider_rows(proj, run_id):
    proj.writer.flush()
    return proj.read_conn.execute(
        "SELECT url, source, spider_run_id FROM history WHERE spider_run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def test_crawl_scope_depth_exclude_binary_and_offhost(tmp_path):
    off = MapOrigin({"/cross": ("text/html", "<html>x</html>")})
    origin = MapOrigin({
        "/": ("text/html", anchors("/a", "/b", "/sub/deep", "/logout", "/img.png",
                                   f"http://localhost:{off.port}/cross")),
        "/a": ("text/html", anchors("/a/child")),
    })
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=3, rate_limit_ms=0, max_requests=50),
            scope_hosts={"127.0.0.1"}, scope_headers={}, seed_record=_seed(origin),
        )
        _run(eng)
        paths = set(origin.paths)
        assert {"/", "/a", "/b", "/sub/deep", "/a/child"} <= paths
        assert "/logout" not in paths           # excluded by default
        assert "/img.png" not in paths          # binary skipped by default
        assert off.requested == []              # out-of-scope host never fetched

        rows = _spider_rows(proj, eng.run_id)
        assert all(r[1] == "spider" and r[2] == eng.run_id for r in rows)
        assert eng._found == len(rows)          # found == saved after flush
    finally:
        proj.close(); origin.stop(); off.stop()


def test_never_ascends_above_seed_path(tmp_path):
    origin = MapOrigin({
        "/a": ("text/html", anchors("/a/child", "/")),  # links up to / and down to child
    })
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=3, rate_limit_ms=0, max_requests=50),
            scope_hosts={"127.0.0.1"}, scope_headers={}, seed_record=_seed(origin, path="/a"),
        )
        _run(eng)
        paths = set(origin.paths)
        assert "/a" in paths and "/a/child" in paths
        assert "/" not in paths  # never ascends above the seed path
    finally:
        proj.close(); origin.stop()


def test_cross_host_followed_only_when_in_scope(tmp_path):
    other = MapOrigin({"/cross": ("text/html", "<html>x</html>")})
    origin = MapOrigin({"/": ("text/html", anchors(f"http://localhost:{other.port}/cross"))})
    proj = _proj(tmp_path)
    try:
        # localhost IS in scope now -> the cross-host link is followed.
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=3, rate_limit_ms=0, max_requests=50),
            scope_hosts={"127.0.0.1", "localhost"}, scope_headers={}, seed_record=_seed(origin),
        )
        _run(eng)
        assert "/cross" in set(other.paths)
    finally:
        proj.close(); origin.stop(); other.stop()


def test_stops_at_max_requests(tmp_path):
    origin = MapOrigin({"/": ("text/html", anchors(*[f"/p{i}" for i in range(10)]))})
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=3, rate_limit_ms=0, max_requests=3),
            scope_hosts={"127.0.0.1"}, scope_headers={}, seed_record=_seed(origin),
        )
        _run(eng)
        assert eng._found == 3
        assert len(origin.requested) == 3  # hard cap honored
    finally:
        proj.close(); origin.stop()


def test_stop_is_prompt_under_high_rate_limit(tmp_path):
    origin = MapOrigin({"/": ("text/html", anchors("/a", "/b", "/c", "/d"))})
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=3, rate_limit_ms=60000, max_requests=50),
            scope_hosts={"127.0.0.1"}, scope_headers={}, seed_record=_seed(origin),
        )
        eng.start()
        time.sleep(0.2)  # let the first fetch land, then it enters the long wait
        t0 = time.time()
        eng.stop(timeout=5)
        assert time.time() - t0 < 2.0        # interruptible wait -> prompt stop
        assert not eng.running
        assert eng._found < 5                # did not crawl everything
    finally:
        proj.close(); origin.stop()


def test_per_host_session_headers(tmp_path):
    other = MapOrigin({"/cross": ("text/html", "<html>x</html>")})
    origin = MapOrigin({
        "/": ("text/html", anchors("/a", f"http://localhost:{other.port}/cross")),
    })
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=2, rate_limit_ms=0, max_requests=50),
            scope_hosts={"127.0.0.1", "localhost"},
            scope_headers={
                "127.0.0.1": "GET / HTTP/1.1\r\nHost: x\r\nCookie: sess=one\r\n\r\n",
                "localhost": "GET / HTTP/1.1\r\nHost: x\r\nCookie: sess=two\r\n\r\n",
            },
            seed_record=_seed(origin),
        )
        _run(eng)
        # Each host receives its OWN stored session, never the other's.
        assert origin.cookies["/"] == "sess=one"
        assert other.cookies["/cross"] == "sess=two"
    finally:
        proj.close(); origin.stop(); other.stop()


def test_in_scope_host_without_headers_is_unauthenticated(tmp_path):
    origin = MapOrigin({"/": ("text/html", anchors("/a"))})
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=1, rate_limit_ms=0, max_requests=50),
            scope_hosts={"127.0.0.1"}, scope_headers={}, seed_record=_seed(origin),
        )
        _run(eng)
        assert origin.cookies["/"] is None  # no stored headers -> no session sent
    finally:
        proj.close(); origin.stop()


def test_config_defaults():
    cfg = SpiderConfig(seed_history_id=0)
    assert cfg.max_depth == 5
    assert cfg.exclude == [{"pattern": "/logout", "is_regex": False}]  # single default


def test_include_binary_option(tmp_path):
    origin = MapOrigin({"/": ("text/html", anchors("/img.png"))})
    proj = _proj(tmp_path)
    try:
        eng = SpiderEngine(
            proj, SpiderConfig(seed_history_id=0, max_depth=1, rate_limit_ms=0,
                               max_requests=50, include_binary=True),
            scope_hosts={"127.0.0.1"}, scope_headers={}, seed_record=_seed(origin),
        )
        _run(eng)
        assert "/img.png" in set(origin.paths)  # fetched when include_binary is on
    finally:
        proj.close(); origin.stop()
