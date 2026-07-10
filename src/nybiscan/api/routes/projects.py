"""Project lifecycle routes (all authenticated).

Sensitive project detail (name, path, encryption status, record count) is
returned ONLY here, never from /health.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import project as core_project
from ...core.errors import (
    NybiScanError,
    PassphraseRequiredError,
    ProjectExistsError,
    ProjectNotFoundError,
    WrongPassphraseError,
)
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/projects")


class CreateProjectRequest(BaseModel):
    path: str
    name: Optional[str] = None
    scope: List[str] = []
    passphrase: Optional[str] = None


class OpenProjectRequest(BaseModel):
    path: str
    passphrase: Optional[str] = None


def _current_payload(state: AppState) -> dict:
    if state.project is None:
        return {"project_open": False}
    meta = state.project.meta()
    return {
        "project_open": True,
        "path": str(state.project.bundle),
        "name": meta.name,
        "uuid": meta.uuid,
        "encrypted": meta.encrypted,
        "record_count": meta.record_count,
        "proxy_running": state.proxy is not None and state.proxy.running,
    }


@router.post("")
def create_project(req: CreateProjectRequest, state: AppState = Depends(require_token)):
    try:
        project = core_project.create_project(
            req.path, name=req.name, scope=req.scope, passphrase=req.passphrase
        )
    except ProjectExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NybiScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state.attach_project(project)
    return _current_payload(state)


@router.post("/open")
def open_project(req: OpenProjectRequest, state: AppState = Depends(require_token)):
    try:
        project = core_project.open_project(req.path, passphrase=req.passphrase)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PassphraseRequiredError, WrongPassphraseError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except NybiScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state.attach_project(project)
    return _current_payload(state)


@router.post("/close")
def close_project(state: AppState = Depends(require_token)):
    state.close_project()
    return {"project_open": False}


@router.get("/current")
def current_project(state: AppState = Depends(require_token)):
    return _current_payload(state)
