"""Streaming logger that bridges sync RLM iterations to async SSE via a queue."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

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
        self.source_registry: dict[str, dict] = {}
        self._last_tool_call_count = 0
        self._tool_stats: dict[str, dict] = {}  # {tool_name: {count, total_ms, errors}}

    _RESERVED_PROGRESS_KEYS = frozenset({"type", "phase", "detail", "timestamp"})

    def emit_progress(self, phase: str, detail: str = "", **kwargs: Any) -> None:
        """Emit a lightweight progress event for frontend initialization display."""
        assert not (self._RESERVED_PROGRESS_KEYS & set(kwargs)), (
            f"kwargs must not override reserved keys: {self._RESERVED_PROGRESS_KEYS & set(kwargs)}"
        )
        event = {
            "type": "progress",
            "phase": phase,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
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

        # Replicate super().log() — increment count (but write enriched event below)
        self._iteration_count += 1

        # Accumulate source data from REPL's source_registry (populated by _normalize_hit)
        for block in iteration.code_blocks:
            sr = block.result.locals.get("source_registry")
            if isinstance(sr, dict):
                for sid, data in sr.items():
                    if isinstance(data, dict):
                        self.source_registry[sid] = data

        # Extract new tool_calls since last iteration
        tool_calls_data: list[dict] = []
        for block in iteration.code_blocks:
            tc = block.result.locals.get("tool_calls")
            if isinstance(tc, list):
                tool_calls_data = tc[self._last_tool_call_count :]
                self._last_tool_call_count = len(tc)

        # Accumulate tool stats for done event summary
        for tc in tool_calls_data:
            name = tc.get("tool", "unknown")
            if name not in self._tool_stats:
                self._tool_stats[name] = {"count": 0, "total_ms": 0, "errors": 0}
            self._tool_stats[name]["count"] += 1
            self._tool_stats[name]["total_ms"] += tc.get("duration_ms", 0)
            if tc.get("error"):
                self._tool_stats[name]["errors"] += 1

        event = {
            "type": "iteration",
            "iteration": self._iteration_count,
            "timestamp": datetime.now().isoformat(),
            **iteration.to_dict(),
            "tool_calls": tool_calls_data,
        }

        # Write enriched event (with tool_calls) to disk
        with open(self.log_file_path, "a") as f:
            json.dump(event, f)
            f.write("\n")

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
            "tool_summary": self._tool_stats,
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
