"""tests/test_evidence_store.py"""

from rlm_search.evidence import EvidenceStore


class TestEvidenceStoreRegistration:
    def test_register_hit_returns_id(self):
        store = EvidenceStore()
        hit = {
            "id": "abc123",
            "question": "What is zakat?",
            "answer": "Zakat is...",
            "score": 0.85,
            "metadata": {"topic": "finance"},
        }
        hit_id = store.register_hit(hit)
        assert hit_id == "abc123"
        assert store.get(hit_id)["question"] == "What is zakat?"

    def test_register_hit_deduplicates(self):
        store = EvidenceStore()
        hit = {"id": "abc123", "question": "Q", "answer": "A", "score": 0.85, "metadata": {}}
        store.register_hit(hit)
        store.register_hit(hit)  # same id
        assert store.count == 1

    def test_register_hit_updates_higher_score(self):
        store = EvidenceStore()
        store.register_hit(
            {"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
        )
        store.register_hit(
            {"id": "x", "question": "Q", "answer": "A", "score": 0.9, "metadata": {}}
        )
        assert store.get("x")["score"] == 0.9


class TestEvidenceStoreSearchLog:
    def test_log_search(self):
        store = EvidenceStore()
        store.log_search(query="test query", num_results=5, filters={"topic": "finance"})
        assert len(store.search_log) == 1
        assert store.search_log[0]["query"] == "test query"
        assert store.search_log[0]["num_results"] == 5

    def test_log_search_appends(self):
        store = EvidenceStore()
        store.log_search(query="q1", num_results=3)
        store.log_search(query="q2", num_results=7)
        assert len(store.search_log) == 2


class TestEvidenceStoreRatings:
    def test_set_and_get_rating(self):
        store = EvidenceStore()
        store.register_hit(
            {"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
        )
        store.set_rating("x", "RELEVANT", confidence=4)
        assert store.get_rating("x") == {"rating": "RELEVANT", "confidence": 4}

    def test_get_rating_unrated_returns_none(self):
        store = EvidenceStore()
        assert store.get_rating("nonexistent") is None

    def test_rated_count(self):
        store = EvidenceStore()
        for i in range(5):
            store.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
            )
        store.set_rating("h0", "RELEVANT", confidence=4)
        store.set_rating("h1", "PARTIAL", confidence=2)
        store.set_rating("h2", "OFF-TOPIC", confidence=5)
        counts = store.rating_counts()
        assert counts == {"RELEVANT": 1, "PARTIAL": 1, "OFF-TOPIC": 1}


class TestEvidenceStoreMerge:
    def test_merge_child_sources(self):
        parent = EvidenceStore()
        parent.register_hit(
            {"id": "p1", "question": "Q1", "answer": "A1", "score": 0.8, "metadata": {}}
        )

        child = EvidenceStore()
        child.register_hit(
            {"id": "c1", "question": "Q2", "answer": "A2", "score": 0.7, "metadata": {}}
        )
        child.register_hit(
            {"id": "p1", "question": "Q1", "answer": "A1", "score": 0.9, "metadata": {}}
        )

        parent.merge(child)
        assert parent.count == 2  # p1 + c1
        assert parent.get("p1")["score"] == 0.9  # child had higher score
        assert parent.get("c1") is not None


class TestEvidenceStoreEvidence:
    def test_get_evidence_for_ids(self):
        store = EvidenceStore()
        store.register_hit(
            {"id": "a", "question": "Q1", "answer": "A1", "score": 0.9, "metadata": {}}
        )
        store.register_hit(
            {"id": "b", "question": "Q2", "answer": "A2", "score": 0.8, "metadata": {}}
        )
        store.register_hit(
            {"id": "c", "question": "Q3", "answer": "A3", "score": 0.7, "metadata": {}}
        )
        evidence = store.get_evidence(["a", "c"])
        assert len(evidence) == 2
        assert evidence[0]["id"] == "a"

    def test_top_rated_returns_by_rating_then_score(self):
        store = EvidenceStore()
        store.register_hit(
            {"id": "a", "question": "Q", "answer": "A", "score": 0.9, "metadata": {}}
        )
        store.register_hit(
            {"id": "b", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}}
        )
        store.register_hit(
            {"id": "c", "question": "Q", "answer": "A", "score": 0.6, "metadata": {}}
        )
        store.set_rating("a", "RELEVANT", confidence=4)
        store.set_rating("b", "RELEVANT", confidence=5)
        store.set_rating("c", "PARTIAL", confidence=3)
        top = store.top_rated(n=2)
        ids = [h["id"] for h in top]
        assert ids == ["b", "a"]  # both RELEVANT, b has higher confidence

    def test_as_dict_returns_snapshot_copy(self):
        """as_dict() returns a copy — writes after the call are NOT visible."""
        store = EvidenceStore()
        store.register_hit(
            {"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
        )
        d = store.as_dict()
        assert isinstance(d, dict)
        assert "x" in d
        store.register_hit(
            {"id": "y", "question": "Q2", "answer": "A2", "score": 0.6, "metadata": {}}
        )
        assert "y" not in d  # snapshot — doesn't see new writes

    def test_live_dict_reflects_writes(self):
        """live_dict exposes the internal dict — LM sees tool writes immediately."""
        store = EvidenceStore()
        live = store.live_dict
        assert len(live) == 0
        store.register_hit(
            {"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}}
        )
        assert "x" in live  # live reference — sees the write
