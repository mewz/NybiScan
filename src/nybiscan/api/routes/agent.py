"""Agent-fetch route (authed).

The one new capability for the MCP server: fetch a URL directly (scope-gated) and
record it into history tagged source='agent', analyzable like browser/spider traffic.
Everything else the MCP does wraps existing endpoints.
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import fetch as core_fetch
from ...core import scope as scope_mod
from ...core.spider import rules
from ...core.store import repository
from ..auth import require_token
from ..state import AppState
from .history import _full

router = APIRouter(prefix="/agent")


def _require_project(state: AppState):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    return state.project


class AgentFetchRequest(BaseModel):
    url: str
    headers: Optional[Dict[str, str]] = None


@router.post("/fetch")
def agent_fetch(req: AgentFetchRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    scheme, host, port, path = rules.split_target(req.url)
    if not host:
        raise HTTPException(status_code=400, detail="invalid url (no host)")
    # Scope-gated like the spider: the agent may only fetch in-scope hosts.
    scope_hosts = {e.host for e in repository.get_scope(proj.read_conn)}
    if not scope_mod.host_in_scope(scope_hosts, host):
        raise HTTPException(
            status_code=400,
            detail=f"host {host!r} not in scope - add it to scope in NybiScan, then retry",
        )
    entry_id = core_fetch.agent_fetch(proj, req.url, req.headers)
    rec = repository.get_entry(proj.read_conn, entry_id, ctx=proj.ctx)
    return _full(rec)
