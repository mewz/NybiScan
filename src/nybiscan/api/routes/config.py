"""Global config routes (authed).

Thin wrappers over core/config.py. The GUI reads /config on launch to decide
whether to show the authorized-use gate and to prefill the proxy listen fields,
and POSTs /config/acknowledge when the user accepts. No config state lives in the
client; the core owns the flag.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...core import config as core_config
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/config")


def _public_config() -> dict:
    cfg = core_config.load_global_config()
    return {
        "authorized_use_ack": bool(cfg.get("authorized_use_ack", False)),
        "auto_start_proxy": bool(cfg.get("auto_start_proxy", True)),
        "default_listen_ip": cfg.get("default_listen_ip", "127.0.0.1"),
        "default_listen_port": int(cfg.get("default_listen_port", 8080)),
    }


class UpdateConfigRequest(BaseModel):
    auto_start_proxy: Optional[bool] = None


@router.get("")
def get_config(state: AppState = Depends(require_token)):
    return _public_config()


@router.post("")
def update_config(req: UpdateConfigRequest, state: AppState = Depends(require_token)):
    cfg = core_config.load_global_config()
    if req.auto_start_proxy is not None:
        cfg["auto_start_proxy"] = req.auto_start_proxy
    core_config.save_global_config(cfg)
    return _public_config()


@router.post("/acknowledge")
def acknowledge(state: AppState = Depends(require_token)):
    core_config.set_authorized_use_ack(True)
    return _public_config()
