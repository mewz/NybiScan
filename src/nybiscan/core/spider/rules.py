"""Pure spider helpers: exclude matching, link extraction, binary skip, session
header handling, and the seed-subtree boundary. No threads, no db, no network, so
they are unit-tested directly and shared by the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..proxy.capture import parse_extension

# Extensions treated as binary (skipped unless include_binary). CSS/JS/SVG are text
# and part of the testable surface, so they are NOT here. Over-inclusion here only
# means "not crawled by default", never data loss.
BINARY_EXTENSIONS: Set[str] = {
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tif", "tiff",
    "woff", "woff2", "ttf", "otf", "eot",
    "zip", "gz", "tgz", "bz2", "xz", "7z", "rar", "tar",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "mp3", "mp4", "avi", "mov", "wmv", "flv", "webm", "ogg", "wav",
    "exe", "dmg", "pkg", "deb", "rpm", "msi", "bin", "dll", "so",
    "wasm", "class", "jar",
}

# Headers dropped when composing a spider GET: the request line is rebuilt, Host is
# set per target, and body headers do not apply to a bodyless GET.
_DROP_HEADERS = {"host", "content-length", "content-type", "connection", "proxy-connection"}


@dataclass
class ExcludeRule:
    pattern: str
    is_regex: bool
    _rx: Optional["re.Pattern"] = None


class ExcludeError(ValueError):
    """A malformed regex exclude, rejected at add-time / start (never mid-crawl)."""


def compile_excludes(entries) -> List[ExcludeRule]:
    """Validate + compile exclude entries. Raises ExcludeError on a bad regex so a
    malformed pattern is rejected before a crawl, never silently mid-crawl.

    Each entry is a dict/object with `pattern` and `is_regex`.
    """
    rules: List[ExcludeRule] = []
    for e in entries or []:
        pattern = e["pattern"] if isinstance(e, dict) else e.pattern
        is_regex = bool(e["is_regex"] if isinstance(e, dict) else e.is_regex)
        if not pattern:
            continue
        rx = None
        if is_regex:
            try:
                rx = re.compile(pattern)
            except re.error as exc:
                raise ExcludeError(f"invalid regex exclude {pattern!r}: {exc}") from exc
        rules.append(ExcludeRule(pattern=pattern, is_regex=is_regex, _rx=rx))
    return rules


def is_excluded(path: str, rules: List[ExcludeRule]) -> bool:
    """True if the path (query already stripped by the caller is fine; we strip too)
    matches any exclude rule. String rules match as an exact path, a path prefix
    (dir), OR any path segment (over-exclude erring safe: `/logout` catches
    `/logout`, `/logout?x=1`, and `/auth/logout`). Regex rules match the path."""
    p = path.split("?", 1)[0]
    for rule in rules:
        if rule.is_regex:
            if rule._rx and rule._rx.search(p):
                return True
            continue
        pat = rule.pattern
        if p == pat or p.startswith(pat.rstrip("/") + "/"):
            return True
        seg = pat.strip("/")
        if seg and seg in [s for s in p.split("/") if s]:
            return True
    return False


def skip_binary(url: str, include_binary: bool) -> bool:
    """True if this URL should NOT be fetched because it looks binary (by extension)
    and binary inclusion is off."""
    if include_binary:
        return False
    ext = parse_extension(url)
    return ext in BINARY_EXTENSIONS


def extract_links(base_url: str, html: bytes) -> Set[str]:
    """Absolute http(s) URLs from href/src/form-action in the HTML, resolved against
    base_url. Deterministic DOM attribute extraction (no JS execution)."""
    try:
        text = html.decode("utf-8", "replace")
    except Exception:
        return set()
    soup = BeautifulSoup(text, "html.parser")
    found: Set[str] = set()
    attrs = (("a", "href"), ("link", "href"), ("area", "href"),
             ("script", "src"), ("img", "src"), ("iframe", "src"),
             ("source", "src"), ("form", "action"))
    for tag, attr in attrs:
        for el in soup.find_all(tag):
            val = el.get(attr)
            if not val:
                continue
            abs_url = urljoin(base_url, val.strip())
            scheme = urlsplit(abs_url).scheme
            if scheme in ("http", "https"):
                found.add(abs_url.split("#", 1)[0])  # drop fragment
    return found


def session_header_lines(raw: Optional[str]) -> List[str]:
    """Header lines from a stored raw request blob, minus the request line and the
    per-request/body headers we rebuild. Preserves order, casing, and duplicates."""
    if not raw:
        return []
    lines = raw.replace("\r\n", "\n").split("\n")
    # Drop a leading request line ("GET /x HTTP/1.1") if present.
    if lines and ":" not in lines[0].split(" ", 1)[0]:
        lines = lines[1:]
    out: List[str] = []
    for line in lines:
        if not line.strip():
            continue
        name = line.split(":", 1)[0].strip().lower()
        if name in _DROP_HEADERS:
            continue
        out.append(line.rstrip("\r"))
    return out


def build_get(path: str, host: str, raw_session: Optional[str]) -> bytes:
    """Compose a raw HTTP/1.1 GET for `path` on `host`, carrying that host's stored
    session headers. Host is always the TARGET host (never derived from the session)."""
    lines = [f"GET {path or '/'} HTTP/1.1", f"Host: {host}"]
    lines.extend(session_header_lines(raw_session))
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace")


def seed_prefix(seed_path: str) -> str:
    """The prefix defining the seed subtree. Seeding `/` crawls the whole host;
    seeding `/foo` crawls `/foo` and everything under `/foo/`."""
    base = (seed_path or "/").split("?", 1)[0]
    return base.rstrip("/") + "/"


def in_seed_subtree(path: str, seed_path: str) -> bool:
    """True if path is at or below the seed path (the spider never ascends above it)."""
    p = (path or "/").split("?", 1)[0]
    base = (seed_path or "/").split("?", 1)[0]
    return p == base or p.startswith(seed_prefix(seed_path))


def norm_url(scheme: str, host: str, port: int, path: str) -> str:
    return f"{scheme}://{host}:{port}{path}"


def split_target(url: str) -> Tuple[str, str, int, str]:
    """(scheme, host, port, path+query) from an absolute URL."""
    parts = urlsplit(url)
    scheme = parts.scheme or "http"
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path = path + "?" + parts.query
    return scheme, host, port, path
