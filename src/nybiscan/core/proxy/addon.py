"""mitmproxy addon that captures flows into the project via the BatchWriter.

The addon NEVER opens a db connection. It enqueues INSERT (on request) and
UPDATE (on response/error) ops onto the project's single BatchWriter, preserving
the single-writer invariant. Body filtering and encryption are handled by the
store, transparently.
"""

from __future__ import annotations

import threading
from typing import Optional

from ..schemas import CaptureStatus
from . import capture


class CaptureAddon:
    def __init__(self, project, ready: Optional[threading.Event] = None) -> None:
        self._project = project
        self._ready = ready

    # mitmproxy calls this once the master is up and the listener is bound.
    def running(self) -> None:
        if self._ready is not None:
            self._ready.set()

    def request(self, flow) -> None:
        try:
            record = capture.record_from_request(flow)
        except Exception:
            return
        self._project.writer.enqueue(record)

    def response(self, flow) -> None:
        try:
            patch = capture.response_patch(flow)
        except Exception:
            self._project.writer.enqueue_update_status(flow.id, CaptureStatus.error)
            return
        self._project.writer.enqueue_update_response(flow.id, patch)

    def error(self, flow) -> None:
        # Connection failure / timeout: mark the pending row as error.
        self._project.writer.enqueue_update_status(flow.id, CaptureStatus.error)
