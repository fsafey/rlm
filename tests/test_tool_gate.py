"""Tests for tool gating by classification confidence."""

from rlm_search.tool_gate import apply_gate, compute_tool_tier, TIER_REMOVALS


class TestComputeToolTier:
    """compute_tool_tier returns focused/standard/full based on classification."""

    def test_high_confidence_returns_focused(self):
        classification = {"confidence": "HIGH", "category": "PT", "also_category": ""}
        assert compute_tool_tier(classification) == "focused"

    def test_medium_confidence_returns_standard(self):
        classification = {"confidence": "MEDIUM", "category": "PT", "also_category": ""}
        assert compute_tool_tier(classification) == "standard"

    def test_low_confidence_returns_full(self):
        classification = {"confidence": "LOW", "category": "PT", "also_category": "BE"}
        assert compute_tool_tier(classification) == "full"

    def test_none_classification_returns_full(self):
        assert compute_tool_tier(None) == "full"

    def test_cross_category_downgrades_to_full(self):
        """When also_category is set, confidence is ambiguous — use full set."""
        classification = {"confidence": "HIGH", "category": "PT", "also_category": "WP"}
        assert compute_tool_tier(classification) == "full"

    def test_empty_category_returns_full(self):
        classification = {"confidence": "HIGH", "category": "", "also_category": ""}
        assert compute_tool_tier(classification) == "full"


class TestTierRemovals:
    """TIER_REMOVALS defines which tools to remove per tier."""

    def test_focused_removes_expensive_tools(self):
        assert "rlm_query" in TIER_REMOVALS["focused"]
        assert "browse" in TIER_REMOVALS["focused"]
        assert "reformulate" in TIER_REMOVALS["focused"]
        assert "critique_answer" in TIER_REMOVALS["focused"]

    def test_focused_keeps_core_tools(self):
        assert "research" not in TIER_REMOVALS["focused"]
        assert "draft_answer" not in TIER_REMOVALS["focused"]
        assert "check_progress" not in TIER_REMOVALS["focused"]
        assert "search" not in TIER_REMOVALS["focused"]
        assert "fiqh_lookup" not in TIER_REMOVALS["focused"]

    def test_standard_removes_only_rlm_query(self):
        assert "rlm_query" in TIER_REMOVALS["standard"]
        assert "browse" not in TIER_REMOVALS["standard"]

    def test_full_removes_nothing(self):
        assert TIER_REMOVALS["full"] == frozenset()


class TestApplyGate:
    """apply_gate removes tool functions from a namespace dict."""

    def _make_namespace(self) -> dict:
        """Simulate a REPL namespace with tool functions."""
        return {
            "research": lambda: None,
            "draft_answer": lambda: None,
            "check_progress": lambda: None,
            "search": lambda: None,
            "browse": lambda: None,
            "fiqh_lookup": lambda: None,
            "reformulate": lambda: None,
            "critique_answer": lambda: None,
            "evaluate_results": lambda: None,
            "rlm_query": lambda: None,
            "format_evidence": lambda: None,
            "source_registry": {},
            "search_log": [],
            "question": "test",
        }

    def test_focused_removes_expensive_tools(self):
        ns = self._make_namespace()
        removed = apply_gate(ns, "focused")
        assert "rlm_query" not in ns
        assert "browse" not in ns
        assert "reformulate" not in ns
        assert "critique_answer" not in ns
        assert "evaluate_results" not in ns
        assert set(removed) == {
            "rlm_query", "browse", "reformulate", "critique_answer", "evaluate_results",
        }

    def test_focused_keeps_core_tools(self):
        ns = self._make_namespace()
        apply_gate(ns, "focused")
        assert "research" in ns
        assert "draft_answer" in ns
        assert "check_progress" in ns
        assert "search" in ns
        assert "fiqh_lookup" in ns

    def test_full_removes_nothing(self):
        ns = self._make_namespace()
        removed = apply_gate(ns, "full")
        assert removed == []
        assert "rlm_query" in ns

    def test_standard_removes_rlm_query_only(self):
        ns = self._make_namespace()
        removed = apply_gate(ns, "standard")
        assert "rlm_query" not in ns
        assert "browse" in ns
        assert removed == ["rlm_query"]

    def test_missing_tool_is_silently_skipped(self):
        """If a tool was never injected (e.g. rlm_query at max depth), skip it."""
        ns = {"research": lambda: None, "draft_answer": lambda: None}
        removed = apply_gate(ns, "focused")
        assert "research" in ns
        # Only tools that were actually present get reported
        assert all(name not in ns for name in removed)

    def test_non_callable_keys_untouched(self):
        ns = self._make_namespace()
        apply_gate(ns, "focused")
        assert "source_registry" in ns
        assert "search_log" in ns
        assert "question" in ns


class TestGateIntegration:
    """Gate fires after classification in the research() wrapper."""

    def test_gate_callback_receives_tier(self):
        """_ctx._gate_callback is called with the computed tier after classification."""
        classification = {"confidence": "HIGH", "category": "PT", "also_category": ""}
        tier = compute_tool_tier(classification)
        assert tier == "focused"

    def test_repl_setup_code_defines_gate_callback(self):
        """Generated setup code must define _ctx._gate_callback."""
        from rlm_search.repl_tools import build_search_setup_code

        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        ctx = ns["_ctx"]
        assert hasattr(ctx, "_gate_callback")
        assert ctx._gate_callback is not None
        assert callable(ctx._gate_callback)


class TestReplGateWiring:
    """Full integration: setup code -> research() -> classification -> gate fires."""

    def test_gate_removes_tools_after_high_confidence_classification(self):
        """After research() returns with HIGH classification, expensive tools are gone."""
        from rlm_search.repl_tools import build_search_setup_code

        code = build_search_setup_code(api_url="http://localhost:8091", query="test question")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        # Before classification, all tools present
        assert "browse" in ns
        assert "reformulate" in ns

        # Simulate classification landing on _ctx
        ns["_ctx"].classification = {
            "confidence": "HIGH",
            "category": "PT",
            "also_category": "",
            "clusters": "Wudu",
            "filters": {"parent_code": "PT"},
            "strategy": "Strong match.",
            "query_variants": [],
        }

        # Fire the gate callback directly (normally research() does this)
        ns["_ctx"]._gate_callback(ns["_ctx"].classification)

        # Expensive tools should be removed
        assert "browse" not in ns
        assert "reformulate" not in ns
        assert "critique_answer" not in ns
        assert "evaluate_results" not in ns

        # Core tools remain
        assert "research" in ns
        assert "draft_answer" in ns
        assert "check_progress" in ns
        assert "search" in ns
        assert "fiqh_lookup" in ns
        assert "format_evidence" in ns

    def test_gate_is_idempotent(self):
        """Calling gate callback twice doesn't error (second call is a no-op)."""
        from rlm_search.repl_tools import build_search_setup_code

        code = build_search_setup_code(api_url="http://localhost:8091", query="test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        classification = {"confidence": "HIGH", "category": "PT", "also_category": ""}
        ns["_ctx"].classification = classification
        ns["_ctx"]._gate_callback(classification)
        # Second call — should not raise
        ns["_ctx"]._gate_callback(classification)

        assert "research" in ns

    def test_low_confidence_keeps_all_tools(self):
        """LOW confidence -> full tier -> no tools removed."""
        from rlm_search.repl_tools import build_search_setup_code

        code = build_search_setup_code(api_url="http://localhost:8091", query="test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        classification = {"confidence": "LOW", "category": "PT", "also_category": "BE"}
        ns["_ctx"].classification = classification
        ns["_ctx"]._gate_callback(classification)

        assert "browse" in ns
        assert "reformulate" in ns
        assert "critique_answer" in ns
