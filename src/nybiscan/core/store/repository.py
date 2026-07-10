"""Typed insert/query helpers over the history/sites/scope/meta tables.

Used by the batched writer (inserts) and by the API/CLI (reads). Body handling
(filter + spill) happens here so it is applied consistently on every insert.
"""

from __future__ import annotations

from typing import List, Optional

from .. import filters
from ..filters import StorageContext
from ..schemas import CaptureStatus, HistoryRecord, ProjectMeta, ScopeEntry
from . import db

_INSERT_SQL = (
    "INSERT INTO history ("
    + ", ".join(db._HISTORY_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" for _ in db._HISTORY_COLUMNS)
    + ")"
)

_SELECT_COLS = "id, " + ", ".join(db._HISTORY_COLUMNS)

_SITE_SQL = (
    "INSERT INTO sites (host, path, first_seen_ts, hits) VALUES (?, ?, ?, 1) "
    "ON CONFLICT(host, path) DO UPDATE SET hits = hits + 1"
)


# ----- meta -----------------------------------------------------------------


def set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def init_meta(conn, name: str, uuid: str, created_ts: int, encrypted: bool) -> None:
    set_meta(conn, "schema_version", str(db.SCHEMA_VERSION))
    set_meta(conn, "name", name)
    set_meta(conn, "uuid", uuid)
    set_meta(conn, "created_ts", str(created_ts))
    set_meta(conn, "encrypted", "1" if encrypted else "0")
    conn.commit()


def read_project_meta(conn) -> ProjectMeta:
    return ProjectMeta(
        name=get_meta(conn, "name") or "",
        uuid=get_meta(conn, "uuid") or "",
        created_ts=int(get_meta(conn, "created_ts") or 0),
        schema_version=int(get_meta(conn, "schema_version") or db.SCHEMA_VERSION),
        encrypted=(get_meta(conn, "encrypted") == "1"),
        record_count=count_history(conn),
    )


# ----- history writes -------------------------------------------------------


def _record_to_row(rec: HistoryRecord, ctx: StorageContext) -> tuple:
    req_blob, req_ref, req_dropped, req_len = filters.prepare_body(
        rec.req_body, rec.req_mime_type, ctx
    )
    resp_blob, resp_ref, resp_dropped, resp_len = filters.prepare_body(
        rec.resp_body, rec.mime_type, ctx
    )
    return (
        rec.scheme,
        rec.host,
        rec.port,
        rec.method,
        rec.url,
        rec.req_headers_raw,
        rec.req_mime_type,
        req_blob,
        req_ref,
        int(req_dropped),
        req_len or rec.req_length,
        rec.req_start_ts,
        rec.status,
        resp_len or rec.resp_length,
        rec.mime_type,
        rec.remote_ip,
        rec.resp_headers_raw,
        resp_blob,
        resp_ref,
        int(resp_dropped),
        rec.resp_complete_ts,
        rec.capture_status.value,
    )


def insert_history_batch(conn, records: List[HistoryRecord], ctx: StorageContext) -> None:
    """Insert a batch of records plus their site rows. Caller commits once."""
    rows = [_record_to_row(r, ctx) for r in records]
    site_rows = [(r.host, r.path, r.req_start_ts) for r in records]
    conn.executemany(_INSERT_SQL, rows)
    conn.executemany(_SITE_SQL, site_rows)


# ----- history reads --------------------------------------------------------


def _row_to_record(row: tuple, ctx: Optional[StorageContext]) -> HistoryRecord:
    (
        rid,
        scheme,
        host,
        port,
        method,
        url,
        req_headers_raw,
        req_mime_type,
        req_body,
        req_body_ref,
        req_body_dropped,
        req_length,
        req_start_ts,
        status,
        resp_length,
        mime_type,
        remote_ip,
        resp_headers_raw,
        resp_body,
        resp_body_ref,
        resp_body_dropped,
        resp_complete_ts,
        capture_status,
    ) = row

    if req_body is None and req_body_ref and ctx is not None:
        req_body = filters.load_spilled_body(req_body_ref, ctx)
    if resp_body is None and resp_body_ref and ctx is not None:
        resp_body = filters.load_spilled_body(resp_body_ref, ctx)

    return HistoryRecord(
        id=rid,
        scheme=scheme,
        host=host,
        port=port,
        method=method,
        url=url,
        req_headers_raw=req_headers_raw,
        req_mime_type=req_mime_type,
        req_body=bytes(req_body) if req_body is not None else None,
        req_body_ref=req_body_ref,
        req_body_dropped=bool(req_body_dropped),
        req_length=req_length,
        req_start_ts=req_start_ts,
        status=status,
        resp_length=resp_length,
        mime_type=mime_type,
        remote_ip=remote_ip,
        resp_headers_raw=resp_headers_raw,
        resp_body=bytes(resp_body) if resp_body is not None else None,
        resp_body_ref=resp_body_ref,
        resp_body_dropped=bool(resp_body_dropped),
        resp_complete_ts=resp_complete_ts,
        capture_status=CaptureStatus(capture_status),
    )


def count_history(conn) -> int:
    return conn.execute("SELECT count(*) FROM history").fetchone()[0]


def get_entry(conn, entry_id: int, ctx: Optional[StorageContext] = None) -> Optional[HistoryRecord]:
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM history WHERE id = ?", (entry_id,)
    ).fetchone()
    return _row_to_record(row, ctx) if row else None


def get_history(
    conn,
    host: Optional[str] = None,
    limit: int = 500,
    ctx: Optional[StorageContext] = None,
) -> List[HistoryRecord]:
    if host:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM history WHERE host = ? ORDER BY id LIMIT ?",
            (host, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM history ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_record(r, ctx) for r in rows]


# ----- scope ----------------------------------------------------------------


def set_scope(conn, hosts: List[str]) -> None:
    conn.execute("DELETE FROM scope")
    conn.executemany(
        "INSERT OR IGNORE INTO scope (host) VALUES (?)", [(h,) for h in hosts]
    )
    conn.commit()


def get_scope(conn) -> List[ScopeEntry]:
    rows = conn.execute("SELECT id, host, note FROM scope ORDER BY host").fetchall()
    return [ScopeEntry(id=r[0], host=r[1], note=r[2]) for r in rows]
