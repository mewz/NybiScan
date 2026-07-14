"""Agent fetch: a one-shot direct GET recorded into history tagged source='agent'.

The one genuinely new capability behind the MCP server (everything else wraps existing
endpoints). Reuses the spider/bench send path (raw HTTP/1.1 GET, TLS-no-verify like the
proxy upstream, decompress, text filter on store) and the single BatchWriter. Scope
enforcement is the route's job (mirrors the spider route); this helper just fetches and
records. Import-clean (core only, no fastapi).

TLS no-verify is a CONSCIOUS inheritance of the Bench/spider posture: authorized testing
connects where the operator is authorized (incl. staging / self-signed hosts); a
completed handshake with a bad cert is not an error, a genuine failure lands in the
recorded status/error.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from .bench import engine as bench_engine
from .proxy.capture import parse_extension
from .schemas import CaptureStatus, HistoryRecord
from .spider import rules
from .store import repository


def _ms() -> int:
    return int(time.time() * 1000)


def _headers_to_raw(headers: Optional[Dict[str, str]]) -> Optional[str]:
    if not headers:
        return None
    return "".join(f"{k}: {v}\r\n" for k, v in headers.items())


def agent_fetch(project, url: str, headers: Optional[Dict[str, str]] = None) -> int:
    """Fetch `url` with a direct GET (carrying optional headers), record it as an
    agent-sourced history entry, and return the new entry id. The caller (route) is
    responsible for the scope gate before calling this."""
    scheme, host, port, path = rules.split_target(url)
    raw = rules.build_get(path, host, _headers_to_raw(headers))
    started = _ms()
    resp = bench_engine.send_raw(host, port, scheme == "https", raw, content_length_autofill=False)
    errored = resp.get("error") is not None
    rec = HistoryRecord(
        scheme=scheme, host=host, port=port, method="GET", url=path,
        extension=parse_extension(path),
        req_headers_raw=raw.decode("latin-1", "replace"),
        req_start_ts=started,
        status=resp.get("status"),
        resp_length=resp.get("resp_length", 0),
        mime_type=resp.get("mime_type"),
        resp_headers_raw=resp.get("resp_headers_raw", ""),
        resp_body=resp.get("resp_body"),
        resp_content_encoding=resp.get("resp_content_encoding"),
        resp_complete_ts=_ms(),
        capture_status=CaptureStatus.error if errored else CaptureStatus.complete,
        source="agent",
    )
    # submit runs on the single writer thread and commits, returning the new id (no
    # competing db connection); the sites index is upserted in the same statement group.
    return project.writer.submit(
        lambda c: repository.insert_history_one(c, rec, project.ctx)
    )
