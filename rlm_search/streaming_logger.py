"""rlm_search/streaming_logger.py — RLMLogger that emits through EventBus."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rlm.core.types import RLMIteration, RLMMetadata
from rlm.logger.rlm_logger import RLMLogger
from rlm_search.bus import EventBus, SearchCancelled  # noqa: F401 — re-export for compat


class StreamingLoggerV2(RLMLogger):
    """RLMLogger that emits all events through an EventBus.

    Replaces StreamingLogger's internal queue with EventBus delegation.
    Still writes JSONL to disk for audit trail.
    No more dual-path data flow — EventBus is the single channel.
    """

    def __init__(
        self,
        log_dir: str,
        file_name: str,
        search_id: str,
        query: str,
        bus: EventBus,
    ) -> None:
        super().__init__(log_dir=log_dir, file_name=file_name)
        self.search_id = search_id
        self.query = query
        self.bus = bus

    # --- RLMLogger overrides ---

    def log_metadata(self, metadata: RLMMetadata) -> None:
        """Emit metadata to bus + write to JSONL."""
        if self._metadata_logged:
            return
        data = metadata.to_dict()
        data["search_id"] = self.search_id
        data["query"] = self.query

        self.bus.emit("metadata", data)

        entry = {"type": "metadata", "timestamp": datetime.now().isoformat(), **data}
        self._write_jsonl(entry)
        self._metadata_logged = True

    def log(self, iteration: RLMIteration) -> None:
        """Emit iteration to bus + write to JSONL."""
        self._iteration_count += 1
        data = {
            "iteration": self._iteration_count,
            **iteration.to_dict(),
        }

        self.bus.emit("iteration", data)

        entry = {"type": "iteration", "timestamp": datetime.now().isoformat(), **data}
        self._write_jsonl(entry)

    # --- Terminal events ---

    def mark_done(
        self,
        answer: str | None,
        sources: list[dict[str, Any]],
        execution_time: float,
        usage: dict[str, Any],
    ) -> None:
        data = {
            "answer": answer,
            "sources": sources,
            "execution_time": execution_time,
            "usage": usage,
        }
        self.bus.emit("done", data)
        entry = {"type": "done", "timestamp": datetime.now().isoformat(), **data}
        self._write_jsonl(entry)

    def mark_error(self, message: str) -> None:
        self.bus.emit("error", {"message": message})
        entry = {"type": "error", "timestamp": datetime.now().isoformat(), "message": message}
        self._write_jsonl(entry)

    def mark_cancelled(self) -> None:
        self.bus.emit("cancelled", {})
        entry = {"type": "cancelled", "timestamp": datetime.now().isoformat()}
        self._write_jsonl(entry)

    # --- Cancellation (delegated to bus) ---

    def raise_if_cancelled(self) -> None:
        self.bus.raise_if_cancelled()

    # --- Properties for backward compat ---

    @property
    def is_done(self) -> bool:
        return self.bus.is_done

    # --- Internal ---

    def _write_jsonl(self, entry: dict[str, Any]) -> None:
        with open(self.log_file_path, "a") as f:
            json.dump(entry, f)
            f.write("\n")


class ChildStreamingLogger:
    """Sub-agent logger — emits sub_iteration events through parent's bus.

    Used by delegation_tools.rlm_query() so child RLM iterations stream
    to the same SSE channel as the parent search.
    """

    def __init__(self, parent: StreamingLoggerV2, sub_question: str) -> None:
        self._parent = parent
        self.sub_question = sub_question

    # --- RLMLogger duck-type interface (called by RLM core) ---

    def log_metadata(self, metadata: Any) -> None:
        pass  # Sub-agents don't emit metadata

    def log(self, iteration: RLMIteration) -> None:
        data = {
            "sub_question": self.sub_question,
            **iteration.to_dict(),
        }
        self._parent.bus.emit("sub_iteration", data)
        entry = {"type": "sub_iteration", "timestamp": datetime.now().isoformat(), **data}
        self._parent._write_jsonl(entry)

    def raise_if_cancelled(self) -> None:
        self._parent.bus.raise_if_cancelled()

    @property
    def is_cancelled(self) -> bool:
        return self._parent.bus.cancelled

    def on_environment_ready(self) -> None:
        pass

    def on_llm_start(self, iteration: int) -> None:
        pass

    def on_code_executing(self, iteration: int, num_blocks: int) -> None:
        pass

    @property
    def iteration_count(self) -> int:
        return 0


# Backward-compat alias
StreamingLogger = StreamingLoggerV2
