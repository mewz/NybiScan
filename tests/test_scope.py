"""Scope repository CRUD + host_in_scope helper.

Scope stores in-scope hosts with an optional per-host session (headers). Removing a
host removes ONLY the scope row: its spider findings in history must persist.
"""

from __future__ import annotations

import pytest

from nybiscan.core import project as core_project
from nybiscan.core import scope
from nybiscan.core.schemas import CaptureStatus, HistoryRecord
from nybiscan.core.store import db, repository


def _fresh_conn(tmp_path):
    conn = db.open_connection(tmp_path / "s.db", None, check_same_thread=True)
    db.create_schema(conn)
    return conn


def test_add_list_update_remove(tmp_path):
    conn = _fresh_conn(tmp_path)
    repository.add_scope_host(conn, "a.test", note="seed", headers="Cookie: s=1\r\n")
    repository.add_scope_host(conn, "b.test")
    conn.commit()

    entries = repository.get_scope(conn)
    assert [e.host for e in entries] == ["a.test", "b.test"]  # ordered by host
    a = next(e for e in entries if e.host == "a.test")
    assert a.note == "seed" and a.headers == "Cookie: s=1\r\n"
    assert next(e for e in entries if e.host == "b.test").headers is None

    # Update session: refresh a's headers, leave the rest.
    assert repository.update_scope_headers(conn, "a.test", "Cookie: s=2\r\n") == 1
    conn.commit()
    assert next(e for e in repository.get_scope(conn) if e.host == "a.test").headers == "Cookie: s=2\r\n"

    # Re-add upserts (refreshes headers) rather than duplicating the unique host.
    repository.add_scope_host(conn, "a.test", headers="Cookie: s=3\r\n")
    conn.commit()
    hosts = [e.host for e in repository.get_scope(conn)]
    assert hosts.count("a.test") == 1
    assert next(e for e in repository.get_scope(conn) if e.host == "a.test").headers == "Cookie: s=3\r\n"

    assert repository.remove_scope_host(conn, "b.test") == 1
    conn.commit()
    assert [e.host for e in repository.get_scope(conn)] == ["a.test"]


def test_remove_scope_leaves_findings(tmp_path):
    # Deleting a scope host must NOT cascade to that host's spider history rows.
    conn = _fresh_conn(tmp_path)
    from nybiscan.core.filters import StorageContext

    sctx = StorageContext(is_encrypted=False, bodies_dir=tmp_path / "bodies", spill_threshold=1 << 20)
    (tmp_path / "bodies").mkdir()

    repository.add_scope_host(conn, "a.test")
    rec = HistoryRecord(
        scheme="https", host="a.test", port=443, method="GET", url="/found",
        status=200, capture_status=CaptureStatus.complete, source="spider",
        spider_run_id="run-1",
    )
    repository.insert_history_batch(conn, [rec], sctx)
    conn.commit()

    repository.remove_scope_host(conn, "a.test")
    conn.commit()

    assert [e.host for e in repository.get_scope(conn)] == []  # scope row gone
    # ...but the spider finding for that host persists.
    assert conn.execute(
        "SELECT count(*) FROM history WHERE host='a.test' AND source='spider'"
    ).fetchone()[0] == 1


def test_host_in_scope_exact_match():
    hosts = {"www.foo.com", "sub.foo.com"}
    assert scope.host_in_scope(hosts, "www.foo.com")
    assert scope.host_in_scope(hosts, "SUB.FOO.COM")  # case-insensitive
    assert not scope.host_in_scope(hosts, "other.foo.com")
    assert not scope.host_in_scope(hosts, "foo.com")  # exact only, no subdomain match
    assert not scope.host_in_scope(set(), "www.foo.com")
    assert not scope.host_in_scope(hosts, "")


@pytest.mark.parametrize("passphrase", [None, "scope-secret"])
def test_scope_headers_persist_through_bundle(tmp_path, passphrase):
    # Stored session headers survive close/reopen; for encrypted projects they live
    # inside the encrypted DB (sensitive session material is covered by encryption).
    bundle = tmp_path / "p.nybiscan"
    proj = core_project.create_project(bundle, name="P", passphrase=passphrase)
    proj.writer.submit(
        lambda c: repository.add_scope_host(c, "a.test", headers="Cookie: sess=abc\r\n")
    )
    proj.close()

    reopened = core_project.open_project(bundle, passphrase=passphrase)
    try:
        entry = next(e for e in repository.get_scope(reopened.read_conn) if e.host == "a.test")
        assert entry.headers == "Cookie: sess=abc\r\n"
    finally:
        reopened.close()
