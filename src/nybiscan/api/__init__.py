"""Local control API: a thin FastAPI client over the core.

Localhost-only, bearer-token authenticated (except the unauthenticated /health
liveness probe). No business logic lives here; every route wraps the core.
"""
