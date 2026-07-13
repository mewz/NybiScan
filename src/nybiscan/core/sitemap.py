"""Passive site-map: a host -> path tree derived by querying captured history.

Zero new requests, always safe. Built from a single pass over the history table
(browser + spider rows), grouped by host, with each URL path split into segments to
form a nested tree. Only actually-observed (mapped) nodes appear; the grey
"seen-but-not-visited" two-state is a deferred feature.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SitemapNode(BaseModel):
    """One path segment in a host's tree. `full_path` is the absolute path from root
    to this node. `entry_ids` are the history rows observed at exactly this path (a
    node can be an internal directory with no direct entries). `sources` is the set of
    provenances that observed it (browser/spider)."""

    name: str  # this segment (e.g. "cgi-bin"); "/" for the host root
    full_path: str  # e.g. "/cgi-bin/update.php"
    entry_ids: List[int] = Field(default_factory=list)
    methods: List[str] = Field(default_factory=list)
    statuses: List[int] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    children: List["SitemapNode"] = Field(default_factory=list)


class SitemapHost(BaseModel):
    scheme: str
    host: str
    port: int
    entry_count: int
    root: SitemapNode


class _MutNode:
    __slots__ = ("name", "full_path", "entry_ids", "methods", "statuses", "sources", "children")

    def __init__(self, name: str, full_path: str) -> None:
        self.name = name
        self.full_path = full_path
        self.entry_ids: List[int] = []
        self.methods: set = set()
        self.statuses: set = set()
        self.sources: set = set()
        self.children: dict = {}  # segment -> _MutNode

    def child(self, segment: str, full_path: str) -> "_MutNode":
        node = self.children.get(segment)
        if node is None:
            node = _MutNode(segment, full_path)
            self.children[segment] = node
        return node

    def freeze(self) -> SitemapNode:
        return SitemapNode(
            name=self.name,
            full_path=self.full_path,
            entry_ids=sorted(self.entry_ids),
            methods=sorted(self.methods),
            statuses=sorted(self.statuses),
            sources=sorted(self.sources),
            children=[self.children[k].freeze() for k in sorted(self.children)],
        )


def _split_path(url: str) -> List[str]:
    path = url.split("?", 1)[0]
    return [seg for seg in path.split("/") if seg]


_ROW_SQL = (
    "SELECT id, scheme, host, port, method, url, status, source FROM history "
    "ORDER BY host, id"
)


def build_sitemap(conn) -> List[SitemapHost]:
    """Return one SitemapHost per (scheme, host, port) observed in history."""
    return _build(conn, host=None)


def build_host_map(conn, host: str) -> Optional[SitemapHost]:
    """Return the map for a single host, or None if the host has no history."""
    hosts = _build(conn, host=host)
    return hosts[0] if hosts else None


def _build(conn, host: Optional[str]) -> List[SitemapHost]:
    if host:
        rows = conn.execute(
            _ROW_SQL.replace("ORDER BY host, id", "WHERE host = ? ORDER BY id"), (host,)
        ).fetchall()
    else:
        rows = conn.execute(_ROW_SQL).fetchall()

    # Group by (scheme, host, port); a host on http and https is two map entries.
    roots: dict = {}
    counts: dict = {}
    for rid, scheme, h, port, method, url, status, source in rows:
        key = (scheme, h, port)
        root = roots.get(key)
        if root is None:
            root = _MutNode("/", "/")
            roots[key] = root
            counts[key] = 0
        counts[key] += 1

        node = root
        acc = ""
        for seg in _split_path(url):
            acc = acc + "/" + seg
            node = node.child(seg, acc)
        # The row's entry attaches to the deepest node for its path.
        node.entry_ids.append(rid)
        if method:
            node.methods.add(method)
        if status is not None:
            node.statuses.add(status)
        if source:
            node.sources.add(source)

    out: List[SitemapHost] = []
    for (scheme, h, port), root in sorted(roots.items()):
        out.append(
            SitemapHost(
                scheme=scheme, host=h, port=port,
                entry_count=counts[(scheme, h, port)], root=root.freeze(),
            )
        )
    return out
