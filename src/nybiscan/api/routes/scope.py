"""Scope routes (all authed).

Scope is the spider's boundary and the authorized-use guard. Each in-scope host may
carry a stored session (raw request headers, incl. Cookie) so the spider crawls that
host authenticated. DELETE removes ONLY the scope row: a host's spider findings in
history are independent and persist.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.store import repository
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/scope")


def _require_project(state: AppState):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    return state.project


class ScopeAddRequest(BaseModel):
    host: str
    note: Optional[str] = None
    headers: Optional[str] = None  # raw request headers captured for this host


class ScopeUpdateRequest(BaseModel):
    headers: Optional[str] = None  # refresh the stored session ("update session")


def _entry(e) -> dict:
    return {"id": e.id, "host": e.host, "note": e.note, "headers": e.headers}


@router.get("")
def list_scope(state: AppState = Depends(require_token)):
    proj = _require_project(state)
    return [_entry(e) for e in repository.get_scope(proj.read_conn)]


@router.post("")
def add_scope(req: ScopeAddRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    host = req.host.strip().lower()
    if not host:
        raise HTTPException(status_code=400, detail="host is required")
    proj.writer.submit(lambda c: repository.add_scope_host(c, host, req.note, req.headers))
    return [_entry(e) for e in repository.get_scope(proj.read_conn)]


@router.put("/{host}")
def update_scope(host: str, req: ScopeUpdateRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    n = proj.writer.submit(lambda c: repository.update_scope_headers(c, host.lower(), req.headers))
    if n == 0:
        raise HTTPException(status_code=404, detail="host not in scope")
    return [_entry(e) for e in repository.get_scope(proj.read_conn)]


@router.delete("/{host}")
def delete_scope(host: str, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    # Removes ONLY the scope row; spider findings for this host persist in history.
    proj.writer.submit(lambda c: repository.remove_scope_host(c, host.lower()))
    return {"deleted": True}
