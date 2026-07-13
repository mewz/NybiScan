"""Spider routes (all authed).

Starting a crawl requires an open project and a seed history entry, and REFUSES a
seed host that is not in scope (the authorized-use guard). The core owns the crawl
engine, per-host session handling, and scope/exclude enforcement.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import scope as scope_mod
from ...core.spider import rules
from ...core.spider.engine import SpiderConfig, SpiderEngine
from ...core.store import repository
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/spider")


def _require_project(state: AppState):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    return state.project


class ExcludeEntry(BaseModel):
    pattern: str
    is_regex: bool = False


class SpiderStartRequest(BaseModel):
    seed_history_id: int
    max_depth: int = 3
    exclude: Optional[List[ExcludeEntry]] = None
    rate_limit_ms: int = 500
    max_requests: int = 300
    include_binary: bool = False


def _saved(proj, run_id: Optional[str]) -> int:
    if not run_id:
        return 0
    return proj.read_conn.execute(
        "SELECT count(*) FROM history WHERE spider_run_id = ?", (run_id,)
    ).fetchone()[0]


def _status_payload(state: AppState, proj) -> dict:
    if state.spider is None:
        return {"running": False, "found": 0, "saved": 0, "cap": 0, "current": None, "run_id": None}
    snap = state.spider.snapshot()
    snap["saved"] = _saved(proj, snap.get("run_id"))
    return snap


@router.post("/start")
def spider_start(req: SpiderStartRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    if state.spider is not None and state.spider.running:
        raise HTTPException(status_code=409, detail="spider already running")

    seed = repository.get_entry(proj.read_conn, req.seed_history_id, ctx=proj.ctx)
    if seed is None:
        raise HTTPException(status_code=404, detail="no such history entry")

    scope_entries = repository.get_scope(proj.read_conn)
    scope_hosts = {e.host for e in scope_entries}
    if not scope_mod.host_in_scope(scope_hosts, seed.host):
        raise HTTPException(
            status_code=400,
            detail=f"seed host {seed.host!r} not in scope - add it first",
        )

    # Caller-provided excludes, else the safe defaults (logout/signout).
    if req.exclude is None:
        exclude = SpiderConfig(seed_history_id=0).exclude
    else:
        exclude = [e.model_dump() for e in req.exclude]
    try:
        rules.compile_excludes(exclude)  # validate regex before starting
    except rules.ExcludeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope_headers = {e.host: e.headers for e in scope_entries}
    config = SpiderConfig(
        seed_history_id=req.seed_history_id,
        max_depth=req.max_depth,
        exclude=exclude,
        rate_limit_ms=req.rate_limit_ms,
        max_requests=req.max_requests,
        include_binary=req.include_binary,
    )
    engine = SpiderEngine(proj, config, scope_hosts, scope_headers, seed)
    engine.start()
    state.spider = engine
    return _status_payload(state, proj)


@router.post("/stop")
def spider_stop(state: AppState = Depends(require_token)):
    _require_project(state)
    state.stop_spider()
    return {"running": False}


@router.get("/status")
def spider_status(state: AppState = Depends(require_token)):
    proj = _require_project(state)
    return _status_payload(state, proj)
