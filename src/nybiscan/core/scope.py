"""Scope enforcement helpers.

Scope is the spider's boundary and the authorized-use guard: the spider crawls only
in-scope hosts and refuses everything else. Matching is exact bare-host for now
(wildcard / subdomain patterns are a deferred feature). Kept as a pure function so
the spider and its tests share one definition.
"""

from __future__ import annotations

from typing import Iterable


def host_in_scope(hosts: Iterable[str], host: str) -> bool:
    """True if host is in scope. Exact bare-host match, case-insensitive."""
    if not host:
        return False
    target = host.strip().lower()
    return any(h.strip().lower() == target for h in hosts)
