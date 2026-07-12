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
        rec.flow_id,
        rec.scheme,
        rec.host,
        rec.port,
        rec.method,
        rec.url,
        rec.extension,
        rec.req_headers_raw,
        rec.req_mime_type,
        req_blob,
        req_ref,
        int(req_dropped),
        req_len or rec.req_length,
        rec.req_content_encoding,
        rec.req_start_ts,
        rec.status,
        resp_len or rec.resp_length,
        rec.mime_type,
        rec.remote_ip,
        rec.resp_headers_raw,
        resp_blob,
        resp_ref,
        int(resp_dropped),
        rec.resp_content_encoding,
        rec.resp_complete_ts,
        rec.capture_status.value,
    )


def insert_history_batch(conn, records: List[HistoryRecord], ctx: StorageContext) -> None:
    """Insert a batch of records plus their site rows. Caller commits once."""
    rows = [_record_to_row(r, ctx) for r in records]
    site_rows = [(r.host, r.path, r.req_start_ts) for r in records]
    conn.executemany(_INSERT_SQL, rows)
    conn.executemany(_SITE_SQL, site_rows)


_UPDATE_RESPONSE_SQL = """
UPDATE history SET
    status = ?, resp_length = ?, mime_type = ?, remote_ip = ?, resp_headers_raw = ?,
    resp_body = ?, resp_body_ref = ?, resp_body_dropped = ?, resp_content_encoding = ?,
    resp_complete_ts = ?, capture_status = ?
WHERE flow_id = ?
"""


def update_response_by_flow(conn, flow_id: str, patch: HistoryRecord, ctx: StorageContext) -> None:
    """Apply a response (pending -> complete) to the row with this flow_id."""
    resp_blob, resp_ref, resp_dropped, resp_len = filters.prepare_body(
        patch.resp_body, patch.mime_type, ctx
    )
    conn.execute(
        _UPDATE_RESPONSE_SQL,
        (
            patch.status,
            resp_len or patch.resp_length,
            patch.mime_type,
            patch.remote_ip,
            patch.resp_headers_raw,
            resp_blob,
            resp_ref,
            int(resp_dropped),
            patch.resp_content_encoding,
            patch.resp_complete_ts,
            patch.capture_status.value,
            flow_id,
        ),
    )


def set_capture_status_by_flow(conn, flow_id: str, status: CaptureStatus) -> None:
    """Flip capture_status for a flow (e.g. pending -> error) without touching bodies."""
    conn.execute(
        "UPDATE history SET capture_status = ? WHERE flow_id = ?",
        (status.value, flow_id),
    )


def mark_pending_interrupted(conn) -> int:
    """On open, any leftover pending rows are from a prior hard kill: mark error."""
    cur = conn.execute(
        "UPDATE history SET capture_status = 'error' WHERE capture_status = 'pending'"
    )
    conn.commit()
    return cur.rowcount


def get_by_flow_id(conn, flow_id: str, ctx: Optional[StorageContext] = None):
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM history WHERE flow_id = ? ORDER BY id DESC LIMIT 1",
        (flow_id,),
    ).fetchone()
    return _row_to_record(row, ctx) if row else None


# ----- history reads --------------------------------------------------------


def _row_to_record(row: tuple, ctx: Optional[StorageContext]) -> HistoryRecord:
    (
        rid,
        flow_id,
        scheme,
        host,
        port,
        method,
        url,
        extension,
        req_headers_raw,
        req_mime_type,
        req_body,
        req_body_ref,
        req_body_dropped,
        req_length,
        req_content_encoding,
        req_start_ts,
        status,
        resp_length,
        mime_type,
        remote_ip,
        resp_headers_raw,
        resp_body,
        resp_body_ref,
        resp_body_dropped,
        resp_content_encoding,
        resp_complete_ts,
        capture_status,
    ) = row

    if req_body is None and req_body_ref and ctx is not None:
        req_body = filters.load_spilled_body(req_body_ref, ctx)
    if resp_body is None and resp_body_ref and ctx is not None:
        resp_body = filters.load_spilled_body(resp_body_ref, ctx)

    return HistoryRecord(
        id=rid,
        flow_id=flow_id,
        scheme=scheme,
        host=host,
        port=port,
        method=method,
        url=url,
        extension=extension,
        req_headers_raw=req_headers_raw,
        req_mime_type=req_mime_type,
        req_body=bytes(req_body) if req_body is not None else None,
        req_body_ref=req_body_ref,
        req_body_dropped=bool(req_body_dropped),
        req_length=req_length,
        req_content_encoding=req_content_encoding,
        req_start_ts=req_start_ts,
        status=status,
        resp_length=resp_length,
        mime_type=mime_type,
        remote_ip=remote_ip,
        resp_headers_raw=resp_headers_raw,
        resp_body=bytes(resp_body) if resp_body is not None else None,
        resp_body_ref=resp_body_ref,
        resp_body_dropped=bool(resp_body_dropped),
        resp_content_encoding=resp_content_encoding,
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
    offset: int = 0,
    ctx: Optional[StorageContext] = None,
) -> List[HistoryRecord]:
    # SQLite treats LIMIT -1 as "no limit"; map any non-positive limit to that so
    # callers can request every row (with OFFSET for paging).
    sql_limit = limit if (limit is not None and limit > 0) else -1
    if host:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM history WHERE host = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (host, sql_limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM history ORDER BY id LIMIT ? OFFSET ?",
            (sql_limit, offset),
        ).fetchall()
    return [_row_to_record(r, ctx) for r in rows]


def count_history_where(conn, host: Optional[str] = None) -> int:
    if host:
        return conn.execute(
            "SELECT count(*) FROM history WHERE host = ?", (host,)
        ).fetchone()[0]
    return conn.execute("SELECT count(*) FROM history").fetchone()[0]


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
