"""Database connection + schema.

One entry point, open_connection(), handles both plaintext SQLite and encrypted
SQLCipher. WAL is required on both paths.

SQLCipher ordering note: on the encrypted path, PRAGMA key MUST run before any
other statement (including PRAGMA journal_mode). We then run a cheap validation
SELECT so a wrong passphrase fails immediately with a clear error. If
test_wal_enabled ever fails ONLY for the SQLCipher database, suspect pragma
ordering or the bundled sqlcipher3 wheel version, not app logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..errors import WrongPassphraseError

SCHEMA_VERSION = 1

_HISTORY_COLUMNS = (
    "scheme",
    "host",
    "port",
    "method",
    "url",
    "req_headers_raw",
    "req_mime_type",
    "req_body",
    "req_body_ref",
    "req_body_dropped",
    "req_length",
    "req_start_ts",
    "status",
    "resp_length",
    "mime_type",
    "remote_ip",
    "resp_headers_raw",
    "resp_body",
    "resp_body_ref",
    "resp_body_dropped",
    "resp_complete_ts",
    "capture_status",
)

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scheme            TEXT    NOT NULL,
    host              TEXT    NOT NULL,
    port              INTEGER NOT NULL,
    method            TEXT    NOT NULL,
    url               TEXT    NOT NULL,
    req_headers_raw   TEXT    NOT NULL DEFAULT '',
    req_mime_type     TEXT,
    req_body          BLOB,
    req_body_ref      TEXT,
    req_body_dropped  INTEGER NOT NULL DEFAULT 0,
    req_length        INTEGER NOT NULL DEFAULT 0,
    req_start_ts      INTEGER NOT NULL DEFAULT 0,
    status            INTEGER,
    resp_length       INTEGER NOT NULL DEFAULT 0,
    mime_type         TEXT,
    remote_ip         TEXT,
    resp_headers_raw  TEXT    NOT NULL DEFAULT '',
    resp_body         BLOB,
    resp_body_ref     TEXT,
    resp_body_dropped INTEGER NOT NULL DEFAULT 0,
    resp_complete_ts  INTEGER,
    capture_status    TEXT    NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_history_host ON history(host);

CREATE TABLE IF NOT EXISTS sites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    host          TEXT    NOT NULL,
    path          TEXT    NOT NULL,
    first_seen_ts INTEGER NOT NULL DEFAULT 0,
    hits          INTEGER NOT NULL DEFAULT 0,
    UNIQUE(host, path)
);

CREATE TABLE IF NOT EXISTS scope (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    host TEXT    NOT NULL UNIQUE,
    note TEXT
);
"""


def _connect(path: str, key: Optional[bytes], check_same_thread: bool):
    if key is None:
        import sqlite3

        return sqlite3.connect(path, check_same_thread=check_same_thread)

    from sqlcipher3 import dbapi2 as sqlcipher

    conn = sqlcipher.connect(path, check_same_thread=check_same_thread)
    # PRAGMA key must be the very first statement on an encrypted connection.
    conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
    return conn


def open_connection(
    path: Path | str,
    key: Optional[bytes] = None,
    check_same_thread: bool = True,
):
    """Open a connection in WAL mode. Encrypted iff key is not None.

    Raises WrongPassphraseError if an encrypted db cannot be decrypted.
    """
    conn = _connect(str(path), key, check_same_thread)

    if key is not None:
        # Force a read that touches the (encrypted) header. Wrong key -> error.
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except Exception as exc:  # sqlcipher raises DatabaseError on bad key
            conn.close()
            raise WrongPassphraseError(
                "Failed to open encrypted project: wrong passphrase or corrupt database."
            ) from exc

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        conn.close()
        raise RuntimeError(f"WAL not enabled (journal_mode={mode!r})")

    return conn


def create_schema(conn) -> None:
    conn.executescript(_DDL)
    conn.commit()
