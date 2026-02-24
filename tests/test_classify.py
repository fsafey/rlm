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
