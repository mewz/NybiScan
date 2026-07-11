"""Launch the control API on 127.0.0.1 with a fresh per-session bearer token.

The control API binds a dedicated auto-picked free port (NOT 8080, which is
reserved for the Plan 2 proxy). The port and token are written to runtime.json
in the app-support dir with 0600 permissions for the GUI (or CLI health-check)
to read. A fresh token is generated per app session and never persisted beyond
that file.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
from typing import Tuple

from ..core.config import app_support_dir
from .app import create_app
from .state import AppState

RUNTIME_FILENAME = "runtime.json"


def runtime_path():
    return app_support_dir() / RUNTIME_FILENAME


def pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def write_runtime(port: int, token: str) -> None:
    path = runtime_path()
    payload = json.dumps({"port": port, "token": token, "pid": os.getpid()})
    # Create with 0600 from the start; do not widen it.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(payload)
    os.chmod(path, 0o600)


def read_runtime() -> Tuple[int, str]:
    with runtime_path().open("r") as f:
        data = json.load(f)
    return int(data["port"]), str(data["token"])


def serve(port: int | None = None, on_startup=None) -> None:
    """Run the control API on 127.0.0.1. on_startup runs inside the app lifespan
    (used by `proxy start` to open a project and start the proxy)."""
    import uvicorn

    token = secrets.token_urlsafe(32)
    port = port or pick_free_port()
    write_runtime(port, token)

    state = AppState(token)
    app = create_app(state, on_startup=on_startup)
    print(f"NybiScan control API listening on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
