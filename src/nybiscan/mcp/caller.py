"""Control-API caller abstraction.

The MCP tools call the control API through a small `Caller` seam. `HttpCaller` (the
production impl) reads runtime.json for {port, token} and calls localhost over stdlib
urllib (no new HTTP dependency, same pattern as the CLI). Tests inject a TestClient-backed
caller so tool logic is hermetic (no live server, no MCP SDK).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


class CoreNotRunning(RuntimeError):
    """runtime.json is absent / unreadable: the NybiScan core is not running."""


@dataclass
class Result:
    status: int
    body: Any            # parsed JSON (dict/list) or None
    headers: Dict[str, str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def detail(self) -> str:
        """The API's error detail, if the body is an error envelope."""
        if isinstance(self.body, dict) and "detail" in self.body:
            return str(self.body["detail"])
        return f"HTTP {self.status}"


class Caller(Protocol):
    def request(
        self, method: str, path: str,
        json_body: Optional[dict] = None, params: Optional[dict] = None,
    ) -> Result: ...


class HttpCaller:
    """Calls the running control API using the runtime.json bearer token."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        if base_url is None or token is None:
            base_url, token = self._from_runtime()
        self._base = base_url.rstrip("/")
        self._token = token

    @staticmethod
    def _from_runtime():
        try:
            from ..api.server import read_runtime
            port, token = read_runtime()
        except FileNotFoundError as exc:
            raise CoreNotRunning(
                "NybiScan is not running. Start it first (open a project in the app, "
                "or run `nybiscan serve`), then retry."
            ) from exc
        return f"http://127.0.0.1:{port}", token

    def request(self, method, path, json_body=None, params=None) -> Result:
        url = self._base + path
        if params:
            from urllib.parse import urlencode
            query = urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"
        data = json.dumps(json_body).encode() if json_body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return Result(r.status, _parse(raw), dict(r.headers))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return Result(exc.code, _parse(raw), dict(exc.headers or {}))
        except urllib.error.URLError as exc:
            raise CoreNotRunning(
                f"Could not reach the NybiScan control API ({exc.reason}). Is it running?"
            ) from exc


def _parse(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode("utf-8", "replace")
