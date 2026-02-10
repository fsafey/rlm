"""Streaming logger that bridges sync RLM iterations to async SSE via a queue."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from rlm.core.types import RLMIteration, RLMMetadata
from rlm.logger.rlm_logger import RLMLogger


class SearchCancelled(Exception):
    """Raised inside the RLM loop when a search is cancelled by the client."""


class StreamingLogger(RLMLogger):
    """RLMLogger subclass that pushes events to a thread-safe queue for SSE streaming."""

    def __init__(
        self,
        log_dir: str,
        file_name: str = "rlm",
        search_id: str = "",
        query: str = "",
    ):
        super().__init__(log_dir, file_name)
        self.search_id = search_id
        self.query = query
        self.queue: list[dict] = []
        self._lock = threading.Lock()
        self._done = False
        self._cancelled = False

    def emit_progress(self, phase: str, detail: str = "") -> None:
        """Emit a lightweight progress event for frontend initialization display."""
        event = {
            "type": "progress",
            "phase": phase,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
        }
        with self._lock:
            self.queue.append(event)

    def log_metadata(self, metadata: RLMMetadata) -> None:
        # Build the enriched event with search-level identifying info
        event = {
            "type": "metadata",
            "search_id": self.search_id,
            "query": self.query,
            "log_file": self.log_file_path,
            "timestamp": datetime.now().isoformat(),
            **metadata.to_dict(),
        }
        # Write enriched event to disk (skip parent's stripped version)
        if not self._metadata_logged:
            with open(self.log_file_path, "a") as f:
                json.dump(event, f)
                f.write("\n")
            self._metadata_logged = True
        # Push to SSE queue
        with self._lock:
            self.queue.append(event)
            print(f"[STREAM] metadata event queued | queue_size={len(self.queue)}")

    def cancel(self) -> None:
        """Signal cancellation. The next log() call will raise SearchCancelled."""
        with self._lock:
            self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def log(self, iteration: RLMIteration) -> None:
        with self._lock:
            if self._cancelled:
                raise SearchCancelled("Search cancelled by client")
        super().log(iteration)
        event = {
            "type": "iteration",
            "iteration": self._iteration_count,
            "timestamp": datetime.now().isoformat(),
            **iteration.to_dict(),
        }
        with self._lock:
            self.queue.append(event)
            print(
                f"[STREAM] iteration {self._iteration_count} queued | has_code={bool(iteration.code_blocks)} final_answer={iteration.final_answer is not None}"
            )

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
        with open(self.log_file_path, "a") as f:
            json.dump(event, f)
            f.write("\n")
        with self._lock:
            self.queue.append(event)
            self._done = True

    def mark_error(self, message: str) -> None:
        event = {"type": "error", "message": message}
        with open(self.log_file_path, "a") as f:
            json.dump(event, f)
            f.write("\n")
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
