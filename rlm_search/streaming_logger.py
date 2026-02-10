"""Streaming logger that bridges sync RLM iterations to async SSE via a queue."""

from __future__ import annotations

import threading
from datetime import datetime

from rlm.core.types import RLMIteration, RLMMetadata
from rlm.logger.rlm_logger import RLMLogger


class StreamingLogger(RLMLogger):
    """RLMLogger subclass that pushes events to a thread-safe queue for SSE streaming."""

    def __init__(self, log_dir: str, file_name: str = "rlm"):
        super().__init__(log_dir, file_name)
        self.queue: list[dict] = []
        self._lock = threading.Lock()
        self._done = False

    def log_metadata(self, metadata: RLMMetadata) -> None:
        super().log_metadata(metadata)
        event = {
            "type": "metadata",
            "timestamp": datetime.now().isoformat(),
            **metadata.to_dict(),
        }
        with self._lock:
            self.queue.append(event)
            print(f"[STREAM] metadata event queued | queue_size={len(self.queue)}")

    def log(self, iteration: RLMIteration) -> None:
        super().log(iteration)
        event = {
            "type": "iteration",
            "iteration": self._iteration_count,
            "timestamp": datetime.now().isoformat(),
            **iteration.to_dict(),
        }
        with self._lock:
            self.queue.append(event)
            print(f"[STREAM] iteration {self._iteration_count} queued | has_code={bool(iteration.code_blocks)} final_answer={iteration.final_answer is not None}")

    def mark_done(
        self, answer: str | None, sources: list[dict], execution_time: float, usage: dict
    ) -> None:
        event = {
            "type": "done",
            "answer": answer or "",
            "sources": sources,
            "execution_time": execution_time,
            "usage": usage,
        }
        with self._lock:
            self.queue.append(event)
            self._done = True

    def mark_error(self, message: str) -> None:
        event = {"type": "error", "message": message}
        with self._lock:
            self.queue.append(event)
            self._done = True

    def drain(self) -> list[dict]:
        """Pop all pending events from the queue (thread-safe)."""
        with self._lock:
            events = self.queue[:]
            self.queue.clear()
        if events:
            print(f"[STREAM] drained {len(events)} events | done={self._done}")
        return events

    @property
    def is_done(self) -> bool:
        with self._lock:
            return self._done
