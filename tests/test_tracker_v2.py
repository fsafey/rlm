"""tests/test_tracker_v2.py"""

import contextlib

from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate
from rlm_search.tools.context import SearchContext


def _make_ctx() -> SearchContext:
    bus = EventBus()
    evidence = EvidenceStore()
    quality = QualityGate(evidence=evidence)
    return SearchContext(
        api_url="https://test.com", api_key="k", bus=bus, evidence=evidence, quality=quality
    )


class TestTrackerEmitsToBus:
    def test_tool_start_event_emitted(self):
        from rlm_search.tools.tracker import tool_call_tracker

        ctx = _make_ctx()
        with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
            tc.set_summary({"num_results": 5})
        events = ctx.bus.replay()
        start_events = [e for e in events if e["type"] == "tool_start"]
        assert len(start_events) == 1
        assert start_events[0]["data"]["tool"] == "search"

    def test_tool_end_event_emitted(self):
        from rlm_search.tools.tracker import tool_call_tracker

        ctx = _make_ctx()
        with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
            tc.set_summary({"num_results": 5})
        events = ctx.bus.replay()
        end_events = [e for e in events if e["type"] == "tool_end"]
        assert len(end_events) == 1
        assert end_events[0]["data"]["tool"] == "search"
        assert "duration_ms" in end_events[0]["data"]

    def test_tool_calls_list_still_populated(self):
        """REPL locals compatibility: ctx.tool_calls must still be appended."""
        from rlm_search.tools.tracker import tool_call_tracker

        ctx = _make_ctx()
        with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
            tc.set_summary({"num_results": 5})
        assert len(ctx.tool_calls) == 1
        assert ctx.tool_calls[0]["tool"] == "search"

    def test_tool_error_recorded(self):
        from rlm_search.tools.tracker import tool_call_tracker

        ctx = _make_ctx()
        with contextlib.suppress(ValueError):
            with tool_call_tracker(ctx, "search", {"query": "test"}):
                raise ValueError("test error")
        assert ctx.tool_calls[0]["error"] is not None
        end_events = [e for e in ctx.bus.replay() if e["type"] == "tool_error"]
        assert len(end_events) == 1
        assert end_events[0]["data"].get("error") is not None
