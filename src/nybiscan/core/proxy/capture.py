"""Map a mitmproxy flow to NybiScan HistoryRecord fields.

Pure helpers (no db, no writer). mitmproxy auto-decompresses gzip/deflate/br, so
`request.content` / `response.content` are already decoded; we store the decoded
bytes and record the original wire encoding separately. Header blobs are built
from `headers.fields` to preserve order, casing, and duplicates exactly.
"""

from __future__ import annotations

from typing import Optional

from ..schemas import CaptureStatus, HistoryRecord


def _ms(ts: Optional[float]) -> int:
    return int(ts * 1000) if ts else 0


def _headers_blob(first_line: str, headers) -> str:
    lines = [first_line]
    for name, value in headers.fields:
        lines.append(f"{name.decode('latin-1')}: {value.decode('latin-1')}")
    return "\r\n".join(lines) + "\r\n\r\n"


def _mime(headers) -> Optional[str]:
    ct = headers.get("content-type")
    return ct.split(";", 1)[0].strip().lower() if ct else None


def _content_encoding(headers) -> Optional[str]:
    ce = headers.get("content-encoding")
    return ce.strip().lower() if ce else None


def _safe_content(message) -> Optional[bytes]:
    """Decoded body, or None if mitmproxy cannot decode it (e.g. streamed)."""
    try:
        return message.content
    except Exception:
        return None


def _remote_ip(flow) -> Optional[str]:
    # peername is legitimately absent on flows that errored before connecting.
    peer = getattr(flow.server_conn, "peername", None)
    if peer and len(peer) >= 1:
        return peer[0]
    return None


def record_from_request(flow) -> HistoryRecord:
    req = flow.request
    first_line = f"{req.method} {req.path} {req.http_version}"
    return HistoryRecord(
        flow_id=flow.id,
        scheme=req.scheme,
        host=req.pretty_host,
        port=req.port,
        method=req.method,
        url=req.path,
        req_headers_raw=_headers_blob(first_line, req.headers),
        req_mime_type=_mime(req.headers),
        req_body=_safe_content(req),
        req_content_encoding=_content_encoding(req.headers),
        req_start_ts=_ms(req.timestamp_start),
        capture_status=CaptureStatus.pending,
    )


def response_patch(flow) -> HistoryRecord:
    """A record carrying the completed response, keyed by flow_id for UPDATE."""
    req = flow.request
    resp = flow.response
    body = _safe_content(resp)
    first_line = f"{resp.http_version} {resp.status_code} {resp.reason}"
    return HistoryRecord(
        flow_id=flow.id,
        scheme=req.scheme,
        host=req.pretty_host,
        port=req.port,
        method=req.method,
        url=req.path,
        status=resp.status_code,
        resp_length=len(body) if body is not None else 0,
        mime_type=_mime(resp.headers),
        remote_ip=_remote_ip(flow),
        resp_headers_raw=_headers_blob(first_line, resp.headers),
        resp_body=body,
        resp_content_encoding=_content_encoding(resp.headers),
        resp_complete_ts=_ms(resp.timestamp_end),
        capture_status=CaptureStatus.complete,
    )
