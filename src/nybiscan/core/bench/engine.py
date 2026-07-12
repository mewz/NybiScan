"""Verbatim low-level HTTP/1.1 send engine for Bench.

Writes the raw request bytes to a plain or TLS socket EXACTLY as composed - no
normalization, no injected headers, the connection target is the caller's
host:port (never derived from the Host: header). The only optional change is
Content-Length auto-fill (a toggle that touches ONLY Content-Length).

TLS does not verify certificates (connects to any host regardless of cert
validity, like the proxy's upstream). A completed handshake with a bad cert is
NOT an error; a handshake/connection that cannot complete IS a real failure and
is returned in `error`. HTTP/2 send is out of scope (h2 is binary/HPACK).
"""

from __future__ import annotations

import socket
import ssl
import time
from http.client import HTTPResponse
from typing import Optional

from ..decode import decompress

_SEP = b"\r\n\r\n"


def apply_content_length(raw: bytes, autofill: bool) -> bytes:
    """When autofill is on, set Content-Length to match the body and touch NOTHING
    else. When off, return the bytes verbatim. Only acts when a header/body
    separator exists."""
    if not autofill:
        return raw
    idx = raw.find(_SEP)
    if idx == -1:
        return raw
    head, body = raw[:idx], raw[idx + len(_SEP) :]
    lines = head.split(b"\r\n")
    request_line, headers = lines[0], lines[1:]
    out, found = [], False
    for h in headers:
        if h.split(b":", 1)[0].strip().lower() == b"content-length":
            out.append(b"Content-Length: " + str(len(body)).encode())
            found = True
        else:
            out.append(h)
    if not found and body:
        out.append(b"Content-Length: " + str(len(body)).encode())
    return b"\r\n".join([request_line] + out) + _SEP + body


def _method_of(raw: bytes) -> str:
    try:
        return raw.split(b" ", 1)[0].decode("latin-1", "replace")
    except Exception:
        return ""


def _mime_of(headers) -> Optional[str]:
    for k, v in headers:
        if k.lower() == "content-type":
            return v.split(";", 1)[0].strip().lower()
    return None


def _content_encoding_of(headers) -> Optional[str]:
    for k, v in headers:
        if k.lower() == "content-encoding":
            return v.strip().lower()
    return None


def send_raw(
    host: str,
    port: int,
    use_tls: bool,
    raw_request: bytes,
    content_length_autofill: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Send raw bytes to host:port and read the HTTP/1.1 response. Returns a dict of
    response-snapshot fields; on a genuine connection/handshake failure returns the
    same shape with status=None and error set."""
    payload = apply_content_length(raw_request, content_length_autofill)
    method = _method_of(payload)
    start = time.time()
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        if use_tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # do not verify, like the proxy upstream
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except NotImplementedError:
                pass
            sock = ctx.wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)
        sock.sendall(payload)

        resp = HTTPResponse(sock, method=method)
        resp.begin()
        headers = resp.getheaders()  # ordered, duplicates preserved
        raw_body = resp.read()
        status = resp.status
        version = f"HTTP/{resp.version // 10}.{resp.version % 10}"
        reason = resp.reason or ""
        resp.close()

        head_line = f"{version} {status} {reason}".rstrip()
        resp_headers_raw = (
            head_line + "\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers) + "\r\n"
        )
        encoding = _content_encoding_of(headers)
        # Store the DECODED body + the original wire encoding, like capture.
        body = decompress(raw_body, encoding)
        return {
            "status": status,
            "resp_headers_raw": resp_headers_raw,
            "resp_body": body,
            "resp_length": len(body) if body is not None else 0,
            "mime_type": _mime_of(headers),
            "resp_content_encoding": encoding,
            "error": None,
            "duration_ms": int((time.time() - start) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - a real connection/handshake failure
        return {
            "status": None,
            "resp_headers_raw": "",
            "resp_body": None,
            "resp_length": 0,
            "mime_type": None,
            "resp_content_encoding": None,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": int((time.time() - start) * 1000),
        }
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
