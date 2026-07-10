"""OS-agnostic NybiScan core.

This package MUST NOT import GUI or API frameworks (no fastapi, uvicorn, swift).
It exposes proxy-agnostic persistence, project lifecycle, crypto, and schemas so
that any UI or the control API can be a thin client over it.
"""
