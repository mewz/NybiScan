"""Schema v1 -> v2 migration, for plaintext and encrypted bundles."""

from __future__ import annotations

import pytest

from nybiscan.core import config, crypto
from nybiscan.core import project as core_project
from nybiscan.core.store import db

# The v1 history schema (pre-Plan-2): no flow_id, no content_encoding columns.
_V1_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
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
CREATE TABLE sites (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL,
    path TEXT NOT NULL, first_seen_ts INTEGER NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0, UNIQUE(host, path));
CREATE TABLE scope (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL UNIQUE, note TEXT);
"""


def _build_v1_bundle(bundle, passphrase=None):
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
            "enabled": True,
            "kdf": params.kdf,
            "argon2_version": params.argon2_version,
            "m_cost": params.m_cost,
            "t_cost": params.t_cost,
            "parallelism": params.parallelism,
            "salt": params.salt,
        }

    conn = db.open_connection(bundle / "session.db", key, check_same_thread=True)
    conn.executescript(_V1_DDL)
    for k, v in [
        ("schema_version", "1"),
        ("name", "Legacy"),
        ("uuid", "legacy-uuid"),
        ("created_ts", "1700000000000"),
        ("encrypted", "1" if encrypted else "0"),
    ]:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (k, v))
    # one complete row + one pending row (pending should be swept on open)
    conn.execute(
        "INSERT INTO history (scheme, host, port, method, url, status, capture_status) "
        "VALUES ('http','a.test',80,'GET','/done',200,'complete')"
    )
    conn.execute(
        "INSERT INTO history (scheme, host, port, method, url, capture_status) "
        "VALUES ('http','a.test',80,'GET','/hung','pending')"
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


def _assert_v2(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(history)").fetchall()}
    assert {"flow_id", "req_content_encoding", "resp_content_encoding"} <= cols
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(history)").fetchall()}
    assert "idx_history_flow_id" in indexes
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "2"


@pytest.mark.parametrize("passphrase", [None, "correct horse"])
def test_migrate_v1_to_v2(tmp_path, passphrase):
    bundle = _build_v1_bundle(tmp_path / "legacy.nybiscan", passphrase=passphrase)

    proj = core_project.open_project(bundle, passphrase=passphrase)
    try:
        _assert_v2(proj.read_conn)

        # pending row swept to error on open; complete row untouched.
        rows = {
            r[0]: r[1]
            for r in proj.read_conn.execute("SELECT url, capture_status FROM history")
        }
        assert rows["/done"] == "complete"
        assert rows["/hung"] == "error"

        # Idempotent: re-running migrate is a no-op.
        db.migrate(proj.read_conn)
        _assert_v2(proj.read_conn)
    finally:
        proj.close()
