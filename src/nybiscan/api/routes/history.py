"""History read routes (all authenticated).

GET /history returns a compact summary list for the live view; GET /history/{id}
returns the full entry including raw request/response headers and bodies. Bodies
are base64-encoded (they may be binary or, if dropped by the filter, absent).
Rich filtering and the site tree are a later plan.
"""

from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from ...core.schemas import HistoryRecord
from ...core.store import repository
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/history")


def _summary(rec: HistoryRecord) -> dict:
    return {
        "id": rec.id,
        "flow_id": rec.flow_id,
        "scheme": rec.scheme,
        "host": rec.host,
        "port": rec.port,
        "method": rec.method,
        "url": rec.url,
        "status": rec.status,
        "mime_type": rec.mime_type,
        "resp_length": rec.resp_length,
        "remote_ip": rec.remote_ip,
        "capture_status": rec.capture_status.value,
        "req_start_ts": rec.req_start_ts,
        "resp_complete_ts": rec.resp_complete_ts,
    }


def _b64(data) -> Optional[str]:
    return base64.b64encode(data).decode("ascii") if data is not None else None


def _full(rec: HistoryRecord) -> dict:
    payload = _summary(rec)
    payload.update(
        {
            "req_headers_raw": rec.req_headers_raw,
            "req_mime_type": rec.req_mime_type,
            "req_body_b64": _b64(rec.req_body),
            "req_body_dropped": rec.req_body_dropped,
            "req_content_encoding": rec.req_content_encoding,
            "resp_headers_raw": rec.resp_headers_raw,
            "resp_body_b64": _b64(rec.resp_body),
            "resp_body_dropped": rec.resp_body_dropped,
            "resp_content_encoding": rec.resp_content_encoding,
        }
    )
    return payload


@router.get("")
def list_history(
    response: Response,
    host: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    state: AppState = Depends(require_token),
):
    # limit <= 0 means "all" (SQLite LIMIT -1). X-Total-Count reports how many
    # rows match the filter so clients know whether more exist beyond this page.
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    total = repository.count_history_where(state.project.read_conn, host=host)
    recs = repository.get_history(
        state.project.read_conn, host=host, limit=limit, offset=offset, ctx=state.project.ctx
    )
    response.headers["X-Total-Count"] = str(total)
    return [_summary(r) for r in recs]


@router.get("/{entry_id}")
def get_history_entry(entry_id: int, state: AppState = Depends(require_token)):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    rec = repository.get_entry(state.project.read_conn, entry_id, ctx=state.project.ctx)
    if rec is None:
        raise HTTPException(status_code=404, detail="no such history entry")
    return _full(rec)
