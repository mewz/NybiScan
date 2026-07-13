"""SQLite helpers for Bench tabs and per-send history.

Writes run on the single writer thread via BatchWriter.submit(); reads use the
read connection. Bench bodies are stored in-db (encrypted projects keep them
inside the encrypted db; the text-only capture filter does not apply to Bench).
"""

from __future__ import annotations

import time
from typing import List, Optional

from .schemas import BenchSend, BenchTab

_TAB_COLS = (
    "id, name, order_index, raw_request, conn_host, conn_port, conn_tls, "
    "content_length_autofill, created_ts, updated_ts"
)
_SEND_COLS = (
    "id, tab_id, req_raw, conn_host, conn_port, conn_tls, content_length_autofill, "
    "status, resp_headers_raw, resp_body, resp_length, mime_type, "
    "resp_content_encoding, error, sent_ts, duration_ms"
)
_UPDATABLE = {
    "name", "order_index", "raw_request", "conn_host", "conn_port",
    "conn_tls", "content_length_autofill",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _row_to_tab(row) -> BenchTab:
    return BenchTab(
        id=row[0], name=row[1], order_index=row[2], raw_request=row[3],
        conn_host=row[4], conn_port=row[5], conn_tls=bool(row[6]),
        content_length_autofill=bool(row[7]), created_ts=row[8], updated_ts=row[9],
    )


def _row_to_send(row, include_body: bool = True) -> BenchSend:
    body = row[9]
    return BenchSend(
        id=row[0], tab_id=row[1], req_raw=row[2], conn_host=row[3], conn_port=row[4],
        conn_tls=bool(row[5]), content_length_autofill=bool(row[6]), status=row[7],
        resp_headers_raw=row[8],
        resp_body=(bytes(body) if include_body and body is not None else None),
        resp_length=row[10], mime_type=row[11], resp_content_encoding=row[12],
        error=row[13], sent_ts=row[14], duration_ms=row[15],
    )


# ----- tabs (writes go through writer.submit) -------------------------------


def create_tab(
    conn, name: str, raw_request: str, conn_host: str, conn_port: int,
    conn_tls: bool, content_length_autofill: bool,
) -> int:
    now = _now_ms()
    order_index = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) + 1 FROM bench_tabs"
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO bench_tabs (name, order_index, raw_request, conn_host, conn_port, "
        "conn_tls, content_length_autofill, created_ts, updated_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, order_index, raw_request, conn_host, conn_port, int(conn_tls),
         int(content_length_autofill), now, now),
    )
    return cur.lastrowid


def update_tab(conn, tab_id: int, **fields) -> None:
    sets, values = [], []
    for key, value in fields.items():
        if key not in _UPDATABLE or value is None:
            continue
        if key in ("conn_tls", "content_length_autofill"):
            value = int(bool(value))
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return
    sets.append("updated_ts = ?")
    values.append(_now_ms())
    values.append(tab_id)
    conn.execute(f"UPDATE bench_tabs SET {', '.join(sets)} WHERE id = ?", values)


def delete_tab(conn, tab_id: int) -> None:
    conn.execute("DELETE FROM bench_history WHERE tab_id = ?", (tab_id,))
    conn.execute("DELETE FROM bench_tabs WHERE id = ?", (tab_id,))


def insert_send(
    conn, tab_id: int, req_raw: str, conn_host: str, conn_port: int, conn_tls: bool,
    content_length_autofill: bool, resp: dict,
) -> int:
    cur = conn.execute(
        "INSERT INTO bench_history (tab_id, req_raw, conn_host, conn_port, conn_tls, "
        "content_length_autofill, status, resp_headers_raw, resp_body, resp_length, "
        "mime_type, resp_content_encoding, error, sent_ts, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tab_id, req_raw, conn_host, conn_port, int(conn_tls),
            int(content_length_autofill), resp.get("status"),
            resp.get("resp_headers_raw", ""), resp.get("resp_body"),
            resp.get("resp_length", 0), resp.get("mime_type"),
            resp.get("resp_content_encoding"), resp.get("error"),
            _now_ms(), resp.get("duration_ms", 0),
        ),
    )
    return cur.lastrowid


# ----- reads (use the read connection) --------------------------------------


def get_tab(conn, tab_id: int) -> Optional[BenchTab]:
    row = conn.execute(
        f"SELECT {_TAB_COLS} FROM bench_tabs WHERE id = ?", (tab_id,)
    ).fetchone()
    return _row_to_tab(row) if row else None


def list_tabs(conn) -> List[BenchTab]:
    rows = conn.execute(
        f"SELECT {_TAB_COLS} FROM bench_tabs ORDER BY order_index, id"
    ).fetchall()
    return [_row_to_tab(r) for r in rows]


def list_tab_history(conn, tab_id: int) -> List[BenchSend]:
    rows = conn.execute(
        f"SELECT {_SEND_COLS} FROM bench_history WHERE tab_id = ? ORDER BY id",
        (tab_id,),
    ).fetchall()
    # List omits bodies (kept lean); GET /bench/history/{id} returns the full body.
    return [_row_to_send(r, include_body=False) for r in rows]


def get_send(conn, send_id: int) -> Optional[BenchSend]:
    row = conn.execute(
        f"SELECT {_SEND_COLS} FROM bench_history WHERE id = ?", (send_id,)
    ).fetchone()
    return _row_to_send(row, include_body=True) if row else None
