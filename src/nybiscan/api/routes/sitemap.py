"""Site-map routes (all authed). A read-only query over captured history; no new
requests. Returns a host -> path tree (browser + spider rows, source-attributed)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...core import sitemap as sitemap_core
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/sitemap")


def _require_project(state: AppState):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    return state.project


@router.get("")
def get_sitemap(state: AppState = Depends(require_token)):
    proj = _require_project(state)
    return sitemap_core.build_sitemap(proj.read_conn)


@router.get("/{host}")
def get_host_map(host: str, state: AppState = Depends(require_token)):
    proj = _require_project(state)
    host_map = sitemap_core.build_host_map(proj.read_conn, host)
    if host_map is None:
        raise HTTPException(status_code=404, detail="no history for host")
    return host_map
