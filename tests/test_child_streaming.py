"""Tests for ChildStreamingLogger — sub-iteration streaming and cancellation propagation."""

from __future__ import annotations

import pytest

from rlm.core.types import CodeBlock, REPLResult, RLMIteration
from rlm_search.bus import SearchCancelled
from rlm_search.streaming_logger import ChildStreamingLogger, StreamingLoggerV2


class TestChildStreamingLogger:
    """Test ChildStreamingLogger event emission and cancellation delegation."""

    def _make_parent(self) -> StreamingLoggerV2:
        return StreamingLoggerV2(
            log_dir="/tmp/rlm_test_child",
            file_name="test_parent",
            search_id="test-search",
            query="test query",
            bus=__import__("rlm_search.bus", fromlist=["EventBus"]).EventBus(),
        )

    def _make_iteration(self, stdout: str = "", final_answer: str | None = None) -> RLMIteration:
        repl_result = REPLResult(stdout=stdout, stderr="", locals={}, execution_time=0.1)
        return RLMIteration(
            prompt="test",
            response="test response",
            code_blocks=[CodeBlock(code="pass", result=repl_result)],
            final_answer=final_answer,
            iteration_time=1.0,
        )

    def test_log_emits_sub_iteration_event(self):
        """log() should emit a sub_iteration event on parent's bus."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "What is X?")

        iteration = self._make_iteration(stdout="[search] query='test' results=3")
        child.log(iteration)

        events = parent.bus.drain()
        sub_events = [e for e in events if e["type"] == "sub_iteration"]
        assert len(sub_events) == 1
        assert sub_events[0]["data"]["sub_question"] == "What is X?"

    def test_log_metadata_is_noop(self):
        """log_metadata should not emit any events."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.log_metadata(None)
        events = parent.bus.drain()
        assert len(events) == 0

    def test_on_environment_ready_is_noop(self):
        """on_environment_ready should not emit any events."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.on_environment_ready()
        events = parent.bus.drain()
        assert len(events) == 0

    def test_raise_if_cancelled_delegates_to_parent(self):
        """raise_if_cancelled should raise when parent bus is cancelled."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")

        # Not cancelled — should not raise
        child.raise_if_cancelled()

        # Cancel parent bus
        parent.bus.cancel()

        # Now child should raise
        with pytest.raises(SearchCancelled):
            child.raise_if_cancelled()

    def test_is_cancelled_delegates_to_parent(self):
        """is_cancelled property should reflect parent bus state."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")

        assert child.is_cancelled is False
        parent.bus.cancel()
        assert child.is_cancelled is True

    def test_on_llm_start_is_noop(self):
        """on_llm_start should not emit any events (called by RLM core)."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.on_llm_start(1)
        events = parent.bus.drain()
        assert len(events) == 0

    def test_on_code_executing_is_noop(self):
        """on_code_executing should not emit any events (called by RLM core)."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.on_code_executing(1, 2)
        events = parent.bus.drain()
        assert len(events) == 0

    def test_multiple_sub_iterations_accumulate(self):
        """Multiple log() calls should accumulate events in parent bus."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "Sub Q")

        child.log(self._make_iteration(stdout="[search] query='a' results=2"))
        child.log(self._make_iteration(stdout="[draft_answer] PASS"))

        events = parent.bus.replay()
        sub_events = [e for e in events if e["type"] == "sub_iteration"]
        assert len(sub_events) == 2
        assert all(e["data"]["sub_question"] == "Sub Q" for e in sub_events)
