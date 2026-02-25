"""Tests for init_classify — single LLM call for category + cluster classification."""

from rlm_search.tools.subagent_tools import _build_category_prompt


class TestBuildCategoryPrompt:
    """Prompt includes category info with cluster labels and sample questions."""

    SAMPLE_KB = {
        "categories": {
            "PT": {"name": "Prayer & Tahara", "document_count": 4938},
            "FN": {"name": "Finance & Transactions", "document_count": 1891},
        }
    }

    KB_WITH_CLUSTERS = {
        "categories": {
            "FN": {
                "name": "Finance",
                "document_count": 100,
                "clusters": {
                    "Banking Riba Operations": "Is mortgage permissible?",
                    "Shariah Investment Screening": "How to screen funds?",
                },
                "facets": {
                    "subtopics": [{"value": "riba", "count": 80}],
                },
            },
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
        prompt = _build_category_prompt("test question", self.SAMPLE_KB)
        assert "CONFIDENCE: HIGH|MEDIUM|LOW" in prompt

    def test_includes_clusters_output_format(self):
        """Prompt must ask for CLUSTERS in the response format."""
        prompt = _build_category_prompt("test", self.SAMPLE_KB)
        assert "CLUSTERS:" in prompt

    def test_includes_cluster_labels_when_present(self):
        """Cluster labels from kb_overview_data appear in the prompt."""
        prompt = _build_category_prompt("test", self.KB_WITH_CLUSTERS)
        assert "Banking Riba Operations" in prompt
        assert "Shariah Investment Screening" in prompt

    def test_includes_sample_questions_for_grounding(self):
        """Sample questions from clusters appear in the prompt for semantic grounding."""
        prompt = _build_category_prompt("test", self.KB_WITH_CLUSTERS)
        assert "Is mortgage permissible?" in prompt
        assert "How to screen funds?" in prompt

    def test_no_clusters_when_absent_from_kb(self):
        """Categories without clusters don't show cluster lines."""
        prompt = _build_category_prompt("test", self.SAMPLE_KB)
        assert "Clusters:" not in prompt


from unittest.mock import MagicMock, patch

from rlm_search.tools.context import ToolContext
from rlm_search.tools.subagent_tools import init_classify


class TestInitClassify:
    """Integration: init_classify uses single LLM call for category + clusters."""

    def _make_ctx(self) -> ToolContext:
        ctx = ToolContext(api_url="http://test:8091")
        ctx.kb_overview_data = {
            "categories": {
                "FN": {
                    "name": "Finance & Transactions",
                    "document_count": 1891,
                    "clusters": {
                        "Banking Riba Operations": "Is mortgage permissible?",
                        "Shariah Investment Screening": "How to screen funds?",
                    },
                    "facets": {"subtopics": [{"value": "riba", "count": 80}]},
                },
                "PT": {
                    "name": "Prayer & Tahara",
                    "document_count": 4938,
                    "clusters": {
                        "Ghusl": "How to perform ghusl?",
                        "Wudu Ablution": "Steps of wudu?",
                    },
                    "facets": {"subtopics": [{"value": "purification", "count": 120}]},
                },
            }
        }
        ctx.llm_query = None
        ctx.llm_query_batched = None
        ctx._parent_logger = None
        return ctx

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_single_call_sets_classification(self, mock_get_client):
        """LLM returns category + clusters → ctx.classification set correctly."""
        mock_client = MagicMock()
        mock_client.completion.return_value = (
            "CATEGORY: FN\nCONFIDENCE: HIGH\nCLUSTERS: Banking Riba Operations"
        )
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "FN"
        assert ctx.classification["confidence"] == "HIGH"
        assert "Banking Riba Operations" in ctx.classification["clusters"]
        assert ctx.classification["filters"] == {"parent_code": "FN"}
        assert ctx.classification["strategy"]
        assert "FN" in ctx.classification["strategy"]

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_low_confidence_sets_broad_search_strategy(self, mock_get_client):
        """CONFIDENCE: LOW should produce a broad-search strategy."""
        mock_client = MagicMock()
        mock_client.completion.return_value = (
            "CATEGORY: FN\nCONFIDENCE: LOW\nCLUSTERS: Banking Riba Operations"
        )
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "can I use haram money for charity?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["confidence"] == "LOW"
        assert "broad search" in ctx.classification["strategy"].lower()
        assert "no filters" in ctx.classification["strategy"].lower()

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_missing_confidence_line_defaults_to_high(self, mock_get_client):
        """When LLM omits CONFIDENCE line, default to HIGH."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN\nCLUSTERS: Banking Riba Operations"
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["confidence"] == "HIGH"

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_no_clusters_in_response_sets_empty(self, mock_get_client):
        """When LLM returns CLUSTERS: NONE, classification has empty clusters."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT\nCONFIDENCE: HIGH\nCLUSTERS: NONE"
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "how to perform ghusl?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "PT"
        assert ctx.classification["clusters"] == ""
        assert "category only" in ctx.classification["strategy"].lower()

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_hallucinated_cluster_filtered_out(self, mock_get_client):
        """LLM-hallucinated cluster names are filtered, only valid ones kept."""
        mock_client = MagicMock()
        mock_client.completion.return_value = (
            "CATEGORY: FN\nCONFIDENCE: HIGH\n"
            "CLUSTERS: Banking Riba Operations, Totally Fake Cluster"
        )
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert "Banking Riba Operations" in ctx.classification["clusters"]
        assert "Totally Fake Cluster" not in ctx.classification["clusters"]

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_all_clusters_hallucinated_falls_back_to_no_cluster(self, mock_get_client):
        """When all LLM clusters are hallucinated, fall back to category-only."""
        mock_client = MagicMock()
        mock_client.completion.return_value = (
            "CATEGORY: FN\nCONFIDENCE: HIGH\nCLUSTERS: Fake One, Fake Two"
        )
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["clusters"] == ""
        assert "category only" in ctx.classification["strategy"].lower()

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_missing_clusters_line_sets_empty(self, mock_get_client):
        """When LLM omits CLUSTERS line entirely, classification has empty clusters."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN\nCONFIDENCE: HIGH"
        mock_get_client.return_value = mock_client

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["clusters"] == ""

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_llm_failure_sets_none(self, mock_get_client):
        """When LLM fails entirely, ctx.classification is None."""
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
        ctx = self._make_ctx_with_classification(
            "FN", "Banking Riba Operations, Riba in Loan Contracts", kb
        )
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
            "test",
            3,
            filters={"cluster_label": "Banking Riba Operations"},
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
