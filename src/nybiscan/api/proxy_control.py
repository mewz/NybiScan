"""Start/stop the in-process proxy for an open project.

Shared by the /proxy/start route and the CLI `proxy start` autostart path, so
both drive the identical lifecycle.
"""

from __future__ import annotations

from typing import Optional

from ..core import ca
from ..core.proxy.engine import ProxyEngine
from .state import AppState


class NoProjectOpenError(Exception):
    pass


def start_proxy(
    state: AppState,
    ip: Optional[str] = None,
    port: Optional[int] = None,
    ssl_insecure: bool = False,
) -> dict:
    proj = state.project
    if proj is None:
        raise NoProjectOpenError("no project open; open a project before starting the proxy")

    default_ip, default_port = proj.listen_settings()
    ip = ip or default_ip
    port = int(port or default_port)
    confdir = ca.resolve_confdir(proj.bundle)

    engine = ProxyEngine(proj, ip, port, confdir, ssl_insecure=ssl_insecure)
    engine.start()
    state.proxy = engine
    return engine.status()


def stop_proxy(state: AppState) -> dict:
    state.stop_proxy()
    return {"running": False}
