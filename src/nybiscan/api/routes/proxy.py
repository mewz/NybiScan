"""Proxy lifecycle routes (all authenticated).

The proxy is an in-process component of this control-API process. Starting it
requires an open project (nowhere to write otherwise). ssl_insecure is honored
only under the NYBISCAN_ALLOW_INSECURE env guard (enforced in the engine) and its
effective value is surfaced in /proxy/status.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_token
from ..proxy_control import start_proxy, stop_proxy
from ..state import AppState

router = APIRouter(prefix="/proxy")


class ProxyStartRequest(BaseModel):
    ip: Optional[str] = None
    port: Optional[int] = None
    ssl_insecure: bool = False


@router.post("/start")
def proxy_start(req: ProxyStartRequest, state: AppState = Depends(require_token)):
    if state.project is None:
        raise HTTPException(status_code=409, detail="no project open")
    if state.proxy is not None and state.proxy.running:
        raise HTTPException(status_code=409, detail="proxy already running")
    try:
        return start_proxy(state, ip=req.ip, port=req.port, ssl_insecure=req.ssl_insecure)
    except Exception as exc:  # noqa: BLE001 - surface bind/startup failures
        raise HTTPException(status_code=500, detail=f"proxy failed to start: {exc}") from exc


@router.post("/stop")
def proxy_stop(state: AppState = Depends(require_token)):
    return stop_proxy(state)


@router.get("/status")
def proxy_status(state: AppState = Depends(require_token)):
    if state.proxy is None:
        return {"running": False}
    return state.proxy.status()
