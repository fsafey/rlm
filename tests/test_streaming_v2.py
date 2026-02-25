"""tests/test_streaming_v2.py"""
import json
import os
import tempfile

from rlm.core.types import CodeBlock, REPLResult, RLMIteration, RLMMetadata
from rlm_search.bus import EventBus
from rlm_search.streaming_logger import StreamingLoggerV2


def _make_iteration(response: str = "test", code: str = "", stdout: str = "") -> RLMIteration:
    blocks = []
    if code:
        blocks.append(CodeBlock(
            code=code,
            result=REPLResult(stdout=stdout, stderr="", locals={}, execution_time=0.1),
        ))
    return RLMIteration(
        prompt=[{"role": "user", "content": "test"}],
        response=response,
        code_blocks=blocks,
        iteration_time=1.0,
    )


class TestStreamingV2EmitsToBus:
    def test_log_metadata_emits_to_bus(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            meta = RLMMetadata(
                root_model="test-model",
                max_depth=1,
                max_iterations=10,
                backend="anthropic",
                backend_kwargs={},
                environment_type="local",
                environment_kwargs={},
            )
            logger.log_metadata(meta)
        events = bus.replay()
        meta_events = [e for e in events if e["type"] == "metadata"]
        assert len(meta_events) == 1
        assert meta_events[0]["data"]["root_model"] == "test-model"

    def test_log_iteration_emits_to_bus(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            iteration = _make_iteration(response="thinking...", code="x = 1", stdout="done")
            logger.log(iteration)
        events = bus.replay()
        iter_events = [e for e in events if e["type"] == "iteration"]
        assert len(iter_events) == 1

    def test_mark_done_emits_terminal(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            logger.mark_done(answer="result", sources=[], execution_time=1.0, usage={})
        assert bus.is_done
        events = bus.replay()
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"]["answer"] == "result"


class TestStreamingV2WritesJSONL:
    def test_writes_to_disk(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            meta = RLMMetadata(
                root_model="m", max_depth=1, max_iterations=10,
                backend="anthropic", backend_kwargs={},
                environment_type="local", environment_kwargs={},
            )
            logger.log_metadata(meta)
            logger.log(_make_iteration())
            logger.mark_done(answer="a", sources=[], execution_time=1.0, usage={})
            files = [f for f in os.listdir(tmpdir) if f.endswith(".jsonl")]
            assert len(files) == 1
            with open(os.path.join(tmpdir, files[0])) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            types = [line["type"] for line in lines]
            assert "metadata" in types
            assert "iteration" in types
            assert "done" in types


class TestStreamingV2Cancellation:
    def test_raise_if_cancelled_delegates_to_bus(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            bus.cancel()
            import pytest

            from rlm_search.bus import SearchCancelled
            with pytest.raises(SearchCancelled):
                logger.raise_if_cancelled()
