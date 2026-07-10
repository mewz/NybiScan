"""FastAPI app factory and shared application state."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from .. import __version__
from ..core.project import Project
from .routes import health, projects


class AppState:
    """Holds the session bearer token and the currently open project (if any)."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.project: Optional[Project] = None

    def close_project(self) -> None:
        if self.project is not None:
            self.project.close()
            self.project = None


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="NybiScan Control API", version=__version__)
    app.state.app_state = state
    app.include_router(health.router)
    app.include_router(projects.router)
    return app
