"""tests/test_context_v2.py"""

from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate
from rlm_search.tools.context import SearchContext


class TestSearchContextCreation:
    def test_creates_with_departments(self):
        bus = EventBus()
        evidence = EvidenceStore()
        quality = QualityGate(evidence=evidence)
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="test-key",
            bus=bus,
            evidence=evidence,
            quality=quality,
        )
        assert ctx.api_url == "https://example.com"
        assert ctx.evidence is evidence
        assert ctx.quality is quality
        assert ctx.bus is bus

    def test_headers_auto_generated(self):
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="test-key",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert ctx.headers["x-api-key"] == "test-key"

    def test_llm_callables_default_none(self):
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert ctx.llm_query is None
        assert ctx.llm_query_batched is None

    def test_tool_calls_list_for_repl_compat(self):
        """tool_calls must remain a plain list for REPL locals compatibility."""
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert isinstance(ctx.tool_calls, list)


class TestEvaluatedRatingsFacade:
    """evaluated_ratings must present dict[str, str] interface over EvidenceStore._ratings."""

    def _make_ctx(self) -> SearchContext:
        return SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
        )

    def test_write_then_read_returns_string(self):
        ctx = self._make_ctx()
        ctx.evaluated_ratings["q1"] = "RELEVANT"
        assert ctx.evaluated_ratings["q1"] == "RELEVANT"

    def test_contains_check(self):
        ctx = self._make_ctx()
        ctx.evaluated_ratings["q1"] = "PARTIAL"
        assert "q1" in ctx.evaluated_ratings
        assert "q99" not in ctx.evaluated_ratings

    def test_get_with_default(self):
        ctx = self._make_ctx()
        assert ctx.evaluated_ratings.get("missing", "UNRATED") == "UNRATED"
        ctx.evaluated_ratings["q1"] = "OFF-TOPIC"
        assert ctx.evaluated_ratings.get("q1", "UNRATED") == "OFF-TOPIC"

    def test_write_propagates_to_evidence_store(self):
        ctx = self._make_ctx()
        ctx.evaluated_ratings["q1"] = "RELEVANT"
        # Verify it went through set_rating with proper dict format
        rating_info = ctx.evidence.get_rating("q1")
        assert rating_info is not None
        assert rating_info["rating"] == "RELEVANT"
        assert rating_info["confidence"] == 3  # default

    def test_items_returns_flat_pairs(self):
        ctx = self._make_ctx()
        ctx.evaluated_ratings["a"] = "RELEVANT"
        ctx.evaluated_ratings["b"] = "OFF-TOPIC"
        pairs = dict(ctx.evaluated_ratings.items())
        assert pairs == {"a": "RELEVANT", "b": "OFF-TOPIC"}

    def test_len(self):
        ctx = self._make_ctx()
        assert len(ctx.evaluated_ratings) == 0
        ctx.evaluated_ratings["q1"] = "RELEVANT"
        assert len(ctx.evaluated_ratings) == 1

    def test_equality_with_off_topic_string(self):
        """Critical: research() does ctx.evaluated_ratings[id] == 'OFF-TOPIC'."""
        ctx = self._make_ctx()
        ctx.evaluated_ratings["q1"] = "OFF-TOPIC"
        assert ctx.evaluated_ratings["q1"] == "OFF-TOPIC"
        # Also verify the != pattern used for filtering
        assert ctx.evaluated_ratings.get("q1", "UNRATED") != "RELEVANT"


class TestChildScopeExceptionSafety:
    """_child_scope must restore current_parent_idx even on exception."""

    def test_restores_on_exception(self):
        from rlm_search.tools.composite_tools import _child_scope

        ctx = self._make_ctx()
        ctx.current_parent_idx = 42
        try:
            with _child_scope(ctx, 99):
                assert ctx.current_parent_idx == 99
                raise ValueError("boom")
        except ValueError:
            pass
        assert ctx.current_parent_idx == 42

    def test_restores_on_success(self):
        from rlm_search.tools.composite_tools import _child_scope

        ctx = self._make_ctx()
        ctx.current_parent_idx = 7
        with _child_scope(ctx, 100):
            assert ctx.current_parent_idx == 100
        assert ctx.current_parent_idx == 7

    def _make_ctx(self) -> SearchContext:
        return SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
        )
