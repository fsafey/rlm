"""Tests for progressive quality gate in research().

Verifies that research() stops searching early when:
1. Saturation: consecutive searches yield no new unique results
2. Strong tier: 6+ RELEVANT evidence accumulated
3. Medium tier: 3+ RELEVANT evidence, capped at MEDIUM_EXTRA_BUDGET more searches
4. Checkpoint evaluation: evaluate_results runs at search 1 and search 3

All tests mock search() and evaluate_results() to avoid real API/LLM calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rlm_search.tools.context import SearchContext


def _make_ctx(api_url: str = "http://test:8095") -> SearchContext:
    """Build a minimal SearchContext with mocked LLM callables."""
    ctx = SearchContext(api_url=api_url)
    ctx.llm_query = MagicMock(return_value="mocked")
    ctx.llm_query_batched = MagicMock(return_value=["mocked"])
    return ctx


def _seed_evidence(ctx: SearchContext, ids: list[int], score: float = 0.8) -> None:
    """Pre-seed EvidenceStore with hits + search log entries.

    This is needed because mocked search() bypasses normalize_hit(),
    which normally populates evidence._registry. Without seeding,
    QualityGate.confidence stays low (quality_score=0, breadth_score=0)
    and strong tier (requires confidence >= 50) is unreachable.
    """
    for i in ids:
        ctx.evidence.register_hit(
            {"id": str(i), "question": f"Q{i}", "answer": f"A{i}",
             "score": score, "metadata": {"primary_topic": f"topic_{i}"}}
        )
    ctx.evidence.log_search(query="seeded", num_results=len(ids))


def _make_results(ids: list[int], score: float = 0.8) -> dict:
    """Build a mock search() return dict."""
    return {
        "results": [
            {
                "id": str(i),
                "question": f"Q{i}",
                "answer": f"A{i}",
                "score": score,
                "metadata": {"primary_topic": f"topic_{i}", "parent_code": "PT"},
            }
            for i in ids
        ]
    }


def _make_eval_ratings(ids: list[int], rating: str = "RELEVANT") -> dict:
    """Build a mock evaluate_results() return dict."""
    return {
        "ratings": [
            {"id": str(i), "rating": rating, "confidence": 4}
            for i in ids
        ],
        "suggestion": "Proceed to synthesis",
        "raw": "mocked",
    }


# ── Saturation Detection ──


class TestSaturationDetection:
    """research() should stop issuing extra_queries when results saturate."""

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_stops_after_consecutive_low_yield(self, mock_search, mock_eval):
        """If 2 consecutive searches return ≤1 new unique result, stop."""
        ctx = _make_ctx()
        # Main query returns ids 1-5
        # Extra query 1 returns same ids 1-5 (0 new) — low yield 1
        # Extra query 2 returns same ids 1-5 (0 new) — low yield 2 → STOP
        # Extra query 3 should NOT be called
        mock_search.side_effect = [
            _make_results([1, 2, 3, 4, 5]),    # main query
            _make_results([1, 2, 3, 4, 5]),    # extra 1: 0 new
            _make_results([1, 2, 3, 4, 5]),    # extra 2: 0 new → stop
            _make_results([6, 7, 8, 9, 10]),   # extra 3: should not reach
        ]
        mock_eval.return_value = _make_eval_ratings([1, 2, 3, 4, 5], "PARTIAL")

        result = research(
            ctx,
            "test query",
            extra_queries=[
                {"query": "variant 1"},
                {"query": "variant 2"},
                {"query": "variant 3"},
            ],
        )

        # Should have called search 3 times (main + 2 extras), NOT 4
        assert mock_search.call_count == 3
        assert result["search_count"] == 3

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_resets_low_yield_on_novel_results(self, mock_search, mock_eval):
        """A search with >1 new results resets the consecutive counter."""
        ctx = _make_ctx()
        mock_search.side_effect = [
            _make_results([1, 2, 3]),          # main: 3 new
            _make_results([1, 2, 3]),          # extra 1: 0 new — low yield 1
            _make_results([4, 5, 6]),          # extra 2: 3 new — reset!
            _make_results([4, 5, 6]),          # extra 3: 0 new — low yield 1
            _make_results([4, 5, 6]),          # extra 4: 0 new — low yield 2 → stop
            _make_results([7, 8, 9]),          # extra 5: should not reach
        ]
        mock_eval.return_value = _make_eval_ratings([1, 2, 3], "PARTIAL")

        result = research(
            ctx,
            "test query",
            extra_queries=[
                {"query": f"variant {i}"} for i in range(5)
            ],
        )

        assert mock_search.call_count == 5
        assert result["search_count"] == 5


# ── Tier-Based Gating ──


class TestTierGating:
    """research() should stop or cap searches based on critique tier."""

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_stops_on_strong_tier(self, mock_search, mock_eval):
        """When evaluation yields 6+ RELEVANT (strong tier), stop searching."""
        ctx = _make_ctx()
        # Pre-seed evidence so QualityGate.confidence can reach 50+
        # (quality_score from registry + breadth from search_log)
        _seed_evidence(ctx, list(range(1, 9)), score=0.85)
        # Main query returns 8 results, all rated RELEVANT → strong tier
        mock_search.side_effect = [
            _make_results(list(range(1, 9)), score=0.85),  # main: 8 results
            _make_results([9, 10]),                        # should not reach
        ]
        mock_eval.return_value = _make_eval_ratings(list(range(1, 9)), "RELEVANT")

        result = research(
            ctx,
            "test query",
            extra_queries=[{"query": "should not run"}],
        )

        assert mock_search.call_count == 1  # only main query ran
        assert result["search_count"] == 1

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_caps_extras_on_medium_tier(self, mock_search, mock_eval):
        """When medium tier reached, allow at most MEDIUM_EXTRA_BUDGET more searches."""
        ctx = _make_ctx()
        # Main query returns 4 RELEVANT → medium tier
        # Should allow 2 more extras (MEDIUM_EXTRA_BUDGET=2), then stop
        mock_search.side_effect = [
            _make_results([1, 2, 3, 4], score=0.7),      # main: medium tier
            _make_results([5, 6]),                        # extra 1: budget 1
            _make_results([7, 8]),                        # extra 2: budget 2 → stop
            _make_results([9, 10]),                       # extra 3: should not reach
            _make_results([11, 12]),                      # extra 4: should not reach
        ]
        # Use return_value (not side_effect) — safe for all _incremental_evaluate
        # calls including the final post-loop one
        mock_eval.return_value = _make_eval_ratings([1, 2, 3, 4], "RELEVANT")

        result = research(
            ctx,
            "test query",
            extra_queries=[{"query": f"v{i}"} for i in range(4)],
        )

        # main + 2 extras = 3 total
        assert mock_search.call_count == 3
        assert result["search_count"] == 3

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_weak_tier_runs_all_extras(self, mock_search, mock_eval):
        """Weak tier: no gating, all extra_queries run (current behavior)."""
        ctx = _make_ctx()
        mock_search.side_effect = [
            _make_results([1], score=0.5),
            _make_results([2], score=0.5),
            _make_results([3], score=0.5),
        ]
        # Only 1 RELEVANT + 0 others = weak tier
        mock_eval.return_value = _make_eval_ratings([1], "PARTIAL")

        result = research(
            ctx,
            "test query",
            extra_queries=[{"query": "v1"}, {"query": "v2"}],
        )

        assert mock_search.call_count == 3
        assert result["search_count"] == 3


# ── Checkpoint Evaluation ──


class TestCheckpointEvaluation:
    """evaluate_results should run at checkpoints, not just at the end."""

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_evaluates_after_main_query(self, mock_search, mock_eval):
        """First evaluation happens after main query (search 1), not deferred."""
        ctx = _make_ctx()
        mock_search.side_effect = [
            _make_results([1, 2, 3]),
            _make_results([4, 5]),
        ]
        mock_eval.return_value = _make_eval_ratings([1, 2, 3], "PARTIAL")

        research(ctx, "test query", extra_queries=[{"query": "v1"}])

        # evaluate_results should have been called (at least once after main query)
        assert mock_eval.call_count >= 1

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_evaluates_at_search_3_checkpoint(self, mock_search, mock_eval):
        """Second evaluation checkpoint at search 3."""
        ctx = _make_ctx()
        mock_search.side_effect = [
            _make_results([1, 2]),          # search 1
            _make_results([3, 4]),          # search 2
            _make_results([5, 6]),          # search 3 → checkpoint
            _make_results([7, 8]),          # search 4
        ]
        mock_eval.return_value = _make_eval_ratings([1, 2], "PARTIAL")

        research(
            ctx,
            "test query",
            extra_queries=[{"query": f"v{i}"} for i in range(3)],
        )

        # Should have at least 2 evaluate calls: after search 1, after search 3
        assert mock_eval.call_count >= 2

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_final_evaluate_catches_stragglers(self, mock_search, mock_eval):
        """Unevaluated results after loop still get evaluated."""
        ctx = _make_ctx()
        mock_search.side_effect = [
            _make_results([1, 2]),          # search 1: evaluated at checkpoint
            _make_results([3, 4]),          # search 2: unevaluated
        ]
        mock_eval.return_value = _make_eval_ratings([1, 2], "PARTIAL")

        result = research(ctx, "test query", extra_queries=[{"query": "v1"}])

        # Final eval should cover ids 3,4 that weren't in the checkpoint batch
        # Result should contain filtered results from all searches
        assert len(result["results"]) > 0


# ── Integration: Gate + Novelty + Checkpoint Combined ──


class TestIntegration:
    """Combined behavior: novelty tracking + tier gating + checkpoints."""

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_strong_tier_at_checkpoint_stops_remaining_extras(
        self, mock_search, mock_eval
    ):
        """If checkpoint eval reaches strong tier, remaining extras are skipped."""
        ctx = _make_ctx()
        # NO pre-seeding — let evidence accumulate naturally across searches.
        # Use side_effect so mock only rates what's actually passed (prevents
        # leaking ratings for IDs not yet searched).
        mock_search.side_effect = [
            _make_results(list(range(1, 5)), score=0.9),     # search 1: 4 results
            _make_results(list(range(5, 9)), score=0.9),     # search 2: 4 new
            _make_results(list(range(9, 12)), score=0.9),    # search 3: 3 new → checkpoint
            _make_results([20, 21]),                          # should not reach
        ]
        mock_eval.side_effect = lambda ctx, q, results, **kw: _make_eval_ratings(
            [int(r["id"]) for r in results], "RELEVANT"
        )

        result = research(
            ctx,
            "test query",
            extra_queries=[{"query": f"v{i}"} for i in range(5)],
        )

        # search 1 (main) → medium (4 RELEVANT, conf ~57)
        # search 2 (extra 1) → still medium (budget 2→1, no checkpoint yet)
        # search 3 (extra 2) → checkpoint fires, 11 RELEVANT → strong
        # search 4 (extra 3) → gate check: strong → stop
        assert mock_search.call_count == 3
        assert result["search_count"] == 3


# Import research at module level — after all helper definitions
from rlm_search.tools.composite_tools import research  # noqa: E402
