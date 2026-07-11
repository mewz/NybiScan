"""Global config routes (authed).

Thin wrappers over core/config.py. The GUI reads /config on launch to decide
whether to show the authorized-use gate and to prefill the proxy listen fields,
and POSTs /config/acknowledge when the user accepts. No config state lives in the
client; the core owns the flag.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core import config as core_config
from ..auth import require_token
from ..state import AppState

router = APIRouter(prefix="/config")


def _public_config() -> dict:
    cfg = core_config.load_global_config()
    return {
        "authorized_use_ack": bool(cfg.get("authorized_use_ack", False)),
        "default_listen_ip": cfg.get("default_listen_ip", "127.0.0.1"),
        "default_listen_port": int(cfg.get("default_listen_port", 8080)),
    }


@router.get("")
def get_config(state: AppState = Depends(require_token)):
    return _public_config()


@router.post("/acknowledge")
def acknowledge(state: AppState = Depends(require_token)):
    core_config.set_authorized_use_ack(True)
    return _public_config()
