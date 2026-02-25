"""Tests for init_classify cluster matching logic."""

from rlm_search.tools.subagent_tools import _match_clusters


class TestMatchClusters:
    """Deterministic cluster matching from browse grouped_results."""

    def test_matches_query_tokens_in_sample_questions(self):
        """Query terms found in sample hit questions score those clusters higher."""
        grouped = [
            {
                "label": "Banking Riba Operations",
                "total_count": 150,
                "hits": [{"question": "Is it permissible to take a mortgage from a bank?"}],
            },
            {
                "label": "Shariah Investment Screening",
                "total_count": 80,
                "hits": [{"question": "How to screen halal investment funds?"}],
            },
        ]
        clusters, is_real = _match_clusters("can I take a mortgage?", grouped)
        assert clusters[0] == "Banking Riba Operations"
        assert is_real is True

    def test_matches_query_tokens_in_cluster_labels(self):
        """Query terms found in cluster labels score higher."""
        grouped = [
            {
                "label": "Ghusl",
                "total_count": 200,
                "hits": [{"question": "How to perform ghusl after janabah?"}],
            },
            {
                "label": "Wudu Ablution",
                "total_count": 300,
                "hits": [{"question": "Steps of ablution in Hanafi school"}],
            },
        ]
        clusters, is_real = _match_clusters("how to perform ghusl", grouped)
        assert clusters[0] == "Ghusl"
        assert is_real is True

    def test_fallback_to_top_by_count_when_no_matches(self):
        """When no tokens match, return top 2 clusters by document count."""
        grouped = [
            {"label": "Cluster A", "total_count": 50, "hits": [{"question": "unrelated topic alpha"}]},
            {"label": "Cluster B", "total_count": 200, "hits": [{"question": "unrelated topic beta"}]},
            {"label": "Cluster C", "total_count": 100, "hits": [{"question": "unrelated topic gamma"}]},
        ]
        clusters, is_real = _match_clusters("completely different query xyz", grouped)
        assert len(clusters) == 2
        assert clusters[0] == "Cluster B"  # highest count
        assert clusters[1] == "Cluster C"  # second highest
        assert is_real is False

    def test_stops_at_five_clusters_max(self):
        """Never return more than 5 matched clusters."""
        grouped = [
            {
                "label": f"Cluster {i}",
                "total_count": 100 - i,
                "hits": [{"question": f"prayer question variant {i}"}],
            }
            for i in range(10)
        ]
        clusters, is_real = _match_clusters("prayer question", grouped)
        assert len(clusters) <= 5
        assert is_real is True

    def test_empty_grouped_results(self):
        """Empty grouped_results returns empty list with is_real=False."""
        clusters, is_real = _match_clusters("any question", [])
        assert clusters == []
        assert is_real is False

    def test_ignores_stop_words(self):
        """Common stop words don't inflate scores."""
        grouped = [
            {
                "label": "Riba in Transactions",
                "total_count": 100,
                "hits": [{"question": "Is riba in all bank transactions?"}],
            },
            {
                "label": "General Fiqh",
                "total_count": 50,
                "hits": [{"question": "What is the ruling on this matter?"}],
            },
        ]
        # "is" and "in" are stop words — shouldn't boost "General Fiqh"
        clusters, is_real = _match_clusters("is riba in mortgage", grouped)
        assert clusters[0] == "Riba in Transactions"
        assert is_real is True


from rlm_search.tools.subagent_tools import _build_category_prompt


class TestBuildCategoryPrompt:
    """Phase 1 prompt: simple 6-way category classification."""

    SAMPLE_KB = {
        "categories": {
            "PT": {"name": "Prayer & Tahara", "document_count": 4938},
            "FN": {"name": "Finance & Transactions", "document_count": 1891},
        }
    }

    def test_includes_all_category_codes(self):
        prompt = _build_category_prompt("test question", self.SAMPLE_KB)
        assert "PT" in prompt
        assert "FN" in prompt

    def test_includes_doc_counts(self):
        prompt = _build_category_prompt("test question", self.SAMPLE_KB)
        assert "4938" in prompt
        assert "1891" in prompt

    def test_includes_question(self):
        prompt = _build_category_prompt("is mortgage halal?", self.SAMPLE_KB)
        assert "is mortgage halal?" in prompt

    def test_includes_confidence_output_format(self):
        """Phase 1 prompt must ask for CONFIDENCE: HIGH|MEDIUM|LOW."""
        prompt = _build_category_prompt("test question", self.SAMPLE_KB)
        assert "CONFIDENCE: HIGH|MEDIUM|LOW" in prompt

    def test_does_not_include_cluster_labels(self):
        """Phase 1 prompt must NOT include cluster labels — that's Phase 3's job."""
        kb_with_clusters = {
            "categories": {
                "FN": {
                    "name": "Finance",
                    "document_count": 100,
                    "clusters": {"Banking Riba Operations": "sample"},
                    "facets": {"clusters": [{"value": "Banking Riba Operations", "count": 50}]},
                },
            }
        }
        prompt = _build_category_prompt("test", kb_with_clusters)
        assert "Banking Riba Operations" not in prompt

    def test_output_format_instruction(self):
        prompt = _build_category_prompt("test", self.SAMPLE_KB)
        assert "CATEGORY:" in prompt
        # Must NOT ask for CLUSTERS, FILTERS, or STRATEGY
        assert "CLUSTERS:" not in prompt.split("Respond")[1]  # not in the response format section


from unittest.mock import MagicMock, patch

from rlm_search.tools.context import ToolContext
from rlm_search.tools.subagent_tools import init_classify


class TestInitClassifyTwoPhase:
    """Integration: init_classify uses Phase 1 (LLM) + Phase 2 (browse) + Phase 3 (match)."""

    def _make_ctx(self) -> ToolContext:
        ctx = ToolContext(api_url="http://test:8091")
        ctx.kb_overview_data = {
            "categories": {
                "FN": {"name": "Finance & Transactions", "document_count": 1891},
                "PT": {"name": "Prayer & Tahara", "document_count": 4938},
            }
        }
        ctx.llm_query = None
        ctx.llm_query_batched = None
        ctx._parent_logger = None
        return ctx

    def _make_browse_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": [],
            "total": 1891,
            "has_more": False,
            "facets": {
                "clusters": [
                    {"value": "Banking Riba Operations", "count": 150},
                    {"value": "Shariah Investment Screening", "count": 80},
                ],
                "subtopics": [{"value": "riba", "count": 80}],
            },
            "grouped_results": {
                "clusters": [
                    {
                        "label": "Banking Riba Operations",
                        "total_count": 150,
                        "hits": [{"id": "1", "question": "Is mortgage permissible in Islam?", "answer": "..."}],
                    },
                    {
                        "label": "Shariah Investment Screening",
                        "total_count": 80,
                        "hits": [{"id": "2", "question": "How to screen halal funds?", "answer": "..."}],
                    },
                ]
            },
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_two_phase_sets_classification(self, mock_post, mock_get_client):
        """Phase 1 LLM → Phase 2 browse → Phase 3 match → ctx.classification set."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN\nCONFIDENCE: HIGH"
        mock_get_client.return_value = mock_client
        mock_post.return_value = self._make_browse_response()

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "FN"
        assert ctx.classification["confidence"] == "HIGH"
        assert "Banking Riba Operations" in ctx.classification["clusters"]
        assert ctx.classification["filters"] == {"parent_code": "FN"}
        # Strategy is non-empty and references the category
        assert ctx.classification["strategy"]
        assert "FN" in ctx.classification["strategy"]

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_low_confidence_sets_broad_search_strategy(self, mock_post, mock_get_client):
        """CONFIDENCE: LOW should produce a broad-search strategy."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN\nCONFIDENCE: LOW"
        mock_get_client.return_value = mock_client
        mock_post.return_value = self._make_browse_response()

        ctx = self._make_ctx()
        init_classify(ctx, "can I use haram money for charity?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["confidence"] == "LOW"
        assert "broad search" in ctx.classification["strategy"].lower()
        assert "no filters" in ctx.classification["strategy"].lower()

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_missing_confidence_line_defaults_to_high(self, mock_post, mock_get_client):
        """When LLM omits CONFIDENCE line, default to HIGH."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN"  # no CONFIDENCE line
        mock_get_client.return_value = mock_client
        mock_post.return_value = self._make_browse_response()

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["confidence"] == "HIGH"

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_browse_failure_falls_back_to_category_only(self, mock_post, mock_get_client):
        """When browse() fails, classification still has category but empty clusters."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT\nCONFIDENCE: HIGH"
        mock_get_client.return_value = mock_client
        mock_post.side_effect = Exception("connection refused")

        ctx = self._make_ctx()
        init_classify(ctx, "how to perform ghusl?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "PT"
        assert ctx.classification["filters"] == {"parent_code": "PT"}
        assert ctx.classification["clusters"] == ""

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_llm_failure_sets_none(self, mock_get_client):
        """When Phase 1 LLM fails entirely, ctx.classification is None."""
        mock_get_client.side_effect = Exception("API key invalid")

        ctx = self._make_ctx()
        init_classify(ctx, "test question", model="test-model")

        assert ctx.classification is None


from rlm_search.tools.progress_tools import _suggest_strategy


class TestSuggestStrategyWithBrowseClusters:
    """Verify _suggest_strategy works with browse-enhanced classification."""

    def _make_ctx_with_classification(self, category, clusters_str, kb_data, confidence="HIGH"):
        ctx = ToolContext(api_url="http://test:8091")
        ctx.kb_overview_data = kb_data
        ctx.classification = {
            "category": category,
            "confidence": confidence,
            "clusters": clusters_str,
            "filters": {"parent_code": category},
            "strategy": "Browse-matched clusters",
        }
        return ctx

    def test_suggests_first_unsearched_classified_cluster(self):
        kb = {
            "categories": {
                "FN": {
                    "name": "Finance & Transactions",
                    "document_count": 1891,
                    "facets": {"clusters": [{"value": "Banking Riba Operations", "count": 150}]},
                },
            }
        }
        ctx = self._make_ctx_with_classification("FN", "Banking Riba Operations, Riba in Loan Contracts", kb)
        result = _suggest_strategy(ctx, set())
        assert "Banking Riba Operations" in result
        assert "research(query" in result

    def test_low_confidence_bypasses_cluster_suggestion(self):
        """LOW confidence should skip cluster suggestion and return broad-search strategy."""
        kb = {
            "categories": {
                "FN": {
                    "name": "Finance & Transactions",
                    "document_count": 1891,
                    "facets": {"clusters": []},
                },
            }
        }
        ctx = self._make_ctx_with_classification(
            "FN",
            "Banking Riba Operations",
            kb,
            confidence="LOW",
        )
        ctx.classification["strategy"] = (
            "Low category confidence — start with broad search (no filters). "
            "Add category filter only if initial results confirm this category."
        )
        result = _suggest_strategy(ctx, set())
        # Should return the strategy string, NOT a cluster filter suggestion
        assert "broad search" in result.lower()
        assert "cluster_label" not in result

    def test_returns_strategy_when_all_clusters_explored(self):
        kb = {
            "categories": {
                "FN": {
                    "name": "Finance & Transactions",
                    "document_count": 1891,
                    "facets": {"clusters": []},
                },
            }
        }
        ctx = self._make_ctx_with_classification("FN", "Banking Riba Operations", kb)
        ctx.evidence.log_search(
            "test", 3, filters={"cluster_label": "Banking Riba Operations"},
            search_type="search_multi",
        )
        result = _suggest_strategy(ctx, set())
        assert "Browse-matched clusters" in result


from rlm_search.tools.context import ToolContext as _ToolContext
from rlm_search.tools.subagent_tools import critique_answer


class TestCritiqueAnswerEvidence:
    """Evidence-grounded critique tests."""

    def _make_ctx(self) -> _ToolContext:
        ctx = _ToolContext(api_url="http://test:8091")
        ctx.llm_query = None
        ctx.llm_query_batched = None
        ctx._parent_logger = None
        return ctx

    def test_critique_with_evidence_passes_valid_draft(self):
        """Draft citing real source IDs from evidence should PASS."""
        ctx = self._make_ctx()
        ctx.llm_query = lambda prompt, model=None: "PASS\nAll citations verified against evidence."
        evidence = [
            "[Source: 101] Q: Is mortgage halal? A: Majority view is it is not permissible.",
            "[Source: 102] Q: Riba in banking A: Riba is strictly prohibited.",
        ]
        draft = (
            "Mortgage is not permissible according to the majority [Source: 101]. "
            "Riba is prohibited [Source: 102]."
        )
        verdict, passed = critique_answer(ctx, "Is mortgage halal?", draft, evidence=evidence)
        assert passed is True
        assert "PASS" in verdict

    def test_critique_catches_fabricated_citation(self):
        """Draft citing a source ID not in evidence should FAIL."""
        ctx = self._make_ctx()
        ctx.llm_query = lambda prompt, model=None: (
            "FAIL\n[Source: 999] does not appear in the evidence. Fabricated citation."
        )
        evidence = [
            "[Source: 101] Q: Is mortgage halal? A: Majority view is not permissible.",
        ]
        draft = "Mortgage is haram [Source: 101] and also per [Source: 999]."
        verdict, passed = critique_answer(ctx, "Is mortgage halal?", draft, evidence=evidence)
        assert passed is False
        assert "FAIL" in verdict

    def test_critique_without_evidence_uses_generic_prompt(self):
        """Without evidence, falls back to generic review (no evidence block)."""
        prompts_seen: list[str] = []

        def capture_prompt(prompt, model=None):
            prompts_seen.append(prompt)
            return "PASS\nLooks reasonable."

        ctx = self._make_ctx()
        ctx.llm_query = capture_prompt
        verdict, passed = critique_answer(ctx, "test question", "test draft", evidence=None)
        assert passed is True
        assert "EVIDENCE:" not in prompts_seen[0]
        assert "Does it answer the actual question" in prompts_seen[0]

    def test_critique_with_evidence_includes_evidence_in_prompt(self):
        """When evidence provided, the prompt must include the evidence block."""
        prompts_seen: list[str] = []

        def capture_prompt(prompt, model=None):
            prompts_seen.append(prompt)
            return "PASS\nOK"

        ctx = self._make_ctx()
        ctx.llm_query = capture_prompt
        evidence = ["[Source: 1] Q: Test A: Answer"]
        critique_answer(ctx, "question", "draft [Source: 1]", evidence=evidence)
        assert "EVIDENCE:" in prompts_seen[0]
        assert "CITATION ACCURACY" in prompts_seen[0]
        assert "ATTRIBUTION FIDELITY" in prompts_seen[0]
        assert "[Source: 1] Q: Test A: Answer" in prompts_seen[0]

    def test_evidence_path_criterion5_includes_declarative_register(self):
        """Critic criterion 5 (evidence path) must check for tentative framing."""
        prompts_seen: list[str] = []

        def capture_prompt(prompt, model=None):
            prompts_seen.append(prompt)
            return "PASS\nOK"

        ctx = self._make_ctx()
        ctx.llm_query = capture_prompt
        evidence = ["[Source: 1] Q: Test A: Answer"]
        critique_answer(ctx, "question", "draft [Source: 1]", evidence=evidence)
        assert "declaratively" in prompts_seen[0]
        assert "tentatively" in prompts_seen[0]

    def test_fallback_path_criterion5_includes_declarative_register(self):
        """Critic criterion 5 (no-evidence fallback) must also check declarative register."""
        prompts_seen: list[str] = []

        def capture_prompt(prompt, model=None):
            prompts_seen.append(prompt)
            return "PASS\nOK"

        ctx = self._make_ctx()
        ctx.llm_query = capture_prompt
        critique_answer(ctx, "test question", "test draft", evidence=None)
        assert "declaratively" in prompts_seen[0]
        assert "tentatively" in prompts_seen[0]
