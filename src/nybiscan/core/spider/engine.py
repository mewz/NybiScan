"""Scope-gated seed-based crawl engine.

Models ProxyEngine's lifecycle (daemon thread, start/stop/status). Fetches pages
DIRECTLY with the Bench low-level send (reusing TLS-no-verify + response read +
decompress), records each result into the SHARED history table via the single
BatchWriter tagged source=spider, and follows in-scope links. All the safety rails
live here: scope boundary, absolute exclude list, seed-subtree limit, depth cap,
hard request cap, interruptible rate limit, and prompt stop.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .. import scope as scope_mod
from ..bench import engine as bench_engine
from ..proxy.capture import parse_extension
from ..schemas import CaptureStatus, HistoryRecord
from . import rules


@dataclass
class SpiderConfig:
    seed_history_id: int
    max_depth: int = 3
    exclude: list = field(default_factory=lambda: [
        {"pattern": "/logout", "is_regex": False},
        {"pattern": "/signout", "is_regex": False},
    ])
    rate_limit_ms: int = 500
    max_requests: int = 300
    include_binary: bool = False


def _ms() -> int:
    return int(time.time() * 1000)


class SpiderEngine:
    def __init__(self, project, config: SpiderConfig, scope_hosts, scope_headers, seed_record):
        if project is None:
            raise ValueError("SpiderEngine requires an open project to write into")
        self._project = project
        self.config = config
        self._scope: Set[str] = {h.strip().lower() for h in scope_hosts}
        self._scope_headers: Dict[str, Optional[str]] = dict(scope_headers)
        self._seed = seed_record
        # compile_excludes raises ExcludeError on a bad regex (caller validates first).
        self._excludes = rules.compile_excludes(config.exclude)

        self.run_id = uuid.uuid4().hex
        self._seed_host = seed_record.host
        self._seed_scheme = seed_record.scheme
        self._seed_port = seed_record.port
        self._seed_path = seed_record.path  # url path without query

        self._found = 0
        self._current: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="nybiscan-spider", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def snapshot(self) -> dict:
        """Engine-side status. The route adds `saved` from the read connection."""
        return {
            "running": self.running,
            "found": self._found,
            "cap": self.config.max_requests,
            "current": self._current,
            "run_id": self.run_id,
        }

    # ----- crawl loop -------------------------------------------------------

    def _run(self) -> None:
        frontier = deque()
        visited: Set[str] = set()
        seed_url = rules.norm_url(
            self._seed_scheme, self._seed_host, self._seed_port, self._seed.url
        )
        frontier.append((self._seed_scheme, self._seed_host, self._seed_port, self._seed.url, 0))

        first = True
        while frontier and not self._stop.is_set() and self._found < self.config.max_requests:
            scheme, host, port, path, depth = frontier.popleft()
            key = rules.norm_url(scheme, host, port, path)
            if key in visited:
                continue
            visited.add(key)

            # Rails checked before EVERY fetch: exclude + scope (seed re-checked too).
            if rules.is_excluded(path, self._excludes):
                continue
            if not scope_mod.host_in_scope(self._scope, host):
                continue

            # Interruptible politeness delay (Stop responds promptly even at a high
            # rate limit). Skipped before the very first fetch.
            if not first:
                if self._stop.wait(self.config.rate_limit_ms / 1000.0):
                    break
            first = False

            self._current = key
            body, is_html = self._fetch_and_record(scheme, host, port, path)

            if is_html and body and depth < self.config.max_depth:
                for link in rules.extract_links(key, body):
                    s2, h2, p2, path2 = rules.split_target(link)
                    if not h2:
                        continue
                    if not scope_mod.host_in_scope(self._scope, h2):
                        continue
                    # Seed-subtree limit applies to the seed host only.
                    if h2 == self._seed_host and not rules.in_seed_subtree(path2, self._seed_path):
                        continue
                    if rules.is_excluded(path2, self._excludes):
                        continue
                    if rules.skip_binary(link, self.config.include_binary):
                        continue
                    nkey = rules.norm_url(s2, h2, p2, path2)
                    if nkey in visited:
                        continue
                    frontier.append((s2, h2, p2, path2, depth + 1))

        self._current = None
        # Flush what was enqueued so `saved` reflects the run on completion. On early
        # stop this still persists everything fetched; only un-fetched frontier URLs
        # are dropped (acceptable: the spider is re-runnable).
        try:
            self._project.writer.flush()
        except Exception:
            pass

    def _fetch_and_record(self, scheme, host, port, path):
        """Fetch one URL, enqueue a spider HistoryRecord, return (body, is_html)."""
        raw = rules.build_get(path, host, self._scope_headers.get(host))
        started = _ms()
        resp = bench_engine.send_raw(host, port, scheme == "https", raw, content_length_autofill=False)
        mime = resp.get("mime_type")
        errored = resp.get("error") is not None
        rec = HistoryRecord(
            scheme=scheme, host=host, port=port, method="GET", url=path,
            extension=parse_extension(path),
            req_headers_raw=raw.decode("latin-1", "replace"),
            req_start_ts=started,
            status=resp.get("status"),
            resp_length=resp.get("resp_length", 0),
            mime_type=mime,
            resp_headers_raw=resp.get("resp_headers_raw", ""),
            resp_body=resp.get("resp_body"),
            resp_content_encoding=resp.get("resp_content_encoding"),
            resp_complete_ts=_ms(),
            capture_status=CaptureStatus.error if errored else CaptureStatus.complete,
            source="spider",
            spider_run_id=self.run_id,
        )
        self._project.writer.enqueue(rec)
        self._found += 1
        is_html = bool(mime and mime.startswith("text/html"))
        return resp.get("resp_body"), is_html
