"""Batched single-writer thread.

A proxy bursts to hundreds of requests per page load, so we NEVER open one
transaction per request. The capture engine calls enqueue()/enqueue_update_*();
a single daemon thread drains the queue and flushes in batched transactions
(every batch_size ops OR every flush_interval seconds, whichever comes first).
Exactly one transaction (one COMMIT) per flush.

The queue carries three op types: INSERT (a new pending/complete record),
UPDATE_RESPONSE (pending -> complete for a flow_id), and UPDATE_STATUS
(pending -> error for a flow_id). Within a flush, all inserts are applied before
any updates, and after commit all entry_created events are published before any
entry_updated events, so a fast localhost request+response landing in one batch
never streams an update ahead of its create.

The writer owns its OWN write connection and is the only thread that touches it,
preserving SQLite's single-writer invariant. Readers use a separate connection.
"""

from __future__ import annotations

import queue
import threading
from typing import List, Optional

from ..events import EventHub
from ..filters import StorageContext
from ..schemas import CaptureStatus, HistoryRecord
from . import db, repository


class _Insert:
    __slots__ = ("record",)

    def __init__(self, record: HistoryRecord) -> None:
        self.record = record


class _UpdateResponse:
    __slots__ = ("flow_id", "patch")

    def __init__(self, flow_id: str, patch: HistoryRecord) -> None:
        self.flow_id = flow_id
        self.patch = patch


class _UpdateStatus:
    __slots__ = ("flow_id", "status")

    def __init__(self, flow_id: str, status: CaptureStatus) -> None:
        self.flow_id = flow_id
        self.status = status


class _FlushMarker:
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
        event_hub: Optional[EventHub] = None,
    ) -> None:
        self._ctx = ctx
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._event_hub = event_hub
        self._q: "queue.Queue" = queue.Queue()

        # Instrumentation: tests assert one COMMIT per flush and single-writer.
        self.commit_count = 0
        self.records_written = 0

        # Only the worker thread ever touches this connection.
        self._conn = db.open_connection(db_path, key, check_same_thread=False)

        self._thread = threading.Thread(target=self._run, name="nybiscan-writer", daemon=True)
        self._thread.start()

    # -- public API ----------------------------------------------------------

    def enqueue(self, record: HistoryRecord) -> None:
        """Enqueue an INSERT (new record)."""
        self._q.put(_Insert(record))

    def enqueue_update_response(self, flow_id: str, patch: HistoryRecord) -> None:
        """Enqueue an UPDATE applying a completed response to a pending row."""
        self._q.put(_UpdateResponse(flow_id, patch))

    def enqueue_update_status(self, flow_id: str, status: CaptureStatus) -> None:
        """Enqueue an UPDATE flipping capture_status (e.g. to error)."""
        self._q.put(_UpdateStatus(flow_id, status))

    def flush(self) -> None:
        """Block until all currently-queued ops have been committed."""
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
        batch: List[object] = []
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

    def _do_flush(self, batch: List[object]) -> None:
        if not batch:
            return

        inserts = [op for op in batch if isinstance(op, _Insert)]
        updates = [op for op in batch if isinstance(op, (_UpdateResponse, _UpdateStatus))]

        # Inserts first, then updates (an update may target a row inserted in the
        # same transaction), then a single commit.
        if inserts:
            repository.insert_history_batch(
                self._conn, [op.record for op in inserts], self._ctx
            )
        for op in updates:
            if isinstance(op, _UpdateResponse):
                repository.update_response_by_flow(
                    self._conn, op.flow_id, op.patch, self._ctx
                )
            else:  # _UpdateStatus
                repository.set_capture_status_by_flow(self._conn, op.flow_id, op.status)

        self._conn.commit()  # exactly one COMMIT per flush
        self.commit_count += 1
        self.records_written += len(inserts)

        # Publish AFTER commit so the row is queryable: all creates before updates.
        if self._event_hub is not None:
            for op in inserts:
                self._publish("entry_created", op.record.flow_id)
            for op in updates:
                self._publish("entry_updated", op.flow_id)

    def _publish(self, kind: str, flow_id: Optional[str]) -> None:
        if not flow_id:
            return
        row = self._conn.execute(
            "SELECT id, host, method, url, status, capture_status "
            "FROM history WHERE flow_id = ? ORDER BY id DESC LIMIT 1",
            (flow_id,),
        ).fetchone()
        if not row:
            return
        self._event_hub.publish(
            {
                "type": kind,
                "id": row[0],
                "flow_id": flow_id,
                "host": row[1],
                "method": row[2],
                "url": row[3],
                "status": row[4],
                "capture_status": row[5],
            }
        )
