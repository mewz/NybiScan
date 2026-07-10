"""Body-capture filter and spill decision.

Default policy: store only text-like bodies (text/*, html, json, xml,
javascript, css). Binary and image bodies are dropped: their metadata (mime,
length) is retained but the body itself is not stored.

Spill: for UNENCRYPTED projects, a kept body larger than the threshold is
written to bodies/<sha256> and referenced by hash (natural dedup). ENCRYPTED
projects keep ALL bodies in the database regardless of size, so there is a
single encryption boundary and no plaintext ever leaves the db.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_SPILL_THRESHOLD = 512 * 1024  # 512 KiB

# Explicit non-text/* MIME types treated as storable text.
TEXTUAL_TYPES = frozenset(
    {
        "application/json",
        "application/ld+json",
        "application/xml",
        "application/xhtml+xml",
        "application/javascript",
        "application/x-javascript",
        "application/ecmascript",
        "application/rss+xml",
        "application/atom+xml",
        "application/x-www-form-urlencoded",
    }
)


@dataclass
class StorageContext:
    """Everything body handling needs to know about the target project."""

    is_encrypted: bool
    bodies_dir: Optional[Path]  # None for encrypted projects
    spill_threshold: int = DEFAULT_SPILL_THRESHOLD


def _normalize_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    return mime.split(";", 1)[0].strip().lower()


def should_store_body(mime: Optional[str]) -> bool:
    """True if a body of this content type should be captured (text-like)."""
    norm = _normalize_mime(mime)
    if norm is None:
        # Unknown content type: keep it (usually small/text; never binary blobs
        # of interest). Real binary responses carry an explicit content type.
        return True
    if norm.startswith("text/"):
        return True
    return norm in TEXTUAL_TYPES


def prepare_body(
    body: Optional[bytes], mime: Optional[str], ctx: StorageContext
) -> Tuple[Optional[bytes], Optional[str], bool, int]:
    """Decide how to persist a body.

    Returns (inline_blob, body_ref, dropped, length):
      - inline_blob: bytes to store in the db, or None
      - body_ref:    sha256 hex of a spilled file, or None
      - dropped:     True if the filter dropped a binary/image body
      - length:      byte length of the original body (always retained)
    """
    if body is None:
        return (None, None, False, 0)

    length = len(body)

    if not should_store_body(mime):
        # Drop the body, keep the metadata (mime + length live on the record).
        return (None, None, True, length)

    if ctx.is_encrypted or ctx.bodies_dir is None or length <= ctx.spill_threshold:
        return (body, None, False, length)

    # Spill (unencrypted, oversized): content-addressed file, dedup by hash.
    digest = hashlib.sha256(body).hexdigest()
    dest = ctx.bodies_dir / digest
    if not dest.exists():
        dest.write_bytes(body)
    return (None, digest, False, length)


def load_spilled_body(body_ref: str, ctx: StorageContext) -> Optional[bytes]:
    """Read a spilled body back from bodies/ by hash reference."""
    if ctx.bodies_dir is None:
        return None
    p = ctx.bodies_dir / body_ref
    return p.read_bytes() if p.exists() else None
