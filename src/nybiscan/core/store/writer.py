"""Batched single-writer thread.

A proxy bursts to hundreds of requests per page load, so we NEVER open one
transaction per request. The capture engine calls enqueue(); a single daemon
thread drains the queue and flushes in batched transactions (every batch_size
records OR every flush_interval seconds, whichever comes first). Exactly one
transaction (one COMMIT) per flush.

The writer owns its OWN write connection and is the only thread that touches it,
preserving SQLite's single-writer invariant. Readers use a separate connection.
"""

from __future__ import annotations

import queue
import threading
from typing import List, Optional

from ..filters import StorageContext
from ..schemas import HistoryRecord
from . import db, repository


class _FlushMarker:
    """Sentinel that forces a flush and signals completion to the caller."""

    __slots__ = ("event",)

    def __init__(self) -> None:
        self.event = threading.Event()


class _StopMarker:
    pass


class BatchWriter:
    def __init__(
        self,
        db_path: str,
        key: Optional[bytes],
        ctx: StorageContext,
        batch_size: int = 100,
        flush_interval: float = 0.1,
    ) -> None:
        self._ctx = ctx
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._q: "queue.Queue" = queue.Queue()

        # commit_count is instrumentation: tests assert one COMMIT per flush.
        self.commit_count = 0
        self.records_written = 0

        # Only the worker thread ever touches this connection.
        self._conn = db.open_connection(db_path, key, check_same_thread=False)

        self._thread = threading.Thread(target=self._run, name="nybiscan-writer", daemon=True)
        self._thread.start()

    # -- public API ----------------------------------------------------------

    def enqueue(self, record: HistoryRecord) -> None:
        self._q.put(record)

    def flush(self) -> None:
        """Block until all currently-queued records have been committed."""
        marker = _FlushMarker()
        self._q.put(marker)
        marker.event.wait()

    def close(self) -> None:
        """Drain, checkpoint the WAL, and close the write connection."""
        self._q.put(_StopMarker())
        self._thread.join()
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self._conn.close()

    # -- worker --------------------------------------------------------------

    def _run(self) -> None:
        batch: List[HistoryRecord] = []
        while True:
            try:
                item = self._q.get(timeout=self._flush_interval)
            except queue.Empty:
                self._do_flush(batch)
                batch = []
                continue

            if isinstance(item, _FlushMarker):
                self._do_flush(batch)
                batch = []
                item.event.set()
                continue

            if isinstance(item, _StopMarker):
                self._do_flush(batch)
                batch = []
                break

            batch.append(item)
            if len(batch) >= self._batch_size:
                self._do_flush(batch)
                batch = []

    def _do_flush(self, batch: List[HistoryRecord]) -> None:
        if not batch:
            return
        repository.insert_history_batch(self._conn, batch, self._ctx)
        self._conn.commit()  # exactly one COMMIT per flush
        self.commit_count += 1
        self.records_written += len(batch)
