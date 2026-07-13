"""Pydantic v2 schemas for NybiScan core.

Every captured exchange is a HistoryRecord. Bodies may be pending (not yet
captured), stored inline, spilled to a file by hash (unencrypted projects only),
or dropped by the capture filter (metadata kept, body omitted).
"""

from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


class CaptureStatus(str, enum.Enum):
    pending = "pending"
    complete = "complete"
    error = "error"


class KdfParams(BaseModel):
    """Argon2id parameters persisted (non-secret) in project.toml.

    The salt is public by design. The passphrase and derived key are never
    persisted. On open, the key is re-derived from these stored params so the
    result is deterministic even if code defaults change later.
    """

    kdf: str = "argon2id"
    argon2_version: int = 19
    m_cost: int = 65536  # KiB
    t_cost: int = 3
    parallelism: int = 4
    salt: str  # hex

    @property
    def salt_bytes(self) -> bytes:
        return bytes.fromhex(self.salt)


class HistoryRecord(BaseModel):
    """One HTTP(S) exchange: request plus optional (possibly pending) response."""

    id: Optional[int] = None

    # flow_id correlates the INSERT (on request) with the UPDATE (on response),
    # so pending -> complete/error is a two-step write on one row. Set by the
    # proxy addon to mitmproxy's flow id; None for records inserted directly.
    flow_id: Optional[str] = None

    # host = scheme + host + port, split into fields for querying
    scheme: str = "http"
    host: str
    port: int = 80
    method: str = "GET"
    url: str = "/"  # path + query
    extension: Optional[str] = None  # file extension parsed from the URL path

    # request
    req_headers_raw: str = ""
    req_mime_type: Optional[str] = None
    req_body: Optional[bytes] = None
    req_body_ref: Optional[str] = None  # sha256 of spilled body, if spilled
    req_body_dropped: bool = False  # filter dropped a binary/image body
    req_length: int = 0
    req_content_encoding: Optional[str] = None  # original wire encoding (gzip, br)
    req_start_ts: int = 0  # UTC epoch millis

    # response
    status: Optional[int] = None
    resp_length: int = 0
    mime_type: Optional[str] = None
    remote_ip: Optional[str] = None
    resp_headers_raw: str = ""
    resp_body: Optional[bytes] = None
    resp_body_ref: Optional[str] = None
    resp_body_dropped: bool = False
    resp_content_encoding: Optional[str] = None  # original wire encoding (gzip, br)
    resp_complete_ts: Optional[int] = None  # UTC epoch millis

    capture_status: CaptureStatus = CaptureStatus.pending

    # provenance: browser (proxy capture) or spider (active crawl). spider_run_id
    # ties a spider row to the run that produced it (None for browser rows).
    source: str = "browser"
    spider_run_id: Optional[str] = None

    @property
    def host_display(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def path(self) -> str:
        return self.url.split("?", 1)[0]


class SiteEntry(BaseModel):
    """One observed host+path in the site map (tree building is a later plan)."""

    id: Optional[int] = None
    host: str
    path: str
    first_seen_ts: int = 0
    hits: int = 0


class ScopeEntry(BaseModel):
    """An in-scope host for this project. The spider crawls only in-scope hosts.

    headers holds the session (raw request headers, incl. Cookie) captured when the
    host was added to scope, so the spider crawls that host authenticated as the
    request that seeded it. Sensitive: lives in the bundle DB (encrypted for
    encrypted projects). None means the host is crawled unauthenticated.
    """

    id: Optional[int] = None
    host: str
    note: Optional[str] = None
    headers: Optional[str] = None


class ProjectMeta(BaseModel):
    name: str
    uuid: str
    created_ts: int
    schema_version: int = 1
    encrypted: bool = False
    record_count: int = 0
