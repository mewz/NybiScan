"""Site-map routes (all authed). A read-only query over captured history; no new
requests. Returns a host -> path tree (browser + spider rows, source-attributed)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import sitemap as sitemap_core
from ...core.store import repository
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/sitemap")


def _require_project(state: AppState):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    return state.project


class HideRequest(BaseModel):
    scheme: str
    host: str
    port: int
    path: Optional[str] = None  # None hides the whole host; a path hides it + descendants


@router.get("")
def get_sitemap(state: AppState = Depends(require_token)):
    proj = _require_project(state)
    return sitemap_core.build_sitemap(proj.read_conn)


@router.post("/hide")
def hide_node(req: HideRequest, state: AppState = Depends(require_token)):
    """Hide a host or path subtree from the map VIEW only. History rows are untouched."""
    proj = _require_project(state)
    key = sitemap_core.make_hidden_key(req.scheme, req.host, req.port, req.path)
    proj.writer.submit(lambda c: repository.add_hidden_map_key(c, key))
    return {"hidden": key}


@router.post("/unhide")
def unhide_node(req: HideRequest, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    key = sitemap_core.make_hidden_key(req.scheme, req.host, req.port, req.path)
    proj.writer.submit(lambda c: repository.remove_hidden_map_key(c, key))
    return {"unhidden": key}


@router.get("/{host}")
def get_host_map(host: str, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    host_map = sitemap_core.build_host_map(proj.read_conn, host)
    if host_map is None:
        raise HTTPException(status_code=404, detail="no history for host")
    return host_map
