"""Unauthenticated liveness probe.

/health is deliberately UNAUTHENTICATED so the GUI can confirm the core is up
before it has read the session token, and to avoid startup races. It MUST NOT
leak any project detail (name, path, record counts). Only three non-sensitive
fields are returned. All sensitive project detail lives on the authed
/projects/current route.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import __version__

router = APIRouter()


@router.get("/health")
def health(request: Request):
    state = request.app.state.app_state
    return {
        "status": "ok",
        "version": __version__,
        "project_open": state.project is not None,
    }
