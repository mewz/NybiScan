"""Schema migration to the current version (v1 -> v4 and v2 -> v4)."""

from __future__ import annotations

import pytest

from nybiscan.core import config, crypto
from nybiscan.core import project as core_project
from nybiscan.core.store import db

# The v1 history schema (pre-Plan-2): no flow_id, content_encoding, or extension.
_V1_HISTORY = """
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheme TEXT NOT NULL, host TEXT NOT NULL, port INTEGER NOT NULL,
    method TEXT NOT NULL, url TEXT NOT NULL,
    req_headers_raw TEXT NOT NULL DEFAULT '', req_mime_type TEXT,
    req_body BLOB, req_body_ref TEXT, req_body_dropped INTEGER NOT NULL DEFAULT 0,
    req_length INTEGER NOT NULL DEFAULT 0, req_start_ts INTEGER NOT NULL DEFAULT 0,
    status INTEGER, resp_length INTEGER NOT NULL DEFAULT 0, mime_type TEXT,
    remote_ip TEXT, resp_headers_raw TEXT NOT NULL DEFAULT '',
    resp_body BLOB, resp_body_ref TEXT, resp_body_dropped INTEGER NOT NULL DEFAULT 0,
    resp_complete_ts INTEGER, capture_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX idx_history_host ON history(host);
"""

# The v2 history schema: adds flow_id + content_encoding (NO extension yet).
_V2_HISTORY = """
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id TEXT,
    scheme TEXT NOT NULL, host TEXT NOT NULL, port INTEGER NOT NULL,
    method TEXT NOT NULL, url TEXT NOT NULL,
    req_headers_raw TEXT NOT NULL DEFAULT '', req_mime_type TEXT,
    req_body BLOB, req_body_ref TEXT, req_body_dropped INTEGER NOT NULL DEFAULT 0,
    req_length INTEGER NOT NULL DEFAULT 0, req_content_encoding TEXT,
    req_start_ts INTEGER NOT NULL DEFAULT 0,
    status INTEGER, resp_length INTEGER NOT NULL DEFAULT 0, mime_type TEXT,
    remote_ip TEXT, resp_headers_raw TEXT NOT NULL DEFAULT '',
    resp_body BLOB, resp_body_ref TEXT, resp_body_dropped INTEGER NOT NULL DEFAULT 0,
    resp_content_encoding TEXT,
    resp_complete_ts INTEGER, capture_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX idx_history_host ON history(host);
CREATE INDEX idx_history_flow_id ON history(flow_id);
"""

_COMMON_TABLES = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sites (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL,
    path TEXT NOT NULL, first_seen_ts INTEGER NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0, UNIQUE(host, path));
CREATE TABLE scope (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL UNIQUE, note TEXT);
"""


def _build_bundle(bundle, history_ddl, version, passphrase=None):
    bundle = core_project._normalize_bundle(bundle)
    bundle.mkdir(parents=True)
    (bundle / "ca").mkdir()
    encrypted = passphrase is not None
    if not encrypted:
        (bundle / "bodies").mkdir()

    key = None
    enc_block = {"enabled": False}
    if encrypted:
        params = crypto.default_kdf_params()
        key = crypto.derive_key(passphrase, params)
        enc_block = {
            "enabled": True, "kdf": params.kdf, "argon2_version": params.argon2_version,
            "m_cost": params.m_cost, "t_cost": params.t_cost,
            "parallelism": params.parallelism, "salt": params.salt,
        }

    conn = db.open_connection(bundle / "session.db", key, check_same_thread=True)
    conn.executescript(_COMMON_TABLES + history_ddl)
    for k, v in [
        ("schema_version", str(version)), ("name", "Legacy"), ("uuid", "legacy-uuid"),
        ("created_ts", "1700000000000"), ("encrypted", "1" if encrypted else "0"),
    ]:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (k, v))
    conn.execute(
        "INSERT INTO history (scheme, host, port, method, url, status, capture_status) "
        "VALUES ('http','a.test',80,'GET','/done',200,'complete')"
    )
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    config.write_project_toml(
        bundle,
        {
            "project": {"name": "Legacy", "uuid": "legacy-uuid", "created_ts": 1700000000000, "scope": []},
            "listen": {"ip": "127.0.0.1", "port": 8080},
            "encryption": enc_block,
        },
    )
    return bundle


def _assert_current(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(history)").fetchall()}
    assert {"flow_id", "req_content_encoding", "resp_content_encoding", "extension"} <= cols
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(history)").fetchall()}
    assert "idx_history_flow_id" in indexes
    # v4: Bench tables present.
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"bench_tabs", "bench_history"} <= tables
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "4"


@pytest.mark.parametrize("passphrase", [None, "correct horse"])
def test_migrate_v1_to_current(tmp_path, passphrase):
    bundle = _build_bundle(tmp_path / "v1.nybiscan", _V1_HISTORY, 1, passphrase=passphrase)
    proj = core_project.open_project(bundle, passphrase=passphrase)
    try:
        _assert_current(proj.read_conn)
        db.migrate(proj.read_conn)  # idempotent no-op
        _assert_current(proj.read_conn)
    finally:
        proj.close()


@pytest.mark.parametrize("passphrase", [None, "correct horse"])
def test_migrate_v2_to_current(tmp_path, passphrase):
    # A REAL v2 schema (flow_id + content_encoding present, extension absent):
    # migrate must add ONLY extension without a duplicate-column error.
    bundle = _build_bundle(tmp_path / "v2.nybiscan", _V2_HISTORY, 2, passphrase=passphrase)

    proj = core_project.open_project(bundle, passphrase=passphrase)  # runs migrate
    _assert_current(proj.read_conn)
    # pre-existing row has a NULL extension read back correctly...
    assert proj.read_conn.execute(
        "SELECT extension FROM history WHERE url='/done'"
    ).fetchone() == (None,)
    proj.close()

    # ...and for the encrypted case, a full cycle THROUGH the cipher: reopen and
    # read the new column back, proving ALTER + read work under SQLCipher.
    reopened = core_project.open_project(bundle, passphrase=passphrase)
    try:
        _assert_current(reopened.read_conn)
        assert reopened.read_conn.execute(
            "SELECT extension FROM history WHERE url='/done'"
        ).fetchone() == (None,)
    finally:
        reopened.close()
