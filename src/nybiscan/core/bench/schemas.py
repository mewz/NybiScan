"""Pydantic models for Bench tabs and per-send history."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class BenchTab(BaseModel):
    id: Optional[int] = None
    name: str = "Bench"
    order_index: int = 0
    # The raw request text is the source of truth for the wire bytes (request line
    # + headers + body as literal text). NO structured method/header fields.
    raw_request: str = ""
    conn_host: str = ""
    conn_port: int = 443
    conn_tls: bool = True
    content_length_autofill: bool = True
    created_ts: int = 0
    updated_ts: int = 0


class BenchSend(BaseModel):
    id: Optional[int] = None
    tab_id: int
    # request snapshot as sent
    req_raw: str = ""
    conn_host: str = ""
    conn_port: int = 443
    conn_tls: bool = True
    content_length_autofill: bool = True
    # response snapshot
    status: Optional[int] = None
    resp_headers_raw: str = ""
    resp_body: Optional[bytes] = None
    resp_length: int = 0
    mime_type: Optional[str] = None
    resp_content_encoding: Optional[str] = None
    error: Optional[str] = None  # genuine connection/handshake/timeout failure
    sent_ts: int = 0
    duration_ms: int = 0
