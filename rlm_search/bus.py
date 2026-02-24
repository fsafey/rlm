"""rlm_search/bus.py"""

import threading
from datetime import datetime
from typing import Any

TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})


class SearchCancelled(Exception):
    """Raised when a search is cancelled via the EventBus."""


class EventBus:
    """Single append-only event channel for all rlm_search streaming.

    All departments emit here. SSE stream reads from here.
    Replaces: dual-channel streaming, stdout tag parsing,
    progress_callback, _parent_logger ref.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []  # pending (not yet drained)
        self._log: list[dict[str, Any]] = []  # all events ever (for replay)
        self._cancelled = False
        self._done = False

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Append a typed event to the bus."""
        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        with self._lock:
            self._queue.append(event)
            self._log.append(event)
            if event_type in TERMINAL_EVENTS:
                self._done = True

    def drain(self) -> list[dict[str, Any]]:
        """Return and clear pending events. Thread-safe."""
        with self._lock:
            events = self._queue[:]
            self._queue.clear()
        return events

    def replay(self) -> list[dict[str, Any]]:
        """Return ALL events ever emitted (for reconnection). Does not clear."""
        with self._lock:
            return self._log[:]

    def cancel(self) -> None:
        """Signal cancellation. Next raise_if_cancelled() will throw."""
        self._cancelled = True

    def raise_if_cancelled(self) -> None:
        """Check cancellation flag. Called by RLM core per iteration."""
        if self._cancelled:
            raise SearchCancelled("Search cancelled")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_done(self) -> bool:
        return self._done
