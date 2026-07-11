"""CA info route (authed, read-only).

Reports which CA WOULD apply for the open project (project override, else global)
without ever generating one. Display only; generate/import/export stay on the CLI
this plan.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

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
