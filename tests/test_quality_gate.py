"""tests/test_quality_gate.py"""

from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate


def test_explore_constants_exist():
    """All explore constants are importable and have expected types."""
    from rlm_search.prompt_constants import (
        EXPLORE_EXTRA_BUDGET,
        EXPLORE_MIN_SEARCHES,
        EXPLORE_SATURATION_THRESHOLD,
        VELOCITY_DECAY,
        VELOCITY_SATURATE,
    )

    assert isinstance(EXPLORE_SATURATION_THRESHOLD, int)
    assert isinstance(EXPLORE_MIN_SEARCHES, int)
    assert isinstance(VELOCITY_DECAY, float)
    assert isinstance(VELOCITY_SATURATE, float)
    assert isinstance(EXPLORE_EXTRA_BUDGET, int)


class TestQualityGateConfidence:
    def test_initial_confidence_is_zero(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.confidence == 0

    def test_confidence_increases_with_relevant_hits(self):
        evidence = EvidenceStore()
        for i in range(5):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.8, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=4)
        gate = QualityGate(evidence=evidence)
        assert gate.confidence > 0

    def test_confidence_includes_critique_outcome(self):
        evidence = EvidenceStore()
        for i in range(3):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.8, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=4)
        gate = QualityGate(evidence=evidence)
        conf_before = gate.confidence
        gate.record_critique(passed=True, verdict="All claims grounded")
        assert gate.confidence > conf_before


class TestQualityGatePhase:
    def test_phase_ready_above_threshold(self):
        evidence = EvidenceStore()
        # Load enough relevant evidence to cross threshold
        for i in range(8):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.9, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=5)
        gate = QualityGate(evidence=evidence)
        gate.record_draft(length=500)
        gate.record_critique(passed=True, verdict="PASS")
        assert gate.phase in ("ready", "finalize")

    def test_phase_continue_below_threshold(self):
        evidence = EvidenceStore()
        evidence.register_hit(
            {"id": "h0", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
        )
        evidence.set_rating("h0", "PARTIAL", confidence=2)
        gate = QualityGate(evidence=evidence)
        assert gate.phase == "continue"

    def test_phase_stalled_many_searches_few_relevant(self):
        evidence = EvidenceStore()
        for i in range(7):
            evidence.log_search(query=f"q{i}", num_results=0)
        gate = QualityGate(evidence=evidence)
        assert gate.phase == "stalled"


class TestQualityGateCritique:
    def test_record_critique_stores_verdict(self):
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_critique(passed=True, verdict="PASS -- all grounded")
        assert gate.last_critique["passed"] is True
        assert "PASS" in gate.last_critique["verdict"]

    def test_no_critique_returns_none(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.last_critique is None


class TestQualityGateDraft:
    def test_record_draft(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert not gate.has_draft
        gate.record_draft(length=1200)
        assert gate.has_draft

    def test_draft_length_tracked(self):
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_draft(length=1200)
        assert gate.draft_length == 1200


class TestQualityGateThresholds:
    def test_ready_threshold_is_accessible(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.READY_THRESHOLD == 60

    def test_stall_threshold_is_accessible(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.STALL_SEARCH_COUNT == 6


class TestCritiqueTier:
    def test_strong_tier_many_relevant_high_confidence(self):
        evidence = EvidenceStore()
        for i in range(8):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.85, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=4)
        gate = QualityGate(evidence=evidence)
        assert gate.critique_tier == "strong"

    def test_medium_tier_moderate_relevant(self):
        evidence = EvidenceStore()
        for i in range(4):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=3)
        gate = QualityGate(evidence=evidence)
        assert gate.critique_tier == "medium"

    def test_weak_tier_few_relevant(self):
        evidence = EvidenceStore()
        evidence.register_hit(
            {"id": "h0", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
        )
        evidence.set_rating("h0", "RELEVANT", confidence=2)
        gate = QualityGate(evidence=evidence)
        assert gate.critique_tier == "weak"

    def test_weak_tier_no_relevant(self):
        evidence = EvidenceStore()
        for i in range(5):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.6, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "PARTIAL", confidence=3)
        gate = QualityGate(evidence=evidence)
        assert gate.critique_tier == "weak"

    def test_strong_requires_both_relevant_and_confidence(self):
        """6+ RELEVANT but low search scores => confidence below 75 => medium tier."""
        evidence = EvidenceStore()
        for i in range(7):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.3, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=2)
        gate = QualityGate(evidence=evidence)
        # relevance=35, quality=7, breadth=0 => confidence=42 < 75
        assert gate.critique_tier == "medium"


class TestExploreState:
    def test_record_search_yield_appends(self):
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_search_yield(5)
        gate.record_search_yield(3)
        assert gate._search_yields == [5.0, 3.0]

    def test_explore_graduated_default_false(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate._explore_graduated is False

    def test_info_velocity_no_yields_returns_1(self):
        """No search data → assume high velocity (keep exploring)."""
        gate = QualityGate(evidence=EvidenceStore())
        assert gate._info_velocity == 1.0

    def test_info_velocity_high_yields(self):
        """Many new IDs per search → high velocity."""
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_search_yield(8)
        gate.record_search_yield(7)
        assert gate._info_velocity > 0.8

    def test_info_velocity_zero_yields(self):
        """Zero new IDs → velocity near zero."""
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        assert gate._info_velocity < 0.1

    def test_info_velocity_decaying(self):
        """Recent low yields weigh more than early high yields."""
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_search_yield(10)  # early: high
        gate.record_search_yield(0)  # recent: zero
        gate.record_search_yield(0)  # recent: zero
        # Velocity should be low because recent searches are unproductive
        assert gate._info_velocity < 0.5

    def test_saturation_score_zero_initially(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.saturation_score == 0

    def test_saturation_score_rises_with_low_velocity(self):
        """When searches stop finding new things, saturation rises."""
        evidence = EvidenceStore()
        for i in range(4):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=3)
            evidence.log_search(query=f"q{i}", num_results=3)
        gate = QualityGate(evidence=evidence)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        assert gate.saturation_score > 50

    def test_saturation_score_low_with_high_velocity(self):
        """When searches keep finding new things, saturation stays low."""
        evidence = EvidenceStore()
        evidence.log_search(query="q1", num_results=5)
        evidence.log_search(query="q2", num_results=5)
        gate = QualityGate(evidence=evidence)
        gate.record_search_yield(8)
        gate.record_search_yield(7)
        assert gate.saturation_score < 40


class TestExplorePhase:
    def test_initial_phase_is_explore(self):
        """Fresh gate with some searches but no velocity data → explore."""
        evidence = EvidenceStore()
        evidence.log_search(query="q1", num_results=5)
        gate = QualityGate(evidence=evidence)
        assert gate.phase == "explore"

    def test_explore_graduates_on_saturation(self):
        """Once saturation >= threshold, phase transitions to continue."""
        evidence = EvidenceStore()
        for i in range(4):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=3)
            evidence.log_search(query=f"q{i}", num_results=3)
        gate = QualityGate(evidence=evidence)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        assert gate.phase != "explore"

    def test_graduation_is_irreversible(self):
        """Once graduated from explore, can't go back even if saturation drops."""
        evidence = EvidenceStore()
        for i in range(4):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=3)
            evidence.log_search(query=f"q{i}", num_results=3)
        gate = QualityGate(evidence=evidence)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        _ = gate.phase  # triggers graduation
        assert gate._explore_graduated is True
        gate.record_search_yield(10)
        gate.record_search_yield(10)
        assert gate.phase != "explore"

    def test_stalled_overrides_explore(self):
        """Stalled takes priority: 6+ searches with <2 relevant → stalled, not explore."""
        evidence = EvidenceStore()
        for i in range(7):
            evidence.log_search(query=f"q{i}", num_results=0)
        gate = QualityGate(evidence=evidence)
        assert gate.phase == "stalled"

    def test_empty_gate_is_not_explore(self):
        """Zero searches → phase should not be explore. It should be continue."""
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.phase == "continue"

    def test_explore_guidance_says_dont_draft(self):
        """During explore, guidance should discourage drafting."""
        evidence = EvidenceStore()
        evidence.log_search(query="q1", num_results=5)
        gate = QualityGate(evidence=evidence)
        assert gate.phase == "explore"
        guidance = gate.guidance()
        assert "Do NOT draft" in guidance or "Do not draft" in guidance

    def test_explore_guidance_includes_saturation(self):
        evidence = EvidenceStore()
        evidence.log_search(query="q1", num_results=5)
        gate = QualityGate(evidence=evidence)
        guidance = gate.guidance()
        assert "saturation" in guidance.lower() or "%" in guidance
