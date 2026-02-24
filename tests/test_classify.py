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
        result = _match_clusters("can I take a mortgage?", grouped)
        assert result[0] == "Banking Riba Operations"

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
        result = _match_clusters("how to perform ghusl", grouped)
        assert result[0] == "Ghusl"

    def test_fallback_to_top_by_count_when_no_matches(self):
        """When no tokens match, return top 2 clusters by document count."""
        grouped = [
            {"label": "Cluster A", "total_count": 50, "hits": [{"question": "unrelated topic alpha"}]},
            {"label": "Cluster B", "total_count": 200, "hits": [{"question": "unrelated topic beta"}]},
            {"label": "Cluster C", "total_count": 100, "hits": [{"question": "unrelated topic gamma"}]},
        ]
        result = _match_clusters("completely different query xyz", grouped)
        assert len(result) == 2
        assert result[0] == "Cluster B"  # highest count
        assert result[1] == "Cluster C"  # second highest

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
        result = _match_clusters("prayer question", grouped)
        assert len(result) <= 5

    def test_empty_grouped_results(self):
        """Empty grouped_results returns empty list."""
        result = _match_clusters("any question", [])
        assert result == []

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
        result = _match_clusters("is riba in mortgage", grouped)
        assert result[0] == "Riba in Transactions"


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

from rlm_search.tools.subagent_tools import init_classify
from rlm_search.tools.context import ToolContext


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

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_two_phase_sets_classification(self, mock_post, mock_get_client):
        """Phase 1 LLM → Phase 2 browse → Phase 3 match → ctx.classification set."""
        # Phase 1: LLM returns category
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN"
        mock_get_client.return_value = mock_client

        # Phase 2: browse returns grouped results
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
        mock_post.return_value = mock_resp

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "FN"
        assert "Banking Riba Operations" in ctx.classification["clusters"]
        assert ctx.classification["filters"] == {"parent_code": "FN"}

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_browse_failure_falls_back_to_category_only(self, mock_post, mock_get_client):
        """When browse() fails, classification still has category but empty clusters."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT"
        mock_get_client.return_value = mock_client

        # Browse fails
        mock_post.side_effect = Exception("connection refused")

        ctx = self._make_ctx()
        init_classify(ctx, "how to perform ghusl?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "PT"
        assert ctx.classification["filters"] == {"parent_code": "PT"}
        # Clusters empty because browse failed, but classification still valid
        assert ctx.classification["clusters"] == ""

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_llm_failure_sets_none(self, mock_get_client):
        """When Phase 1 LLM fails entirely, ctx.classification is None."""
        mock_get_client.side_effect = Exception("API key invalid")

        ctx = self._make_ctx()
        init_classify(ctx, "test question", model="test-model")

        assert ctx.classification is None
