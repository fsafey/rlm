"""Tests for tool gating by classification confidence."""

from rlm_search.tool_gate import compute_tool_tier, TIER_REMOVALS


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
