"""Bench (Repeater analog) routes (all authed).

Thin over the core: the core owns the send engine, storage, and tab/history model.
Writes run on the single writer thread via project.writer.submit(); reads use the
read connection. Bench sends record into bench_history only, never the main proxy
history.
"""

from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.bench import engine
from ...core.bench import repository as brepo
from ...core.bench import seed
from ...core.bench.schemas import BenchSend, BenchTab
from ...core.store import repository as hrepo
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/bench")

_BLANK_REQUEST = "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"


def _require_project(state: AppState):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    return state.project


def _tab_payload(tab: BenchTab) -> dict:
    return {
        "id": tab.id, "name": tab.name, "order_index": tab.order_index,
        "raw_request": tab.raw_request, "conn_host": tab.conn_host,
        "conn_port": tab.conn_port, "conn_tls": tab.conn_tls,
        "content_length_autofill": tab.content_length_autofill,
    }


def _send_summary(s: BenchSend) -> dict:
    return {
        "id": s.id, "tab_id": s.tab_id, "status": s.status,
        "resp_length": s.resp_length, "mime_type": s.mime_type,
        "error": s.error, "sent_ts": s.sent_ts, "duration_ms": s.duration_ms,
    }


def _send_full(s: BenchSend) -> dict:
    payload = _send_summary(s)
    payload.update({
        "req_raw": s.req_raw, "conn_host": s.conn_host, "conn_port": s.conn_port,
        "conn_tls": s.conn_tls, "content_length_autofill": s.content_length_autofill,
        "resp_headers_raw": s.resp_headers_raw,
        "resp_body_b64": base64.b64encode(s.resp_body).decode("ascii") if s.resp_body is not None else None,
        "resp_content_encoding": s.resp_content_encoding,
    })
    return payload


class CreateTabRequest(BaseModel):
    name: Optional[str] = None
    seed_history_id: Optional[int] = None


class UpdateTabRequest(BaseModel):
    name: Optional[str] = None
    order_index: Optional[int] = None
    raw_request: Optional[str] = None
    conn_host: Optional[str] = None
    conn_port: Optional[int] = None
    conn_tls: Optional[bool] = None
    content_length_autofill: Optional[bool] = None


@router.get("/tabs")
def list_tabs(state: AppState = Depends(require_token)):
    proj = _require_project(state)
    return [_tab_payload(t) for t in brepo.list_tabs(proj.read_conn)]


@router.post("/tabs")
def create_tab(req: CreateTabRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    dropped_note = None
    if req.seed_history_id is not None:
        rec = hrepo.get_entry(proj.read_conn, req.seed_history_id, ctx=proj.ctx)
        if rec is None:
            raise HTTPException(status_code=404, detail="no such history entry")
        raw, host, port, tls, dropped_note = seed.raw_request_from_history(rec)
        name = req.name or f"{rec.host}"
    else:
        raw, host, port, tls = _BLANK_REQUEST, "example.com", 443, True
        name = req.name or "Bench"

    tab_id = proj.writer.submit(
        lambda c: brepo.create_tab(c, name, raw, host, port, tls, True)
    )
    tab = brepo.get_tab(proj.read_conn, tab_id)
    payload = _tab_payload(tab)
    if dropped_note:
        payload["dropped_note"] = dropped_note
    return payload


@router.patch("/tabs/{tab_id}")
def update_tab(tab_id: int, req: UpdateTabRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    if brepo.get_tab(proj.read_conn, tab_id) is None:
        raise HTTPException(status_code=404, detail="no such bench tab")
    proj.writer.submit(lambda c: brepo.update_tab(c, tab_id, **req.model_dump(exclude_none=True)))
    return _tab_payload(brepo.get_tab(proj.read_conn, tab_id))


@router.delete("/tabs/{tab_id}")
def delete_tab(tab_id: int, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    proj.writer.submit(lambda c: brepo.delete_tab(c, tab_id))
    return {"deleted": True}


@router.post("/tabs/{tab_id}/send")
def send_tab(tab_id: int, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    tab = brepo.get_tab(proj.read_conn, tab_id)
    if tab is None:
        raise HTTPException(status_code=404, detail="no such bench tab")
    # The raw request text is the wire payload (verbatim); the connection target is
    # the tab's host/port/tls, NEVER derived from the Host header.
    raw_bytes = tab.raw_request.encode("utf-8", errors="surrogateescape")
    resp = engine.send_raw(
        tab.conn_host, tab.conn_port, tab.conn_tls, raw_bytes, tab.content_length_autofill
    )
    send_id = proj.writer.submit(
        lambda c: brepo.insert_send(
            c, tab_id, tab.raw_request, tab.conn_host, tab.conn_port, tab.conn_tls,
            tab.content_length_autofill, resp,
        )
    )
    return _send_full(brepo.get_send(proj.read_conn, send_id))


@router.get("/tabs/{tab_id}/history")
def tab_history(tab_id: int, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    return [_send_summary(s) for s in brepo.list_tab_history(proj.read_conn, tab_id)]


@router.get("/history/{entry_id}")
def send_detail(entry_id: int, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    send = brepo.get_send(proj.read_conn, entry_id)
    if send is None:
        raise HTTPException(status_code=404, detail="no such bench send")
    return _send_full(send)
