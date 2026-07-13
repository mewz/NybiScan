"""FastAPI app factory and application lifespan."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Callable, Optional

from fastapi import FastAPI

from .. import __version__
from .routes import (
    bench,
    ca,
    config,
    history,
    health,
    projects,
    proxy,
    scope,
    sitemap,
    spider,
    ws,
)
from .state import AppState


def create_app(state: AppState, on_startup: Optional[Callable[[AppState], None]] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Capture the running loop so the core EventHub (writer thread) can hand
        # events to WebSocket clients via call_soon_threadsafe.
        state.loop = asyncio.get_running_loop()
        if on_startup is not None:
            on_startup(state)  # e.g. CLI `proxy start`: open project + start proxy
        try:
            yield
        finally:
            state.close_project()  # drains writer, checkpoints WAL, stops proxy

    app = FastAPI(title="NybiScan Control API", version=__version__, lifespan=lifespan)
    app.state.app_state = state
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(proxy.router)
    app.include_router(history.router)
    app.include_router(ws.router)
    app.include_router(config.router)
    app.include_router(ca.router)
    app.include_router(bench.router)
    app.include_router(scope.router)
    app.include_router(sitemap.router)
    app.include_router(spider.router)
    return app
