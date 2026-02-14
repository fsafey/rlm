"""Tests for ChildStreamingLogger — sub-iteration streaming and cancellation propagation."""

from __future__ import annotations

import pytest

from rlm.core.types import CodeBlock, REPLResult, RLMIteration
from rlm_search.streaming_logger import ChildStreamingLogger, SearchCancelled, StreamingLogger


class TestChildStreamingLogger:
    """Test ChildStreamingLogger event emission and cancellation delegation."""

    def _make_parent(self) -> StreamingLogger:
        return StreamingLogger(log_dir="/tmp/rlm_test_child", file_name="test_parent")

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
        """log() should enqueue a sub_iteration event on parent's queue."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "What is X?")

        iteration = self._make_iteration(stdout="[search] query='test' results=3")
        child.log(iteration)

        assert len(parent.queue) == 1
        event = parent.queue[0]
        assert event["type"] == "sub_iteration"
        assert event["sub_question"] == "What is X?"
        assert "timestamp" in event
        assert "code_blocks" in event

    def test_log_metadata_is_noop(self):
        """log_metadata should not emit any events."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.log_metadata(None)
        assert len(parent.queue) == 0

    def test_on_environment_ready_is_noop(self):
        """on_environment_ready should not emit any events."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.on_environment_ready()
        assert len(parent.queue) == 0

    def test_raise_if_cancelled_delegates_to_parent(self):
        """raise_if_cancelled should raise when parent is cancelled."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")

        # Not cancelled — should not raise
        child.raise_if_cancelled()

        # Cancel parent
        parent.cancel()

        # Now child should raise
        with pytest.raises(SearchCancelled):
            child.raise_if_cancelled()

    def test_is_cancelled_delegates_to_parent(self):
        """is_cancelled property should reflect parent state."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")

        assert child.is_cancelled is False
        parent.cancel()
        assert child.is_cancelled is True

    def test_on_llm_start_is_noop(self):
        """on_llm_start should not emit any events (called by RLM core)."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.on_llm_start(1)
        assert len(parent.queue) == 0

    def test_on_code_executing_is_noop(self):
        """on_code_executing should not emit any events (called by RLM core)."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "test")
        child.on_code_executing(1, 2)
        assert len(parent.queue) == 0

    def test_multiple_sub_iterations_accumulate(self):
        """Multiple log() calls should accumulate events in parent queue."""
        parent = self._make_parent()
        child = ChildStreamingLogger(parent, "Sub Q")

        child.log(self._make_iteration(stdout="[search] query='a' results=2"))
        child.log(self._make_iteration(stdout="[draft_answer] PASS"))

        assert len(parent.queue) == 2
        assert all(e["type"] == "sub_iteration" for e in parent.queue)
        assert all(e["sub_question"] == "Sub Q" for e in parent.queue)
