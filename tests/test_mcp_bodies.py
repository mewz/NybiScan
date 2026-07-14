"""MCP body shaping: decode to text, markers, and never-hide-source range retrieval."""

from __future__ import annotations

import base64

from nybiscan.mcp import bodies


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_decodes_text_body():
    out = bodies.decode_body(_b64(b'{"ok":true}'), mime="application/json")
    assert out["text"] == '{"ok":true}'
    assert out["truncated"] is False and out["total_chars"] == 11


def test_dropped_and_binary_markers():
    assert "dropped by capture filter" in bodies.decode_body(None, dropped=True)["text"]
    assert bodies.decode_body(None)["text"] == "[no body]"
    binary = bodies.decode_body(_b64(b"\x89PNG\r\n\x1a\n\xff\xfe"), mime="image/png")
    assert "binary body" in binary["text"] and "not shown" in binary["text"]


def test_large_body_preview_then_full_and_range():
    big = ("x" * 300_000)
    b64 = _b64(big.encode())
    # Default: capped preview + total size + a marker; NOT the whole thing.
    preview = bodies.decode_body(b64, cap=262144)
    assert preview["truncated"] is True
    assert preview["total_chars"] == 300_000
    assert len(preview["text"]) == 262144
    assert "of 300000" in preview["note"]
    # Full retrieval: the entire body, nothing hidden.
    full = bodies.decode_body(b64, full=True)
    assert full["text"] == big and full["truncated"] is False
    # Byte/char range retrieval: a window in the middle.
    window = bodies.decode_body(b64, offset=100_000, length=50_000)
    assert window["text"] == big[100_000:150_000]
    assert window["truncated"] is True  # more remains after the window
