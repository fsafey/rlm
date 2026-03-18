"""Tests for programmatic citation verification."""

from rlm_search.tools.composite_tools import _verify_citations


class TestVerifyCitations:
    def test_all_valid_citations(self):
        draft = "The ruling is X [Source: 123]. Also Y [Source: 456]."
        evidence_ids = {"123", "456", "789"}
        result = _verify_citations(draft, evidence_ids)
        assert result["valid"] is True
        assert result["fabricated"] == set()
        assert "789" in result["uncited"]

    def test_fabricated_citation(self):
        draft = "The ruling is X [Source: 999]."
        evidence_ids = {"123", "456"}
        result = _verify_citations(draft, evidence_ids)
        assert result["valid"] is False
        assert "999" in result["fabricated"]

    def test_no_citations_in_draft(self):
        draft = "The ruling is X with no citations."
        evidence_ids = {"123"}
        result = _verify_citations(draft, evidence_ids)
        assert result["valid"] is True  # no fabrication
        assert result["cited"] == set()
        assert result["uncited"] == {"123"}

    def test_whitespace_variations(self):
        """Handle [Source:123] and [Source: 123] and [Source:  123]."""
        draft = "A [Source:123] B [Source: 456] C [Source:  789]."
        evidence_ids = {"123", "456", "789"}
        result = _verify_citations(draft, evidence_ids)
        assert result["valid"] is True
        assert result["cited"] == {"123", "456", "789"}

    def test_duplicate_citations_counted_once(self):
        draft = "A [Source: 123] confirms B [Source: 123]."
        evidence_ids = {"123"}
        result = _verify_citations(draft, evidence_ids)
        assert result["valid"] is True
        assert result["cited"] == {"123"}

    def test_coverage_ratio(self):
        draft = "A [Source: 1] B [Source: 2]."
        evidence_ids = {"1", "2", "3", "4"}
        result = _verify_citations(draft, evidence_ids)
        assert result["coverage"] == 0.5  # 2 cited out of 4 evidence
