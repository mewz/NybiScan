"""Body shaping for the agent.

The control API returns bodies base64-encoded (already decompressed at capture/fetch
time; content-encoding is informational). For the agent we decode to TEXT so it sees
actual source (JSON/HTML/JS), not base64.

Large bodies are handled so source is NEVER hidden: the default returns a capped preview
WITH a marker AND the total size, but the FULL body or any character RANGE (offset/length,
or full=True) is retrievable - a multi-MB minified bundle can always be read, in pieces if
needed. Binary/undecodable and capture-dropped bodies return a clear marker, not garbage.
"""

from __future__ import annotations

import base64
from typing import Optional

DEFAULT_CAP = 262144  # 256 KB preview by default


def decode_body(
    b64: Optional[str],
    *,
    dropped: bool = False,
    content_encoding: Optional[str] = None,
    mime: Optional[str] = None,
    cap: int = DEFAULT_CAP,
    offset: int = 0,
    length: Optional[int] = None,
    full: bool = False,
) -> dict:
    """Return {text, total_chars, truncated, note}. total_chars is the full decoded
    length so the agent knows how much more exists; text is the requested window."""
    if dropped:
        return _marker("[body dropped by capture filter; metadata retained]")
    if b64 is None:
        return _marker("[no body]")
    try:
        data = base64.b64decode(b64)
    except Exception:
        return _marker("[body could not be decoded]")

    try:
        text_full = data.decode("utf-8")
    except UnicodeDecodeError:
        return _marker(f"[binary body, {len(data)} bytes, not shown]")

    total = len(text_full)
    start = max(0, offset)
    if full:
        window = text_full[start:]
    elif length is not None:
        window = text_full[start:start + max(0, length)]
    else:
        window = text_full[start:start + cap]

    shown_end = start + len(window)
    truncated = shown_end < total
    note = None
    if truncated:
        note = (
            f"[showing chars {start}-{shown_end} of {total}; "
            "pass full=true or offset/length for more]"
        )
    if content_encoding:
        # The stored body is already decompressed; encoding is informational only.
        enc = f"[original content-encoding: {content_encoding}]"
        note = f"{enc} {note}" if note else enc
    return {"text": window, "total_chars": total, "truncated": truncated, "note": note}


def _marker(text: str) -> dict:
    return {"text": text, "total_chars": 0, "truncated": False, "note": None}
