"""Tests for query diversity guard in search()."""

from rlm_search.tools.api_tools import _query_similarity


class TestQuerySimilarity:
    def test_identical_queries(self):
        assert _query_similarity("taqlid deceased marja", "taqlid deceased marja") == 1.0

    def test_completely_different(self):
        assert _query_similarity("prayer times calculation", "marriage contract conditions") < 0.2

    def test_near_duplicate(self):
        """Queries with same core terms in different order."""
        sim = _query_similarity(
            "continuing taqlid deceased marja ruling",
            "taqlid deceased marja acting on rulings",
        )
        assert sim > 0.3

    def test_empty_query(self):
        assert _query_similarity("", "anything") == 0.0

    def test_case_insensitive(self):
        assert _query_similarity("Taqlid Marja", "taqlid marja") == 1.0
