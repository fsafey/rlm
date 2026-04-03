"""rlm_search/bus.py — push-based event channel with async queue."""

import asyncio
import threading
from datetime import datetime
from typing import Any

TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})


class SearchCancelled(Exception):
    """Raised when a search is cancelled via the EventBus."""


class EventBus:
    """Single append-only event channel for all rlm_search streaming.

    Producer threads call emit() (thread-safe).
    SSE consumer calls bind_and_replay() once, then awaits next_event().
    No polling — events are pushed via asyncio.Queue.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._log: list[dict[str, Any]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_q: asyncio.Queue[dict[str, Any]] | None = None
        self._cancelled = False
        self._done = False

    def bind_and_replay(
        self, loop: asyncio.AbstractEventLoop,
    ) -> list[dict[str, Any]]:
        """Atomically bind async queue and return all historical events.

        Must be called exactly once from the SSE async context.
        After this call, emit() pushes into the async queue.
        """
        with self._lock:
            self._loop = loop
            self._async_q = asyncio.Queue()
            return self._log[:]

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Append a typed event to the bus (thread-safe)."""
        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        with self._lock:
            self._log.append(event)
            if event_type in TERMINAL_EVENTS:
                self._done = True
        if self._loop is not None and self._async_q is not None:
            self._loop.call_soon_threadsafe(self._async_q.put_nowait, event)

    async def next_event(self, timeout: float = 15.0) -> dict[str, Any] | None:
        """Await the next event, or return None on timeout (for keepalive)."""
        if self._async_q is None:
            return None
        try:
            return await asyncio.wait_for(self._async_q.get(), timeout)
        except asyncio.TimeoutError:
            return None

    def replay(self) -> list[dict[str, Any]]:
        """Return ALL events ever emitted. Does not clear."""
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
