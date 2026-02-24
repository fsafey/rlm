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
