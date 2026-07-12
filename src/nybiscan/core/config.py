"""TOML configuration: global app settings and per-project project.toml.

Global settings live OUTSIDE any project, in the macOS Application Support dir.
Per-project config lives in the bundle. tomllib (stdlib) reads; tomli_w writes.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Dict

import tomli_w

APP_DIR_NAME = "NybiScan"

DEFAULT_GLOBAL_CONFIG: Dict[str, Any] = {
    "default_listen_ip": "127.0.0.1",
    "default_listen_port": 8080,  # proxy default (Plan 2); control API self-assigns
    "last_opened_project": "",
    "authorized_use_ack": False,  # first-launch acknowledgment (UI prompt is Plan 3)
    "auto_start_proxy": True,  # start the proxy automatically on project open
    "ui": {},
}


def app_support_dir() -> Path:
    """The global app-support directory (created on demand).

    Defaults to ~/Library/Application Support/NybiScan. Overridable via the
    NYBISCAN_SUPPORT_DIR env var so tests stay hermetic and never clobber the
    user's real config.toml or runtime.json.
    """
    override = os.environ.get("NYBISCAN_SUPPORT_DIR")
    d = Path(override) if override else Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def global_config_path() -> Path:
    return app_support_dir() / "config.toml"


def load_global_config() -> Dict[str, Any]:
    path = global_config_path()
    if not path.exists():
        return dict(DEFAULT_GLOBAL_CONFIG)
    with path.open("rb") as f:
        data = tomllib.load(f)
    merged = dict(DEFAULT_GLOBAL_CONFIG)
    merged.update(data)
    return merged


def save_global_config(config: Dict[str, Any]) -> None:
    with global_config_path().open("wb") as f:
        tomli_w.dump(config, f)


def set_authorized_use_ack(value: bool = True) -> Dict[str, Any]:
    """Persist the authorized-use acknowledgment to disk and return the config."""
    config = load_global_config()
    config["authorized_use_ack"] = value
    save_global_config(config)
    return config


# ----- project.toml ---------------------------------------------------------


def read_project_toml(bundle: Path) -> Dict[str, Any]:
    with (bundle / "project.toml").open("rb") as f:
        return tomllib.load(f)


def write_project_toml(bundle: Path, data: Dict[str, Any]) -> None:
    with (bundle / "project.toml").open("wb") as f:
        tomli_w.dump(data, f)
