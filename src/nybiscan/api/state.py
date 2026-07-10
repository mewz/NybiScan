"""Shared application state for the control API.

Kept in its own module (not app.py) so route modules can import AppState without
the circular import that app.py <-> routes would create. This is the proper fix
for the Plan 1 shortcut where AppState type hints were dropped.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Set

from ..core.project import Project
from ..core.proxy.engine import ProxyEngine


class WsHub:
    """Fan-out of history events to connected WebSocket clients.

    deliver() runs in the asyncio loop thread (scheduled via call_soon_threadsafe
    from the core EventHub subscriber), so put_nowait on each client queue is safe.
    """

    def __init__(self) -> None:
        self._clients: Set["asyncio.Queue"] = set()

    def register(self) -> "asyncio.Queue":
        q: "asyncio.Queue" = asyncio.Queue(maxsize=1000)
        self._clients.add(q)
        return q

    def unregister(self, q: "asyncio.Queue") -> None:
        self._clients.discard(q)

    def deliver(self, event: dict) -> None:
        for q in list(self._clients):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class AppState:
    def __init__(self, token: str) -> None:
        self.token = token
        self.project: Optional[Project] = None
        self.proxy: Optional[ProxyEngine] = None
        self.ws_hub = WsHub()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._event_unsub = None

    def _bridge(self, event: dict) -> None:
        """Core EventHub subscriber (runs in the writer thread). Hand off to loop."""
        loop = self.loop
        if loop is not None:
            loop.call_soon_threadsafe(self.ws_hub.deliver, event)

    def attach_project(self, project: Project) -> None:
        self.close_project()
        self.project = project
        self._event_unsub = project.events.subscribe(self._bridge)

    def close_project(self) -> None:
        # Stop the proxy first (it writes into the project), then unsubscribe,
        # then close the project (drains writer + checkpoints WAL).
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy = None
        if self._event_unsub is not None:
            self._event_unsub()
            self._event_unsub = None
        if self.project is not None:
            self.project.close()
            self.project = None

    def stop_proxy(self) -> None:
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy = None
