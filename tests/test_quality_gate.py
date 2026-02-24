"""tests/test_quality_gate.py"""

from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate


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
