"""Thread-safe in-process event hub.

The BatchWriter publishes history events (entry_created / entry_updated) here
AFTER each commit, from the writer thread. Subscribers must be non-blocking and
must not raise; the API layer's subscriber just marshals the event into the
asyncio loop for WebSocket delivery. This module is plain core (no asyncio, no
fastapi) so the core stays import-clean.
"""

from __future__ import annotations

import threading
from typing import Callable, List

Subscriber = Callable[[dict], None]


class EventHub:
    def __init__(self) -> None:
        self._subs: List[Subscriber] = []
        self._lock = threading.Lock()

    def subscribe(self, cb: Subscriber) -> Callable[[], None]:
        """Register a subscriber. Returns an unsubscribe callable."""
        with self._lock:
            self._subs.append(cb)

        def unsubscribe() -> None:
            with self._lock:
                if cb in self._subs:
                    self._subs.remove(cb)

        return unsubscribe

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(event)
            except Exception:
                # A misbehaving subscriber must never break the writer thread.
                pass
