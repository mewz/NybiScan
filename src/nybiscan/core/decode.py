"""Shared response-body decompression (gzip / deflate / br).

Used by the Bench send engine to decode a response body for storage/display,
mirroring what mitmproxy does for captured responses. Best-effort: on any decode
failure the original bytes are returned unchanged.
"""

from __future__ import annotations

import gzip
import zlib
from typing import Optional


def decompress(data: Optional[bytes], content_encoding: Optional[str]) -> Optional[bytes]:
    if not data or not content_encoding:
        return data
    enc = content_encoding.split(",")[0].strip().lower()
    try:
        if enc == "gzip":
            return gzip.decompress(data)
        if enc == "deflate":
            try:
                return zlib.decompress(data)
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS)
        if enc == "br":
            import brotli

            return brotli.decompress(data)
    except Exception:
        return data
    return data
