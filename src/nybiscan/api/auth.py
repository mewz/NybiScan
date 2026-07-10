"""Bearer-token auth dependency for the control API."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request


def require_token(request: Request):
    """Validate the Authorization: Bearer <token> header against the session token."""
    state = request.app.state.app_state
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header[len("Bearer ") :]
    if not secrets.compare_digest(token, state.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return state
