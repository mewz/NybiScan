"""Passive site-map query: host -> path tree over history, with source attribution."""

from __future__ import annotations

from nybiscan.core import sitemap
from nybiscan.core.filters import StorageContext
from nybiscan.core.schemas import CaptureStatus, HistoryRecord
from nybiscan.core.store import db, repository


def _conn(tmp_path):
    conn = db.open_connection(tmp_path / "m.db", None, check_same_thread=True)
    db.create_schema(conn)
    return conn


def _ctx(tmp_path):
    (tmp_path / "bodies").mkdir(exist_ok=True)
    return StorageContext(is_encrypted=False, bodies_dir=tmp_path / "bodies", spill_threshold=1 << 20)


def _rec(host, url, method="GET", status=200, source="browser", scheme="https", port=443):
    return HistoryRecord(
        scheme=scheme, host=host, port=port, method=method, url=url, status=status,
        source=source, capture_status=CaptureStatus.complete,
    )


def _find(node, full_path):
    if node.full_path == full_path:
        return node
    for c in node.children:
        hit = _find(c, full_path)
        if hit:
            return hit
    return None


def test_tree_groups_hosts_and_paths(tmp_path):
    conn = _conn(tmp_path)
    ctx = _ctx(tmp_path)
    repository.insert_history_batch(conn, [
        _rec("www.test.com", "/index.html"),
        _rec("www.test.com", "/cgi-bin/update_user.php"),
        _rec("www.test.com", "/cgi-bin/update_user.php?id=2"),  # same path, query differs
        _rec("api.test.com", "/v1/users"),
    ], ctx)
    conn.commit()

    hosts = sitemap.build_sitemap(conn)
    by_host = {h.host: h for h in hosts}
    assert set(by_host) == {"www.test.com", "api.test.com"}
    assert by_host["www.test.com"].entry_count == 3

    www = by_host["www.test.com"].root
    assert _find(www, "/index.html") is not None
    cgi = _find(www, "/cgi-bin")
    assert cgi is not None and cgi.entry_ids == []  # internal dir, no direct entry
    php = _find(www, "/cgi-bin/update_user.php")
    assert php is not None and len(php.entry_ids) == 2  # both queries collapse to one path


def test_node_references_entry_ids_and_sources(tmp_path):
    conn = _conn(tmp_path)
    ctx = _ctx(tmp_path)
    repository.insert_history_batch(conn, [
        _rec("h.test", "/a", source="browser"),
        _rec("h.test", "/a", source="spider"),
    ], ctx)
    conn.commit()

    host = sitemap.build_host_map(conn, "h.test")
    assert host is not None
    node = _find(host.root, "/a")
    assert sorted(node.sources) == ["browser", "spider"]  # source attribution
    ids = conn.execute("SELECT id FROM history ORDER BY id").fetchall()
    assert node.entry_ids == [ids[0][0], ids[1][0]]


def test_scheme_and_port_split_hosts(tmp_path):
    conn = _conn(tmp_path)
    ctx = _ctx(tmp_path)
    repository.insert_history_batch(conn, [
        _rec("dup.test", "/x", scheme="http", port=80),
        _rec("dup.test", "/x", scheme="https", port=443),
    ], ctx)
    conn.commit()
    hosts = sitemap.build_sitemap(conn)
    keys = {(h.scheme, h.host, h.port) for h in hosts}
    assert keys == {("http", "dup.test", 80), ("https", "dup.test", 443)}


def test_empty_history_is_empty_map(tmp_path):
    conn = _conn(tmp_path)
    assert sitemap.build_sitemap(conn) == []
    assert sitemap.build_host_map(conn, "nope.test") is None
