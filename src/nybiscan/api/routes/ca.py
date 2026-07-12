"""CA info route (authed, read-only).

Reports which CA WOULD apply for the open project (project override, else global)
without ever generating one. Display only; generate/import/export stay on the CLI
this plan.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import ca as core_ca
from ...core.errors import NybiScanError
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/ca")


@router.get("/info")
def ca_info(state: AppState = Depends(require_token)):
    bundle = state.project.bundle if state.project is not None else None
    confdir = core_ca.resolve_existing_confdir(bundle)
    if confdir is None:
        return {"scope": "none", "exists": False}

    scope = "project" if bundle is not None and confdir == (bundle / "ca") else "global"
    try:
        info = core_ca.ca_info(confdir)
    except NybiScanError:
        return {"scope": scope, "exists": False, "confdir": str(confdir)}

    return {
        "scope": scope,
        "exists": True,
        "confdir": info["confdir"],
        "cn": info["cn"],
        "fingerprint_sha256": info["fingerprint_sha256"],
        "not_after": info["not_after"],
    }


class ExportRequest(BaseModel):
    format: str = "pem"  # pem | der


@router.post("/export")
def ca_export(req: ExportRequest, state: AppState = Depends(require_token)):
    """Export the PUBLIC CA certificate (PEM or DER). Never the private key.

    Resolves the CA that applies to the open project (project override, else
    global) without generating one. Returns base64 cert bytes; the GUI writes the
    file via its own save dialog.
    """
    if req.format not in ("pem", "der"):
        raise HTTPException(status_code=400, detail="format must be pem or der")
    bundle = state.project.bundle if state.project is not None else None
    confdir = core_ca.resolve_existing_confdir(bundle)
    if confdir is None:
        raise HTTPException(status_code=404, detail="no CA to export")
    try:
        data = core_ca.public_cert_bytes(confdir, req.format)
    except NybiScanError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "format": req.format,
        "suggested_filename": f"nybiscan-ca.{'crt' if req.format == 'pem' else 'der'}",
        "cert_b64": base64.b64encode(data).decode("ascii"),
    }
