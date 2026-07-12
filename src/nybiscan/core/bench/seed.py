"""Seed a Bench tab from a captured history entry ("send to Bench").

Reconstructs an HTTP/1.1 raw request from a capture. An h1.1 capture already has a
valid request line + Host header and is used essentially as-is. An h2 capture has
version HTTP/2.0 and carries the authority as a pseudo-header (no Host: header), so
we normalize the request-line version to HTTP/1.1 and inject a Host: header from
the captured host[:port]. Nothing else is changed; once seeded, edits + send stay
byte-verbatim.
"""

from __future__ import annotations

from typing import Optional, Tuple

from ..schemas import HistoryRecord


def _has_host(header_lines) -> bool:
    return any(line.split(":", 1)[0].strip().lower() == "host" for line in header_lines)


def raw_request_from_history(rec: HistoryRecord) -> Tuple[str, str, int, bool, Optional[str]]:
    """Returns (raw_request, conn_host, conn_port, conn_tls, dropped_note)."""
    blob = (rec.req_headers_raw or "").rstrip("\r\n")
    lines = blob.split("\r\n") if blob else []
    if not lines:
        lines = [f"{rec.method} {rec.url} HTTP/1.1"]

    # Normalize the request-line version to HTTP/1.1 (h2 stored HTTP/2.0).
    parts = lines[0].split(" ")
    if len(parts) >= 3:
        parts[2] = "HTTP/1.1"
        lines[0] = " ".join(parts)
    else:
        lines[0] = f"{rec.method} {rec.url} HTTP/1.1"

    # Ensure a Host header (h2 captures have none).
    if not _has_host(lines[1:]):
        default_port = (rec.scheme == "https" and rec.port == 443) or (
            rec.scheme != "https" and rec.port == 80
        )
        host_val = rec.host if default_port else f"{rec.host}:{rec.port}"
        lines.insert(1, f"Host: {host_val}")

    head = "\r\n".join(lines)

    dropped_note: Optional[str] = None
    if rec.req_body_dropped:
        body_text = ""
        dropped_note = (
            "The captured request body was dropped by the capture filter (binary/"
            "image) and cannot be replayed; the body is empty."
        )
    elif rec.req_body:
        body_text = rec.req_body.decode("utf-8", errors="replace")
    else:
        body_text = ""

    raw = head + "\r\n\r\n" + body_text
    return raw, rec.host, rec.port, rec.scheme == "https", dropped_note
