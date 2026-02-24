# rlm_search Department Model Redesign (A+C Hybrid)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace rlm_search's 22-field god object (ToolContext) with four scoped departments connected by a single EventBus, eliminating the dual-channel streaming hack, the follow-up session hack, and prompt-code duplication — while keeping the LM-facing API unchanged.

**Architecture:** Four departments (EvidenceStore, QualityGate, EventBus, SessionManager) each own their state and expose clean protocols. A thin ToolContext wires them together. The EventBus is the single append-only channel for all streaming — SSE reads from it, frontend consumes typed events directly. Tools keep identical LM-facing signatures but rewire internals to use department methods. The follow-up session swap becomes a single `SessionManager.swap_logger()` call instead of 4 fragile mutations through private internals.

**Tech Stack:** Python 3.11+, FastAPI, dataclasses, threading.Lock, existing RLM core (no core changes)

**Branch:** `feature/department-redesign` (worktree: `.worktrees/department-redesign`)

---

## Progress

| Task | Phase | Status | Tests | Commit | Notes |
|------|-------|--------|-------|--------|-------|
| 0: Prompt Caching | 0 | DONE | 18 pass | `59ece03` | 5-line change, both sync+async paths |
| 1: EventBus | 1 | DONE | 9 pass | `991b881` | emit/drain/replay/cancel, thread-safe |
| 2: EvidenceStore | 1 | DONE | 13 pass | `2c6bb4c` | register_hit, ratings, merge, live_dict |
| 3: QualityGate | 1 | DONE | 12 pass | `0b380db` | 5-factor confidence, phase detection |
| 4: SearchContext | 2 | DONE | 4 pass | `09d3777` | ~10 fields, auto-creates QualityGate |
| 5: Tracker rewire | 2 | DONE | 4 new + 148 legacy pass | `5ca5a1f` | Dual-path: bus or legacy callback |
| 6: SessionManager | 3 | DONE | 11 pass | `8f008e9` | Session lifecycle, follow-up swap, expiration |
| 7: StreamingLoggerV2 | 4 | DONE | 5 pass | `1f1aa84` | RLMLogger subclass, EventBus delegation, JSONL |
| 8: SSE endpoint | 5 | DONE | 3 pass | `7be27a9` | EventBus drain, replay, 100ms poll |
| 9: setup_code v2 | 6 | DONE | 1 pass | `3b55ae4` | SearchContext + departments, backward compat props |
| 10: api_v2 orchestrator | 6 | DONE | 2 pass | `c83603a` | SessionManager, EventBus per search, SSE router |
| 11: Migrate tools | 7 | PENDING | — | — | Largest blast radius |
| 12: Swap api.py | 7 | PENDING | — | — | |
| 13: Remove legacy | 7 | PENDING | — | — | |
| 14: Prompt dedup | 7 | PENDING | — | — | |
| 15: Frontend events | 8 | PENDING | — | — | |

**Full suite:** 491 passed, 8 skipped, 6 pre-existing failures (3 TestInitClassify, 3 test_empty_iteration_breaker)

**Next batch:** Tasks 11-14 (Phase 7: Cutover + Cleanup). Task 11 is the critical migration — rewire all tools from `ctx.source_registry`/`ctx.search_log`/`ctx.evaluated_ratings` to `ctx.evidence.*` methods. Backward-compat properties on SearchContext (`context_v2.py`) already bridge the gap so existing tests pass through migration. After Task 11, swap api.py (12), remove legacy files (13), deduplicate prompts (14).

**Key context for next session:**
- Working in worktree at `.worktrees/department-redesign` on branch `feature/department-redesign`
- SearchContext (`context_v2.py`) already has backward-compat properties: `source_registry` → `evidence.live_dict`, `search_log` → `evidence.search_log`, `evaluated_ratings` → `evidence._ratings`
- Tracker (`tracker.py`) already dual-paths: emits to `ctx.bus` if present, else falls back to `progress_callback`
- `api_v2.py` uses `build_search_setup_code_v2()` which creates SearchContext — but tools still directly access old ToolContext fields internally
- Task 11 strategy: duck-type check `hasattr(ctx, 'evidence')` in each tool file, migrate writes to department methods

---

## Phase 0: Quick Wins (Independent of Redesign)

---

### Task 0: Prompt Caching in AnthropicClient

**Files:**
- Modify: `rlm/clients/anthropic.py`

**Context:** The system prompt is passed as a plain string on every API call. Anthropic's prompt caching (`cache_control: {"type": "ephemeral"}`) can save ~60-80% on system prompt tokens with a 5-line change. This is independent of the department redesign and delivers the highest ROI of any single change.

**Step 1: Modify system prompt handling**

In `rlm/clients/anthropic.py`, change the system prompt from a plain string to a cached content block:

```python
# Before (current):
if system:
    kwargs["system"] = system

# After:
if system:
    kwargs["system"] = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
```

**Step 2: Run tests**

Run: `uv run pytest tests/ -v -x -k "anthropic or client"`
Expected: ALL PASS (the API accepts both string and list format for system)

**Step 3: Commit**

```bash
git add rlm/clients/anthropic.py
git commit -m "feat(clients): enable prompt caching for Anthropic system prompts"
```

---

## Phase 1: Foundation — EventBus + EvidenceStore

Build the two most fundamental departments. Everything else depends on these.

---

### Task 1: EventBus — The Single Channel

**Files:**
- Create: `rlm_search/bus.py`
- Test: `tests/test_event_bus.py`

**Context:** Currently, tool progress flows through TWO channels: (1) `progress_callback` → `StreamingLogger.emit_tool_event()` for real-time SSE, and (2) `ctx.tool_calls` list → REPL locals snapshot → `StreamingLogger.log()` for iteration events. The EventBus replaces both with a single append-only queue. Every department emits here. SSE reads from here.

**Step 1: Write the failing tests**

```python
"""tests/test_event_bus.py"""
import threading
import time

from rlm_search.bus import EventBus


class TestEventBusEmitAndDrain:
    def test_emit_single_event(self):
        bus = EventBus()
        bus.emit("test_event", {"key": "value"})
        events = bus.drain()
        assert len(events) == 1
        assert events[0]["type"] == "test_event"
        assert events[0]["data"]["key"] == "value"
        assert "timestamp" in events[0]

    def test_drain_clears_queue(self):
        bus = EventBus()
        bus.emit("a", {})
        bus.emit("b", {})
        first = bus.drain()
        assert len(first) == 2
        second = bus.drain()
        assert len(second) == 0

    def test_replay_returns_all_events_without_clearing(self):
        bus = EventBus()
        bus.emit("a", {"n": 1})
        bus.emit("b", {"n": 2})
        bus.drain()  # consume
        bus.emit("c", {"n": 3})
        # replay returns ALL events ever emitted
        all_events = bus.replay()
        assert len(all_events) == 3
        assert [e["type"] for e in all_events] == ["a", "b", "c"]

    def test_thread_safety(self):
        bus = EventBus()
        errors = []

        def writer(prefix, count):
            try:
                for i in range(count):
                    bus.emit(f"{prefix}_{i}", {"i": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"t{t}", 100)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        all_events = bus.replay()
        assert len(all_events) == 400


class TestEventBusTerminalEvents:
    def test_is_terminal(self):
        bus = EventBus()
        assert not bus.is_done
        bus.emit("done", {"answer": "test"})
        assert bus.is_done

    def test_error_is_terminal(self):
        bus = EventBus()
        bus.emit("error", {"message": "failed"})
        assert bus.is_done

    def test_cancelled_is_terminal(self):
        bus = EventBus()
        bus.emit("cancelled", {})
        assert bus.is_done


class TestEventBusCancellation:
    def test_cancel_sets_flag(self):
        bus = EventBus()
        assert not bus.cancelled
        bus.cancel()
        assert bus.cancelled

    def test_raise_if_cancelled(self):
        from rlm_search.bus import SearchCancelled
        bus = EventBus()
        bus.cancel()
        import pytest
        with pytest.raises(SearchCancelled):
            bus.raise_if_cancelled()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_event_bus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rlm_search.bus'`

**Step 3: Write minimal implementation**

```python
"""rlm_search/bus.py"""
import threading
from datetime import datetime
from typing import Any

TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})


class SearchCancelled(Exception):
    """Raised when a search is cancelled via the EventBus."""


class EventBus:
    """Single append-only event channel for all rlm_search streaming.

    All departments emit here. SSE stream reads from here.
    Replaces: dual-channel streaming, stdout tag parsing,
    progress_callback, _parent_logger ref.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []  # pending (not yet drained)
        self._log: list[dict[str, Any]] = []  # all events ever (for replay)
        self._cancelled = False
        self._done = False

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Append a typed event to the bus."""
        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        with self._lock:
            self._queue.append(event)
            self._log.append(event)
            if event_type in TERMINAL_EVENTS:
                self._done = True

    def drain(self) -> list[dict[str, Any]]:
        """Return and clear pending events. Thread-safe."""
        with self._lock:
            events = self._queue[:]
            self._queue.clear()
        return events

    def replay(self) -> list[dict[str, Any]]:
        """Return ALL events ever emitted (for reconnection). Does not clear."""
        with self._lock:
            return self._log[:]

    def cancel(self) -> None:
        """Signal cancellation. Next raise_if_cancelled() will throw."""
        self._cancelled = True

    def raise_if_cancelled(self) -> None:
        """Check cancellation flag. Called by RLM core per iteration."""
        if self._cancelled:
            raise SearchCancelled("Search cancelled")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_done(self) -> bool:
        return self._done
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_event_bus.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/bus.py tests/test_event_bus.py
git commit -m "feat(rlm-search): add EventBus — single append-only event channel"
```

---

### Task 2: EvidenceStore — Owns source_registry + search_log

**Files:**
- Create: `rlm_search/evidence.py`
- Test: `tests/test_evidence_store.py`

**Context:** Currently `source_registry` (dict) and `search_log` (list) live as fields on ToolContext with 3 independent writers and no coordination protocol. `normalize_hit()` writes to registry, `delegation_tools.rlm_query()` merges child sources, and `StreamingLogger.log()` reads from REPL locals. The EvidenceStore owns all evidence state and exposes explicit methods.

**Step 1: Write the failing tests**

```python
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
        store.register_hit({"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}})
        store.register_hit({"id": "x", "question": "Q", "answer": "A", "score": 0.9, "metadata": {}})
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
        store.register_hit({"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}})
        store.set_rating("x", "RELEVANT", confidence=4)
        assert store.get_rating("x") == {"rating": "RELEVANT", "confidence": 4}

    def test_get_rating_unrated_returns_none(self):
        store = EvidenceStore()
        assert store.get_rating("nonexistent") is None

    def test_rated_count(self):
        store = EvidenceStore()
        for i in range(5):
            store.register_hit({"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}})
        store.set_rating("h0", "RELEVANT", confidence=4)
        store.set_rating("h1", "PARTIAL", confidence=2)
        store.set_rating("h2", "OFF-TOPIC", confidence=5)
        counts = store.rating_counts()
        assert counts == {"RELEVANT": 1, "PARTIAL": 1, "OFF-TOPIC": 1}


class TestEvidenceStoreMerge:
    def test_merge_child_sources(self):
        parent = EvidenceStore()
        parent.register_hit({"id": "p1", "question": "Q1", "answer": "A1", "score": 0.8, "metadata": {}})

        child = EvidenceStore()
        child.register_hit({"id": "c1", "question": "Q2", "answer": "A2", "score": 0.7, "metadata": {}})
        child.register_hit({"id": "p1", "question": "Q1", "answer": "A1", "score": 0.9, "metadata": {}})

        parent.merge(child)
        assert parent.count == 2  # p1 + c1
        assert parent.get("p1")["score"] == 0.9  # child had higher score
        assert parent.get("c1") is not None


class TestEvidenceStoreEvidence:
    def test_get_evidence_for_ids(self):
        store = EvidenceStore()
        store.register_hit({"id": "a", "question": "Q1", "answer": "A1", "score": 0.9, "metadata": {}})
        store.register_hit({"id": "b", "question": "Q2", "answer": "A2", "score": 0.8, "metadata": {}})
        store.register_hit({"id": "c", "question": "Q3", "answer": "A3", "score": 0.7, "metadata": {}})
        evidence = store.get_evidence(["a", "c"])
        assert len(evidence) == 2
        assert evidence[0]["id"] == "a"

    def test_top_rated_returns_by_rating_then_score(self):
        store = EvidenceStore()
        store.register_hit({"id": "a", "question": "Q", "answer": "A", "score": 0.9, "metadata": {}})
        store.register_hit({"id": "b", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}})
        store.register_hit({"id": "c", "question": "Q", "answer": "A", "score": 0.6, "metadata": {}})
        store.set_rating("a", "RELEVANT", confidence=4)
        store.set_rating("b", "RELEVANT", confidence=5)
        store.set_rating("c", "PARTIAL", confidence=3)
        top = store.top_rated(n=2)
        ids = [h["id"] for h in top]
        assert ids == ["b", "a"]  # both RELEVANT, b has higher confidence

    def test_as_dict_returns_snapshot_copy(self):
        """as_dict() returns a copy — writes after the call are NOT visible."""
        store = EvidenceStore()
        store.register_hit({"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}})
        d = store.as_dict()
        assert isinstance(d, dict)
        assert "x" in d
        store.register_hit({"id": "y", "question": "Q2", "answer": "A2", "score": 0.6, "metadata": {}})
        assert "y" not in d  # snapshot — doesn't see new writes

    def test_live_dict_reflects_writes(self):
        """live_dict exposes the internal dict — LM sees tool writes immediately."""
        store = EvidenceStore()
        live = store.live_dict
        assert len(live) == 0
        store.register_hit({"id": "x", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}})
        assert "x" in live  # live reference — sees the write
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_evidence_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rlm_search.evidence'`

**Step 3: Write minimal implementation**

```python
"""rlm_search/evidence.py"""
from __future__ import annotations

import dataclasses
from typing import Any


RATING_ORDER = {"RELEVANT": 0, "PARTIAL": 1, "OFF-TOPIC": 2, "UNKNOWN": 3}


@dataclasses.dataclass
class EvidenceStore:
    """Owns source_registry, search_log, and evaluated_ratings.

    Single writer protocol: all mutations go through methods.
    Replaces the scattered writes across normalize_hit, delegation merge,
    and StreamingLogger snapshot polling.
    """

    _registry: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    _ratings: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    _search_log: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    # --- Registration ---

    def register_hit(self, hit: dict[str, Any]) -> str:
        """Register a search hit. Deduplicates by id, keeps higher score."""
        hit_id = str(hit["id"])
        existing = self._registry.get(hit_id)
        if existing is None or hit.get("score", 0) > existing.get("score", 0):
            self._registry[hit_id] = {
                "id": hit_id,
                "question": hit.get("question", ""),
                "answer": hit.get("answer", ""),
                "score": hit.get("score", 0),
                "metadata": hit.get("metadata", {}),
            }
        return hit_id

    def get(self, hit_id: str) -> dict[str, Any] | None:
        return self._registry.get(str(hit_id))

    @property
    def count(self) -> int:
        return len(self._registry)

    # --- Search log ---

    def log_search(
        self,
        query: str,
        num_results: int,
        filters: dict[str, Any] | None = None,
        search_type: str = "search",
    ) -> None:
        self._search_log.append({
            "type": search_type,
            "query": query,
            "num_results": num_results,
            "filters": filters or {},
        })

    @property
    def search_log(self) -> list[dict[str, Any]]:
        return self._search_log

    # --- Ratings ---

    def set_rating(self, hit_id: str, rating: str, confidence: int = 0) -> None:
        self._ratings[str(hit_id)] = {"rating": rating, "confidence": confidence}

    def get_rating(self, hit_id: str) -> dict[str, Any] | None:
        return self._ratings.get(str(hit_id))

    def rating_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._ratings.values():
            rating = r["rating"]
            counts[rating] = counts.get(rating, 0) + 1
        return counts

    # --- Evidence retrieval ---

    def get_evidence(self, hit_ids: list[str]) -> list[dict[str, Any]]:
        """Get registry entries for specific IDs, preserving order."""
        return [self._registry[str(hid)] for hid in hit_ids if str(hid) in self._registry]

    def top_rated(self, n: int = 10) -> list[dict[str, Any]]:
        """Return top N hits sorted by rating tier then confidence."""
        rated = []
        for hit_id, rating_info in self._ratings.items():
            hit = self._registry.get(hit_id)
            if hit is None:
                continue
            rated.append({
                **hit,
                "_rating": rating_info["rating"],
                "_confidence": rating_info["confidence"],
            })
        rated.sort(key=lambda h: (RATING_ORDER.get(h["_rating"], 99), -h["_confidence"]))
        return [{k: v for k, v in h.items() if not k.startswith("_")} for h in rated[:n]]

    # --- Merge (for child delegation) ---

    def merge(self, child: EvidenceStore) -> None:
        """Merge a child store into this one. Higher scores win on conflict."""
        for hit_id, hit in child._registry.items():
            self.register_hit(hit)
        for hit_id, rating in child._ratings.items():
            if hit_id not in self._ratings:
                self._ratings[hit_id] = rating

    # --- REPL compatibility ---

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """Snapshot copy for serialization or logging."""
        return dict(self._registry)

    @property
    def live_dict(self) -> dict[str, dict[str, Any]]:
        """Live reference for REPL locals — LM sees tool writes immediately.

        IMPORTANT: The current source_registry = _ctx.source_registry is a live
        dict reference. Tools write via normalize_hit(), LM reads via
        print(source_registry). Using as_dict() here would break this contract
        because it returns a copy. Expose _registry directly so mutations from
        register_hit() are visible to the LM without re-assignment.

        The LM should NOT write to this dict directly — use register_hit().
        """
        return self._registry
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_evidence_store.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/evidence.py tests/test_evidence_store.py
git commit -m "feat(rlm-search): add EvidenceStore — owns source_registry, search_log, ratings"
```

---

### Task 3: QualityGate — Owns confidence, critique verdicts, progress phases

**Files:**
- Create: `rlm_search/quality.py`
- Test: `tests/test_quality_gate.py`

**Context:** Currently confidence computation lives in `progress_tools._compute_confidence()` (5-factor formula reading scattered ctx fields), critique verdicts are stored nowhere (just returned), and the 60% threshold is duplicated in prompts.py and progress_tools.py. QualityGate owns all quality state and the threshold constants.

**Step 1: Write the failing tests**

```python
"""tests/test_quality_gate.py"""
from rlm_search.quality import QualityGate
from rlm_search.evidence import EvidenceStore


class TestQualityGateConfidence:
    def test_initial_confidence_is_zero(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.confidence == 0

    def test_confidence_increases_with_relevant_hits(self):
        evidence = EvidenceStore()
        for i in range(5):
            evidence.register_hit({"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.8, "metadata": {}})
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=4)
        gate = QualityGate(evidence=evidence)
        assert gate.confidence > 0

    def test_confidence_includes_critique_outcome(self):
        evidence = EvidenceStore()
        for i in range(3):
            evidence.register_hit({"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.8, "metadata": {}})
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
            evidence.register_hit({"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.9, "metadata": {}})
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=5)
        gate = QualityGate(evidence=evidence)
        gate.record_draft(length=500)
        gate.record_critique(passed=True, verdict="PASS")
        assert gate.phase in ("ready", "finalize")

    def test_phase_continue_below_threshold(self):
        evidence = EvidenceStore()
        evidence.register_hit({"id": "h0", "question": "Q", "answer": "A", "score": 0.5, "metadata": {}})
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
        gate.record_critique(passed=True, verdict="PASS — all grounded")
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quality_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rlm_search.quality'`

**Step 3: Write minimal implementation**

```python
"""rlm_search/quality.py"""
from __future__ import annotations

import dataclasses
from typing import Any

from rlm_search.evidence import EvidenceStore


@dataclasses.dataclass
class QualityGate:
    """Owns confidence scoring, critique verdicts, and progress phase.

    Single source of truth for quality thresholds. The system prompt
    references these by name, not by numeric value.

    Replaces: progress_tools._compute_confidence(), scattered critique
    state, duplicated threshold constants in prompts.py.
    """

    evidence: EvidenceStore

    # --- Thresholds (single source of truth) ---
    READY_THRESHOLD: int = 60
    STALL_SEARCH_COUNT: int = 6

    # --- Mutable state ---
    _has_draft: bool = dataclasses.field(default=False, init=False)
    _draft_length: int = dataclasses.field(default=0, init=False)
    _last_critique: dict[str, Any] | None = dataclasses.field(default=None, init=False)

    # --- Draft tracking ---

    def record_draft(self, length: int) -> None:
        self._has_draft = True
        self._draft_length = length

    @property
    def has_draft(self) -> bool:
        return self._has_draft

    @property
    def draft_length(self) -> int:
        return self._draft_length

    # --- Critique tracking ---

    def record_critique(self, passed: bool, verdict: str) -> None:
        self._last_critique = {"passed": passed, "verdict": verdict}

    @property
    def last_critique(self) -> dict[str, Any] | None:
        return self._last_critique

    # --- Confidence (5-factor + critique bonus) ---

    @property
    def confidence(self) -> int:
        """Compute confidence score (0-100). Deterministic, from evidence state."""
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)
        partial = counts.get("PARTIAL", 0)
        total_rated = sum(counts.values())

        # Factor 1: Relevance (35%)
        if total_rated == 0:
            relevance_score = 0
        else:
            relevance_score = min(35, int(35 * (relevant + 0.3 * partial) / max(total_rated, 1)))

        # Factor 2: Top score quality (25%)
        top_score = 0.0
        for entry in self.evidence._registry.values():
            if entry.get("score", 0) > top_score:
                top_score = entry["score"]
        quality_score = min(25, int(25 * top_score))

        # Factor 3: Breadth (10%)
        n_searches = len(self.evidence.search_log)
        breadth_score = min(10, n_searches * 3)

        # Factor 4: Draft exists (15%)
        draft_score = 15 if self._has_draft else 0

        # Factor 5: Critique outcome (15%)
        critique_score = 0
        if self._last_critique is not None:
            critique_score = 15 if self._last_critique["passed"] else 5

        return min(100, relevance_score + quality_score + breadth_score + draft_score + critique_score)

    # --- Phase ---

    @property
    def phase(self) -> str:
        """Determine current search phase from evidence state."""
        n_searches = len(self.evidence.search_log)
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)

        if n_searches >= self.STALL_SEARCH_COUNT and relevant < 2:
            return "stalled"

        conf = self.confidence
        if conf >= self.READY_THRESHOLD:
            if self._has_draft and self._last_critique and self._last_critique["passed"]:
                return "finalize"
            return "ready"

        return "continue"

    # --- Guidance (copy-paste-ready next steps for LM) ---

    def guidance(self) -> str:
        """Return guidance string for the LM based on current phase."""
        p = self.phase
        if p == "stalled":
            return "Evidence insufficient after multiple searches. Try reformulate() or broaden filters."
        if p == "ready":
            return "Evidence sufficient. Call draft_answer() to synthesize."
        if p == "finalize":
            return "Draft passed critique. Call FINAL_VAR(answer) to deliver."
        # continue
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)
        if relevant == 0:
            return "No relevant results yet. Try different query angles or broader filters."
        return f"{relevant} relevant sources found. Continue searching for more evidence or draft if confident."
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quality_gate.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/quality.py tests/test_quality_gate.py
git commit -m "feat(rlm-search): add QualityGate — owns confidence, critique, phases"
```

---

## Phase 2: Thin ToolContext + Tool Tracker Rewiring

Wire the departments into the tools without changing LM-facing signatures.

---

### Task 4: New Thin ToolContext

**Files:**
- Create: `rlm_search/tools/context_v2.py`
- Test: `tests/test_context_v2.py`

**Context:** The current `ToolContext` has 22+ fields spanning 5 concerns. The new one holds API config + references to departments. We create it as `context_v2.py` alongside the existing `context.py` so both can coexist during migration.

**Step 1: Write the failing tests**

```python
"""tests/test_context_v2.py"""
from rlm_search.tools.context_v2 import SearchContext
from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate


class TestSearchContextCreation:
    def test_creates_with_departments(self):
        bus = EventBus()
        evidence = EvidenceStore()
        quality = QualityGate(evidence=evidence)
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="test-key",
            bus=bus,
            evidence=evidence,
            quality=quality,
        )
        assert ctx.api_url == "https://example.com"
        assert ctx.evidence is evidence
        assert ctx.quality is quality
        assert ctx.bus is bus

    def test_headers_auto_generated(self):
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="test-key",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert ctx.headers["Authorization"] == "Bearer test-key"

    def test_llm_callables_default_none(self):
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert ctx.llm_query is None
        assert ctx.llm_query_batched is None

    def test_tool_calls_list_for_repl_compat(self):
        """tool_calls must remain a plain list for REPL locals compatibility."""
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert isinstance(ctx.tool_calls, list)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_context_v2.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""rlm_search/tools/context_v2.py"""
from __future__ import annotations

import dataclasses
from typing import Any

from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate


@dataclasses.dataclass
class SearchContext:
    """Thin wiring harness connecting departments.

    ~10 fields, down from 22. Departments own their state.
    This just holds API config + department references + LLM callables.
    """

    # --- API config (read-only after init) ---
    api_url: str
    api_key: str
    timeout: int = 30
    headers: dict[str, str] = dataclasses.field(default_factory=dict)

    # --- Department references ---
    bus: EventBus = dataclasses.field(default_factory=EventBus)
    evidence: EvidenceStore = dataclasses.field(default_factory=EvidenceStore)
    quality: QualityGate | None = None  # auto-created in __post_init__ if not provided

    # --- LLM callables (injected from REPL globals) ---
    llm_query: Any = None
    llm_query_batched: Any = None

    # --- REPL compatibility (tracker still appends here for LM visibility) ---
    tool_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    # --- Delegation config ---
    classification: dict | None = None
    kb_overview_data: dict | None = None
    _rlm_model: str = ""
    _rlm_backend: str = ""
    _depth: int = 0
    _max_delegation_depth: int = 1
    _sub_iterations: int | None = None
    pipeline_mode: str = ""

    def __post_init__(self) -> None:
        if not self.headers and self.api_key:
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        # QualityGate needs evidence reference — auto-create if not provided
        if self.quality is None:
            self.quality = QualityGate(evidence=self.evidence)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_context_v2.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/tools/context_v2.py tests/test_context_v2.py
git commit -m "feat(rlm-search): add SearchContext — thin ToolContext replacement with departments"
```

---

### Task 5: Rewire tracker.py to emit through EventBus

**Files:**
- Modify: `rlm_search/tools/tracker.py`
- Test: `tests/test_tracker_v2.py`

**Context:** The current tracker emits via `ctx.progress_callback` (one channel) AND appends to `ctx.tool_calls` (second channel). Rewire it to emit through `ctx.bus` as the single channel while still appending to `ctx.tool_calls` for REPL locals compatibility. This eliminates the need for `progress_callback` and `_parent_logger` fields on ToolContext.

**Step 1: Write the failing tests**

```python
"""tests/test_tracker_v2.py"""
import contextlib
from unittest.mock import MagicMock

from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate
from rlm_search.tools.context_v2 import SearchContext


def _make_ctx() -> SearchContext:
    bus = EventBus()
    evidence = EvidenceStore()
    quality = QualityGate(evidence=evidence)
    return SearchContext(api_url="https://test.com", api_key="k", bus=bus, evidence=evidence, quality=quality)


class TestTrackerEmitsToBus:
    def test_tool_start_event_emitted(self):
        from rlm_search.tools.tracker import tool_call_tracker
        ctx = _make_ctx()
        with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
            tc.set_summary({"num_results": 5})
        events = ctx.bus.replay()
        start_events = [e for e in events if e["type"] == "tool_start"]
        assert len(start_events) == 1
        assert start_events[0]["data"]["tool"] == "search"

    def test_tool_end_event_emitted(self):
        from rlm_search.tools.tracker import tool_call_tracker
        ctx = _make_ctx()
        with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
            tc.set_summary({"num_results": 5})
        events = ctx.bus.replay()
        end_events = [e for e in events if e["type"] == "tool_end"]
        assert len(end_events) == 1
        assert end_events[0]["data"]["tool"] == "search"
        assert "duration_ms" in end_events[0]["data"]

    def test_tool_calls_list_still_populated(self):
        """REPL locals compatibility: ctx.tool_calls must still be appended."""
        from rlm_search.tools.tracker import tool_call_tracker
        ctx = _make_ctx()
        with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
            tc.set_summary({"num_results": 5})
        assert len(ctx.tool_calls) == 1
        assert ctx.tool_calls[0]["tool"] == "search"

    def test_tool_error_recorded(self):
        from rlm_search.tools.tracker import tool_call_tracker
        ctx = _make_ctx()
        with contextlib.suppress(ValueError):
            with tool_call_tracker(ctx, "search", {"query": "test"}) as tc:
                raise ValueError("test error")
        assert ctx.tool_calls[0]["error"] is not None
        end_events = [e for e in ctx.bus.replay() if e["type"] == "tool_end"]
        assert end_events[0]["data"].get("error") is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tracker_v2.py -v`
Expected: FAIL — tracker doesn't emit to bus yet

**Step 3: Modify tracker.py**

Modify: `rlm_search/tools/tracker.py`

The tracker needs to detect whether it's working with the old `ToolContext` (has `progress_callback`) or new `SearchContext` (has `bus`). During migration, support both.

```python
"""rlm_search/tools/tracker.py — updated to emit through EventBus when available."""
from __future__ import annotations

import contextlib
import time
from typing import Any, Generator


def _compact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Truncate large argument values for logging."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 100:
            out[k] = v[:100] + "..."
        elif isinstance(v, list):
            out[k] = f"[{len(v)} items]"
        else:
            out[k] = v
    return out


def _emit(ctx: Any, tool: str, phase: str, data: dict[str, Any] | None = None) -> None:
    """Emit tool progress — via EventBus if available, else legacy callback."""
    bus = getattr(ctx, "bus", None)
    if bus is not None:
        event_type = f"tool_{phase}"  # tool_start, tool_end
        bus.emit(event_type, {"tool": tool, **(data or {})})
        return
    # Legacy path: use progress_callback
    cb = getattr(ctx, "progress_callback", None)
    if cb is not None:
        cb(tool, phase, data or {})


class _ToolCallHandle:
    """Handle returned by tool_call_tracker for setting summary."""

    def __init__(self, entry: dict[str, Any], idx: int) -> None:
        self.entry = entry
        self.idx = idx

    def set_summary(self, summary: dict[str, Any]) -> None:
        self.entry["result_summary"] = summary


@contextlib.contextmanager
def tool_call_tracker(
    ctx: Any,
    tool_name: str,
    args: dict[str, Any],
    parent_idx: int | None = None,
) -> Generator[_ToolCallHandle, None, None]:
    """Context manager that tracks a tool call on ctx.tool_calls and emits events."""
    compact = _compact_args(args)
    entry: dict[str, Any] = {
        "tool": tool_name,
        "args": compact,
        "result_summary": {},
        "duration_ms": 0,
        "children": [],
        "error": None,
    }

    ctx.tool_calls.append(entry)
    idx = len(ctx.tool_calls) - 1

    if parent_idx is not None and 0 <= parent_idx < len(ctx.tool_calls):
        ctx.tool_calls[parent_idx].setdefault("children", []).append(idx)

    _emit(ctx, tool_name, "start", {"args": compact})
    start = time.monotonic()
    handle = _ToolCallHandle(entry, idx)

    try:
        yield handle
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        entry["duration_ms"] = elapsed_ms
        _emit(ctx, tool_name, "end", {
            "result_summary": entry["result_summary"],
            "duration_ms": elapsed_ms,
            "error": entry["error"],
        })
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tracker_v2.py -v`
Expected: ALL PASS

Also verify existing tests still pass:
Run: `uv run pytest tests/test_repl_tools.py -v -x`
Expected: ALL PASS (old ToolContext path still works via legacy `_emit`)

**Step 5: Commit**

```bash
git add rlm_search/tools/tracker.py tests/test_tracker_v2.py
git commit -m "refactor(rlm-search): tracker emits to EventBus, falls back to legacy callback"
```

---

## Phase 3: SessionManager — Kill the Follow-Up Hack

---

### Task 6: SessionManager — Proper Session Protocol

**Files:**
- Create: `rlm_search/sessions.py`
- Test: `tests/test_session_manager.py`

**Context:** Currently `api.py:353-368` reaches through `rlm._persistent_env`, walks function closures to find `_ctx`, and makes 4 coordinated mutations to swap the logger for a follow-up search. SessionManager encapsulates this into a single `prepare_follow_up()` method. The key insight: instead of mutating `_ctx` through closures, pass the EventBus reference through `_ctx.bus` at setup time — and for follow-ups, the bus itself is swappable (or we create a new bus per search and wire it in).

**Step 1: Write the failing tests**

```python
"""tests/test_session_manager.py"""
import threading
import time
from unittest.mock import MagicMock, patch

from rlm_search.sessions import SessionManager, SessionState


class TestSessionManagerLifecycle:
    def test_create_session(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        assert sid is not None
        assert mgr.get(sid) is not None

    def test_get_nonexistent_returns_none(self):
        mgr = SessionManager()
        assert mgr.get("nonexistent") is None

    def test_delete_session(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        mgr.delete(sid)
        assert mgr.get(sid) is None

    def test_delete_calls_rlm_close(self):
        mgr = SessionManager()
        mock_rlm = MagicMock()
        sid = mgr.create_session(rlm=mock_rlm, bus=MagicMock())
        mgr.delete(sid)
        mock_rlm.close.assert_called_once()


class TestSessionManagerBusy:
    def test_active_search_prevents_new_search(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        session = mgr.get(sid)
        session.active_search_id = "search_1"
        assert mgr.is_busy(sid)

    def test_no_active_search_is_not_busy(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        assert not mgr.is_busy(sid)


class TestSessionManagerCleanup:
    def test_cleanup_expired_sessions(self):
        mgr = SessionManager(session_timeout=0.1)  # 100ms timeout
        mock_rlm = MagicMock()
        sid = mgr.create_session(rlm=mock_rlm, bus=MagicMock())
        time.sleep(0.2)
        removed = mgr.cleanup_expired()
        assert sid in removed
        assert mgr.get(sid) is None
        mock_rlm.close.assert_called_once()

    def test_cleanup_skips_active_sessions(self):
        mgr = SessionManager(session_timeout=0.1)
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        mgr.get(sid).active_search_id = "active"
        time.sleep(0.2)
        removed = mgr.cleanup_expired()
        assert sid not in removed


class TestSessionManagerPrepareFollowUp:
    def test_prepare_follow_up_returns_rlm(self):
        mgr = SessionManager()
        mock_rlm = MagicMock()
        sid = mgr.create_session(rlm=mock_rlm, bus=MagicMock())
        from rlm_search.bus import EventBus
        new_bus = EventBus()
        rlm, session = mgr.prepare_follow_up(sid, new_bus, search_id="s2")
        assert rlm is mock_rlm
        assert session.active_search_id == "s2"
        assert session.search_count == 1

    def test_prepare_follow_up_raises_if_busy(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        mgr.get(sid).active_search_id = "s1"
        import pytest
        with pytest.raises(ValueError, match="busy"):
            mgr.prepare_follow_up(sid, MagicMock(), search_id="s2")

    def test_prepare_follow_up_raises_if_not_found(self):
        mgr = SessionManager()
        import pytest
        with pytest.raises(KeyError):
            mgr.prepare_follow_up("nonexistent", MagicMock(), search_id="s2")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""rlm_search/sessions.py"""
from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any

from rlm_search.bus import EventBus


@dataclasses.dataclass
class SessionState:
    """Persistent session for multi-turn search conversations."""

    session_id: str
    rlm: Any  # RLM instance
    bus: EventBus
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    search_count: int = 0
    last_active: float = dataclasses.field(default_factory=time.monotonic)
    active_search_id: str | None = None


class SessionManager:
    """Manages persistent search sessions.

    Replaces the ad-hoc session dict + follow-up hack in api.py.
    Encapsulates the 4-mutation logger swap into prepare_follow_up().
    """

    def __init__(self, session_timeout: float = 1800.0) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self.session_timeout = session_timeout

    def create_session(self, rlm: Any, bus: EventBus, session_id: str | None = None) -> str:
        import uuid
        sid = session_id or str(uuid.uuid4())[:12]
        session = SessionState(session_id=sid, rlm=rlm, bus=bus)
        with self._lock:
            self._sessions[sid] = session
        return sid

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def is_busy(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return session.active_search_id is not None

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.rlm.close()

    def prepare_follow_up(
        self,
        session_id: str,
        new_bus: EventBus,
        search_id: str,
    ) -> tuple[Any, SessionState]:
        """Prepare a session for a follow-up search.

        Replaces the 4-mutation hack in api.py:353-368.
        Returns (rlm, session) with session locked and marked active.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        if session.active_search_id is not None:
            raise ValueError(f"Session {session_id} is busy with {session.active_search_id}")

        with session.lock:
            session.search_count += 1
            session.last_active = time.monotonic()
            session.active_search_id = search_id
            session.bus = new_bus

        return session.rlm, session

    def cleanup_expired(self) -> list[str]:
        """Remove sessions idle longer than timeout. Returns removed IDs."""
        now = time.monotonic()
        to_remove: list[str] = []
        with self._lock:
            for sid, session in self._sessions.items():
                if session.active_search_id is not None:
                    continue
                if now - session.last_active > self.session_timeout:
                    to_remove.append(sid)
            for sid in to_remove:
                session = self._sessions.pop(sid)
                session.rlm.close()
        return to_remove

    def clear_active(self, session_id: str) -> None:
        """Mark a session's active search as complete."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.active_search_id = None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session_manager.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/sessions.py tests/test_session_manager.py
git commit -m "feat(rlm-search): add SessionManager — proper session protocol, no more follow-up hack"
```

---

## Phase 4: StreamingLogger Rewired to EventBus

---

### Task 7: StreamingLogger v2 — Reads from EventBus

**Files:**
- Create: `rlm_search/streaming_v2.py`
- Test: `tests/test_streaming_v2.py`

**Context:** The current StreamingLogger is a complex class that: (1) has its own thread-safe queue, (2) extracts tool_calls from REPL locals snapshots, (3) writes JSONL to disk, (4) serves as the RLMLogger for the core engine. The new version delegates the queue to EventBus. It still subclasses RLMLogger (core requirement) but translates RLM iteration events into EventBus emissions. No more dual-path data flow.

**Step 1: Write the failing tests**

```python
"""tests/test_streaming_v2.py"""
import json
import os
import tempfile

from rlm_search.bus import EventBus
from rlm_search.streaming_v2 import StreamingLoggerV2
from rlm.core.types import RLMIteration, RLMMetadata, CodeBlock, REPLResult


def _make_iteration(response: str = "test", code: str = "", stdout: str = "") -> RLMIteration:
    blocks = []
    if code:
        blocks.append(CodeBlock(
            code=code,
            result=REPLResult(stdout=stdout, stderr="", locals={}, execution_time=0.1),
        ))
    return RLMIteration(
        prompt=[{"role": "user", "content": "test"}],
        response=response,
        code_blocks=blocks,
        iteration_time=1.0,
    )


class TestStreamingV2EmitsToBus:
    def test_log_metadata_emits_to_bus(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            meta = RLMMetadata(
                root_model="test-model",
                max_depth=1,
                max_iterations=10,
                backend="anthropic",
                backend_kwargs={},
                environment_type="local",
                environment_kwargs={},
            )
            logger.log_metadata(meta)
        events = bus.replay()
        meta_events = [e for e in events if e["type"] == "metadata"]
        assert len(meta_events) == 1
        assert meta_events[0]["data"]["root_model"] == "test-model"

    def test_log_iteration_emits_to_bus(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            iteration = _make_iteration(response="thinking...", code="x = 1", stdout="done")
            logger.log(iteration)
        events = bus.replay()
        iter_events = [e for e in events if e["type"] == "iteration"]
        assert len(iter_events) == 1

    def test_mark_done_emits_terminal(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            logger.mark_done(answer="result", sources=[], execution_time=1.0, usage={})
        assert bus.is_done
        events = bus.replay()
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"]["answer"] == "result"


class TestStreamingV2WritesJSONL:
    def test_writes_to_disk(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            meta = RLMMetadata(
                root_model="m", max_depth=1, max_iterations=10,
                backend="anthropic", backend_kwargs={},
                environment_type="local", environment_kwargs={},
            )
            logger.log_metadata(meta)
            logger.log(_make_iteration())
            logger.mark_done(answer="a", sources=[], execution_time=1.0, usage={})
        files = [f for f in os.listdir(tmpdir) if f.endswith(".jsonl")]
        assert len(files) == 1
        with open(os.path.join(tmpdir, files[0])) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        types = [line["type"] for line in lines]
        assert "metadata" in types
        assert "iteration" in types
        assert "done" in types


class TestStreamingV2Cancellation:
    def test_raise_if_cancelled_delegates_to_bus(self):
        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StreamingLoggerV2(
                log_dir=tmpdir, file_name="test", search_id="s1", query="q", bus=bus
            )
            bus.cancel()
            import pytest
            from rlm_search.bus import SearchCancelled
            with pytest.raises(SearchCancelled):
                logger.raise_if_cancelled()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_streaming_v2.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""rlm_search/streaming_v2.py"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

from rlm.core.types import RLMIteration, RLMMetadata
from rlm.logger.rlm_logger import RLMLogger
from rlm_search.bus import EventBus, SearchCancelled


class StreamingLoggerV2(RLMLogger):
    """RLMLogger that emits all events through an EventBus.

    Replaces StreamingLogger's internal queue with EventBus delegation.
    Still writes JSONL to disk for audit trail.
    No more dual-path data flow — EventBus is the single channel.
    """

    def __init__(
        self,
        log_dir: str,
        file_name: str,
        search_id: str,
        query: str,
        bus: EventBus,
    ) -> None:
        # Initialize parent (creates log file)
        super().__init__(log_dir=log_dir, file_name=file_name)
        self.search_id = search_id
        self.query = query
        self.bus = bus

    # --- RLMLogger overrides ---

    def log_metadata(self, metadata: RLMMetadata) -> None:
        """Emit metadata to bus + write to JSONL."""
        if self._metadata_logged:
            return
        data = metadata.to_dict()
        data["search_id"] = self.search_id
        data["query"] = self.query

        # Emit to bus
        self.bus.emit("metadata", data)

        # Write to disk (parent pattern)
        entry = {"type": "metadata", "timestamp": datetime.now().isoformat(), **data}
        self._write_jsonl(entry)
        self._metadata_logged = True

    def log(self, iteration: RLMIteration) -> None:
        """Emit iteration to bus + write to JSONL."""
        self._iteration_count += 1
        data = {
            "iteration": self._iteration_count,
            **iteration.to_dict(),
        }

        # Emit to bus
        self.bus.emit("iteration", data)

        # Write to disk
        entry = {"type": "iteration", "timestamp": datetime.now().isoformat(), **data}
        self._write_jsonl(entry)

    # --- Terminal events ---

    def mark_done(
        self,
        answer: str | None,
        sources: list[dict[str, Any]],
        execution_time: float,
        usage: dict[str, Any],
    ) -> None:
        data = {
            "answer": answer,
            "sources": sources,
            "execution_time": execution_time,
            "usage": usage,
        }
        self.bus.emit("done", data)
        entry = {"type": "done", "timestamp": datetime.now().isoformat(), **data}
        self._write_jsonl(entry)

    def mark_error(self, message: str) -> None:
        self.bus.emit("error", {"message": message})
        entry = {"type": "error", "timestamp": datetime.now().isoformat(), "message": message}
        self._write_jsonl(entry)

    def mark_cancelled(self) -> None:
        self.bus.emit("cancelled", {})
        entry = {"type": "cancelled", "timestamp": datetime.now().isoformat()}
        self._write_jsonl(entry)

    # --- Cancellation (delegated to bus) ---

    def raise_if_cancelled(self) -> None:
        self.bus.raise_if_cancelled()

    # --- Properties for backward compat ---

    @property
    def is_done(self) -> bool:
        return self.bus.is_done

    @property
    def source_registry(self) -> dict:
        """For _extract_sources() in api.py — reads from bus context if available."""
        return {}

    # --- Internal ---

    def _write_jsonl(self, entry: dict[str, Any]) -> None:
        with open(self.log_file_path, "a") as f:
            json.dump(entry, f)
            f.write("\n")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_streaming_v2.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/streaming_v2.py tests/test_streaming_v2.py
git commit -m "feat(rlm-search): add StreamingLoggerV2 — delegates to EventBus, single channel"
```

---

## Phase 5: SSE Contract Evolution

---

### Task 8: New SSE endpoint that reads from EventBus

**Files:**
- Create: `rlm_search/sse.py`
- Test: `tests/test_sse.py`

**Context:** The current SSE endpoint in `api.py:518-558` polls `StreamingLogger.drain()` every 200ms. The new endpoint reads from EventBus, supports replay (for reconnection), and serves typed events that the frontend can consume directly — no more stdout tag parsing.

**Step 1: Write the failing tests**

```python
"""tests/test_sse.py"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI

from rlm_search.bus import EventBus
from rlm_search.sse import create_sse_router


class TestSSEEndpoint:
    def setup_method(self):
        self.app = FastAPI()
        self.searches: dict[str, EventBus] = {}
        self.app.include_router(create_sse_router(self.searches))

    def test_stream_returns_events(self):
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream", timeout=5)
        lines = [line for line in response.text.strip().split("\n") if line.startswith("data:")]
        assert len(lines) >= 2

        events = [json.loads(line.removeprefix("data: ")) for line in lines]
        types = [e["type"] for e in events]
        assert "metadata" in types
        assert "done" in types

    def test_stream_404_for_unknown_search(self):
        client = TestClient(self.app)
        response = client.get("/api/search/unknown/stream")
        assert response.status_code == 404

    def test_replay_on_reconnect(self):
        """If events already emitted before client connects, replay them."""
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.drain()  # simulate: first client already consumed
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream?replay=true", timeout=5)
        lines = [line for line in response.text.strip().split("\n") if line.startswith("data:")]
        events = [json.loads(line.removeprefix("data: ")) for line in lines]
        types = [e["type"] for e in events]
        # Replay sends ALL events (metadata + done)
        assert "metadata" in types
        assert "done" in types
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sse.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""rlm_search/sse.py"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from rlm_search.bus import EventBus


def create_sse_router(searches: dict[str, EventBus]) -> APIRouter:
    """Create SSE streaming router.

    Reads from EventBus instead of StreamingLogger.drain().
    Supports replay for reconnection.
    """
    router = APIRouter()

    @router.get("/api/search/{search_id}/stream")
    async def stream_search(
        search_id: str,
        request: Request,
        replay: bool = Query(default=False),
    ) -> StreamingResponse:
        if search_id not in searches:
            raise HTTPException(status_code=404, detail="Search not found")

        bus = searches[search_id]

        async def event_generator():
            deadline = time.monotonic() + 600  # 10 min max
            last_sent = time.monotonic()

            # Replay: send all historical events first
            if replay:
                for event in bus.replay():
                    yield f"data: {json.dumps(event)}\n\n"
                    last_sent = time.monotonic()
                    if event.get("type") in ("done", "error", "cancelled"):
                        searches.pop(search_id, None)
                        return

            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    bus.cancel()
                    searches.pop(search_id, None)
                    return

                events = bus.drain()
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                    last_sent = time.monotonic()
                    if event.get("type") in ("done", "error", "cancelled"):
                        searches.pop(search_id, None)
                        return

                if time.monotonic() - last_sent >= 15:
                    yield ": keepalive\n\n"
                    last_sent = time.monotonic()

                await asyncio.sleep(0.1)  # 100ms poll (down from 200ms)

            searches.pop(search_id, None)
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Search timed out'}})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sse.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/sse.py tests/test_sse.py
git commit -m "feat(rlm-search): add SSE router reading from EventBus with replay support"
```

---

## Phase 6: Integration — Wire Everything Together

---

### Task 9: New setup_code builder using SearchContext

**Files:**
- Create: `rlm_search/repl_tools_v2.py`
- Test: Add integration test to `tests/test_event_bus.py`

**Context:** The current `repl_tools.py:build_search_setup_code()` generates a code string that creates a `ToolContext` and defines 15 wrapper functions. The v2 builder creates a `SearchContext` (with departments) instead, wires the EventBus, and passes departments to tool functions. LM-facing function signatures stay IDENTICAL.

This is the most delicate task — the generated code string must work inside `exec()` in LocalREPL. All imports must be available in the REPL namespace.

**Step 1: Write the failing test**

```python
# Append to tests/test_event_bus.py

class TestSetupCodeV2Integration:
    """Verify the new setup code executes in a LocalREPL without errors."""

    def test_setup_code_executes_cleanly(self):
        from rlm_search.repl_tools_v2 import build_search_setup_code_v2
        from rlm.environments.local_repl import LocalREPL
        from rlm_search.bus import EventBus

        code = build_search_setup_code_v2(
            api_url="https://test.com",
            kb_overview_data=None,
            rlm_model="test-model",
            rlm_backend="anthropic",
            depth=0,
            max_delegation_depth=1,
            sub_iterations=3,
            query="test question",
            classify_model="test-model",
        )

        # The setup code should execute without errors in a real LocalREPL
        repl = LocalREPL(setup_code=code, depth=1)

        # Verify key functions exist in REPL namespace
        assert "search" in repl.locals
        assert "research" in repl.locals
        assert "draft_answer" in repl.locals
        assert "check_progress" in repl.locals
        assert "source_registry" in repl.locals

        repl.cleanup()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_bus.py::TestSetupCodeV2Integration -v`
Expected: FAIL

**Step 3: Write `repl_tools_v2.py`**

This file generates a Python code string similar to the current `repl_tools.py` but wires `SearchContext` with departments. The generated code must:
1. Import department classes
2. Create EventBus, EvidenceStore, QualityGate, SearchContext
3. Define the same wrapper functions with identical LM-facing signatures
4. Expose `source_registry` as a plain dict alias (REPL compat)

Due to the complexity and length of this generated code string, this task should reference the existing `rlm_search/repl_tools.py` (140 lines) and adapt it line by line. The key changes are:
- Replace `_ctx = _ToolContext(...)` with `SearchContext(...)` construction
- Replace `_ctx.progress_callback = ...` with `_ctx.bus` (EventBus handles it)
- Remove `_parent_logger_ref` wiring (EventBus replaces it)
- Add `source_registry = _ctx.evidence.live_dict` alias for REPL (NOT `as_dict()` — must be a live reference so LM sees tool writes immediately)
- Note: `source_registry` is read-only from the LM's perspective. Tools write through `register_hit()`. Direct LM writes to `source_registry["new_id"] = {...}` bypass EvidenceStore methods (dedup, score comparison) but are still visible. This matches current behavior.
- Route `init_classify()` through `ctx.llm_query()` if available (the LMHandler is already running when setup_code executes). This eliminates the shadow `get_client()` call in `subagent_tools.py:476` that bypasses usage tracking. If `ctx.llm_query` is not yet wired at init time, defer this to a follow-up task.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_event_bus.py::TestSetupCodeV2Integration -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rlm_search/repl_tools_v2.py tests/test_event_bus.py
git commit -m "feat(rlm-search): add setup code builder v2 using SearchContext + departments"
```

---

### Task 10: New api_v2.py orchestrator using all departments

**Files:**
- Create: `rlm_search/api_v2.py`
- Test: `tests/test_api_v2.py`

**Context:** The current `api.py` is 657 lines with the 5-concern `_run_search()` function and the follow-up hack. The v2 orchestrator uses SessionManager, EventBus, and SearchContext. The follow-up swap becomes `session_mgr.prepare_follow_up()`. The SSE stream uses the new router.

This task creates the new orchestrator alongside the existing one. The `_run_search_v2()` function should be ~60 lines (down from 126) because session management, streaming, and event emission are delegated to departments.

**Step 1: Write the failing test**

```python
"""tests/test_api_v2.py"""
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from rlm_search.api_v2 import app


class TestSearchV2Endpoint:
    def test_start_search_returns_ids(self):
        client = TestClient(app)
        with patch("rlm_search.api_v2._executor") as mock_exec:
            mock_exec.submit = MagicMock()
            response = client.post("/api/search", json={"query": "test question"})
        assert response.status_code == 200
        data = response.json()
        assert "search_id" in data
        assert "session_id" in data

    def test_health_endpoint(self):
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api_v2.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal `api_v2.py`**

The new orchestrator should:
1. Use `SessionManager` for session lifecycle
2. Create `EventBus` per search (not per session)
3. Pass `EventBus` to `StreamingLoggerV2`
4. Use `create_sse_router(searches)` for streaming
5. Follow-up: `session_mgr.prepare_follow_up(sid, new_bus, search_id)`
6. `_run_search_v2()`: ~60 lines, single concern (orchestration)

Implementation details: Reference `api.py:323-448` for the current flow, but delegate session management to `SessionManager`, event emission to `EventBus`, and streaming to the SSE router. The `_run_search_v2` function should look like:

```python
def _run_search_v2(search_id, query, settings, session_id):
    bus = _searches[search_id]
    session_mgr = _session_manager

    try:
        if session_mgr.get(session_id):
            # Follow-up: one method call, not 4 mutations
            rlm, session = session_mgr.prepare_follow_up(session_id, bus, search_id)
            logger = StreamingLoggerV2(..., bus=bus)
            rlm.logger = logger
            _emit_metadata(logger, rlm)
        else:
            # New session
            kw = _build_rlm_kwargs(settings, query=query)
            logger = StreamingLoggerV2(..., bus=bus)
            rlm = RLM(..., logger=logger)
            session_mgr.create_session(rlm=rlm, bus=bus, session_id=session_id)

        result = rlm.completion(query, root_prompt=query)

        # Extract sources from EvidenceStore (replaces _extract_sources() which
        # read from REPL locals snapshot). EvidenceStore.top_rated() returns
        # sources sorted by rating tier + confidence — a strict upgrade over
        # the old unordered source_registry dump.
        evidence = _get_evidence_store(rlm)  # walk persistent_env locals
        sources = evidence.top_rated(n=20) if evidence else []
        logger.mark_done(answer=result.answer, sources=sources, ...)

    except SearchCancelled:
        bus.emit("cancelled", {})
    except Exception as e:
        bus.emit("error", {"message": str(e)})
    finally:
        session_mgr.clear_active(session_id)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api_v2.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rlm_search/api_v2.py tests/test_api_v2.py
git commit -m "feat(rlm-search): add api_v2 orchestrator using departments + EventBus"
```

---

## Phase 7: Cutover + Cleanup

---

### Task 11: Migrate tools to use SearchContext (backward-compatible)

**Files:**
- Modify: `rlm_search/tools/api_tools.py`
- Modify: `rlm_search/tools/composite_tools.py`
- Modify: `rlm_search/tools/subagent_tools.py`
- Modify: `rlm_search/tools/progress_tools.py`
- Modify: `rlm_search/tools/normalize.py`

**Context:** Each tool currently reads/writes `ctx.source_registry`, `ctx.search_log`, `ctx.evaluated_ratings` directly. Migrate to `ctx.evidence.*` methods. Support both old `ToolContext` and new `SearchContext` by duck-typing (check for `.evidence` attribute).

This is done tool-by-tool. For each tool file:
1. Replace `ctx.source_registry[id] = hit` → `ctx.evidence.register_hit(hit)`
2. Replace `ctx.search_log.append(...)` → `ctx.evidence.log_search(...)`
3. Replace `ctx.evaluated_ratings[id] = ...` → `ctx.evidence.set_rating(id, ...)`
4. Replace `_compute_confidence(...)` → `ctx.quality.confidence`
5. Remove `current_parent_idx` save/restore → use `_child_scope` context manager:

```python
@contextlib.contextmanager
def _child_scope(ctx, parent_idx):
    """Safe parent index scoping — exception-safe, replaces manual save/restore."""
    saved = ctx.current_parent_idx
    ctx.current_parent_idx = parent_idx
    try:
        yield
    finally:
        ctx.current_parent_idx = saved
```

Then `research()` and `draft_answer()` in `composite_tools.py` become:
```python
with _child_scope(ctx, tc.idx):
    # ... all nested tool calls ...
```

6. Add Cascade API resilience to `api_tools.py` — currently all `requests.post()` calls have no try/except. On timeout, partial results pass as complete and the LM can't distinguish "searched and found nothing" from "search failed mid-flight":

```python
# Wrap Cascade calls with retry + error signal:
try:
    resp = requests.post(f"{ctx.api_url}/search", json=payload, headers=ctx.headers, timeout=ctx.timeout)
    resp.raise_for_status()
except (requests.Timeout, requests.ConnectionError) as exc:
    print(f"[search] ERROR: Cascade unreachable — {exc}")
    return {"results": [], "error": f"Cascade timeout: {exc}", "total": 0}
```

7. Update existing test files (`test_repl_tools.py`, `test_search_api.py`) to use `SearchContext` where they directly instantiate `ToolContext`. This prevents test rot after the cutover.

**Step 1:** Run existing tests to establish baseline

Run: `uv run pytest tests/test_repl_tools.py tests/test_search_api.py -v --tb=short`
Expected: ALL PASS (196 tests)

**Step 2-7:** Migrate each file, run tests after each to verify no regressions.

**Step 8: Commit**

```bash
git add rlm_search/tools/
git commit -m "refactor(rlm-search): migrate tools to use EvidenceStore + QualityGate methods"
```

---

### Task 12: Swap api.py → api_v2.py

**Files:**
- Rename: `rlm_search/api.py` → `rlm_search/api_legacy.py`
- Rename: `rlm_search/api_v2.py` → `rlm_search/api.py`
- Update: `Makefile` (if backend target references api module)

**Step 1:** Run full test suite one final time with v2

Run: `uv run pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 2:** Swap files

```bash
mv rlm_search/api.py rlm_search/api_legacy.py
mv rlm_search/api_v2.py rlm_search/api.py
```

**Step 3:** Run tests again

Run: `uv run pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add rlm_search/
git commit -m "refactor(rlm-search): swap to department-model api with EventBus"
```

---

### Task 13: Remove legacy files

**Files:**
- Delete: `rlm_search/api_legacy.py`
- Delete: `rlm_search/streaming_logger.py` (replaced by `streaming_v2.py`)
- Delete: `rlm_search/tools/context.py` (replaced by `context_v2.py`)
- Delete: `rlm_search/repl_tools.py` (replaced by `repl_tools_v2.py`)
- Rename: `rlm_search/streaming_v2.py` → `rlm_search/streaming_logger.py`
- Rename: `rlm_search/tools/context_v2.py` → `rlm_search/tools/context.py`
- Rename: `rlm_search/repl_tools_v2.py` → `rlm_search/repl_tools.py`
- Update all imports across the codebase

**Step 1:** Remove legacy, rename v2 → final

**Step 2:** Fix all imports

Run: `uv run ruff check --fix . && uv run ruff format .`

**Step 3:** Run full test suite

Run: `uv run pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "chore(rlm-search): remove legacy files, rename v2 → final"
```

---

### Task 14: Update system prompt — single source of truth

**Files:**
- Create: `rlm_search/prompt_constants.py`
- Modify: `rlm_search/prompts.py`
- Modify: `rlm_search/quality.py`

**Context:** Remove duplicated thresholds, reduce iteration patterns from 5 to 2, reference QualityGate thresholds by name. Remove I.M.A.M. identity duplication from tool prompts (keep it only in the system prompt). Create a shared constants module so thresholds exist in exactly one place.

**Step 1:** Create `rlm_search/prompt_constants.py` — the single source of truth for all thresholds and identity:

```python
"""rlm_search/prompt_constants.py — shared constants for prompts + QualityGate."""

# Quality thresholds
READY_THRESHOLD = 60
STALL_SEARCH_COUNT = 6
LOW_CONFIDENCE_THRESHOLD = 40

# Confidence weights (must sum to 100)
WEIGHT_RELEVANCE = 35
WEIGHT_QUALITY = 25
WEIGHT_BREADTH = 10
WEIGHT_DRAFT = 15
WEIGHT_CRITIQUE = 15

# Rating definitions
RATING_ORDER = {"RELEVANT": 0, "PARTIAL": 1, "OFF-TOPIC": 2, "UNKNOWN": 3}
```

Then update `quality.py` to import from `prompt_constants` instead of hardcoding, and update `prompts.py` to reference these constants.

**Step 2:** Edit `prompts.py`:
- Remove `confidence >= 60%` numeric threshold → replace with "when `check_progress()` returns phase `ready`"
- Reduce iteration patterns A-E to just 2: "straightforward" and "complex"
- Keep tool documentation section but note that `research()` auto-calls `check_progress()`

**Step 3:** Remove school context from tool prompts:
- `composite_tools.py:233-235` → remove inline I.M.A.M. context
- `subagent_tools.py:295-299` → remove inline school context
- `delegation_tools.py:15-16` → reference system prompt instead

**Step 4:** Run tests

Run: `uv run pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rlm_search/prompt_constants.py rlm_search/prompts.py rlm_search/quality.py rlm_search/tools/
git commit -m "refactor(rlm-search): deduplicate prompt — single source of truth for thresholds and identity"
```

---

## Phase 8: Frontend Evolution

---

### Task 15: Frontend consumes typed EventBus events

**Files:**
- Modify: `search-app/src/lib/types.ts`
- Modify: `search-app/src/lib/activityDetection.ts`
- Modify: `search-app/src/components/SearchProgress.tsx`

**Context:** The frontend currently parses stdout tags from iteration events to detect activity (`detectActivity()` in `activityDetection.ts`). With the new EventBus, `tool_start` and `tool_end` events arrive as first-class SSE events. The frontend should consume these directly.

**Step 1:** Update `types.ts` — add `ToolStartEvent`, `ToolEndEvent` types matching the EventBus schema:
```typescript
interface ToolStartEvent {
  type: "tool_start";
  data: { tool: string; args: Record<string, unknown> };
  timestamp: string;
}

interface ToolEndEvent {
  type: "tool_end";
  data: { tool: string; result_summary: Record<string, unknown>; duration_ms: number; error?: string };
  timestamp: string;
}
```

**Step 2:** Rewrite `detectActivity()` to consume `tool_start`/`tool_end` events instead of parsing stdout. The mapping is direct: `tool_start.data.tool === "research"` replaces `stdout.includes("[research]")`.

**Step 3:** Add `?replay=true` to SSE connection URL for reconnection support.

**Step 4:** Test manually in browser with `make tunnel` or `make frontend` + `make backend`.

**Step 5: Commit**

```bash
cd search-app && git add src/
git commit -m "feat(search-app): consume typed tool events from EventBus, add replay support"
```

---

## Summary: New File Structure After Redesign

```
rlm_search/
├── api.py              ← Slim orchestrator (~200 lines, down from 657)
├── bus.py              ← NEW: EventBus (single channel)
├── evidence.py         ← NEW: EvidenceStore (source_registry + search_log + ratings)
├── quality.py          ← NEW: QualityGate (confidence + critique + phases)
├── sessions.py         ← NEW: SessionManager (proper session protocol)
├── sse.py              ← NEW: SSE router (reads from EventBus, supports replay)
├── streaming_logger.py ← REWRITTEN: delegates to EventBus
├── repl_tools.py       ← REWRITTEN: builds SearchContext with departments
├── config.py           ← unchanged
├── models.py           ← unchanged
├── prompt_constants.py ← NEW: shared thresholds + weights (single source of truth)
├── prompts.py          ← SIMPLIFIED: references prompt_constants
├── kb_overview.py      ← unchanged
└── tools/
    ├── context.py      ← REPLACED: thin SearchContext (~10 fields)
    ├── api_tools.py    ← MODIFIED: uses ctx.evidence.register_hit()
    ├── composite_tools.py ← MODIFIED: uses ctx.quality.*, no manual stack
    ├── subagent_tools.py  ← MODIFIED: uses ctx.evidence.set_rating()
    ├── progress_tools.py  ← SIMPLIFIED: delegates to ctx.quality
    ├── delegation_tools.py ← MODIFIED: uses ctx.bus for child events
    ├── tracker.py      ← MODIFIED: emits to ctx.bus
    ├── normalize.py    ← MODIFIED: uses ctx.evidence.register_hit()
    ├── format_tools.py ← unchanged
    ├── kb.py           ← unchanged
    └── constants.py    ← unchanged
```

---

## Appendix: Review Additions

Changes incorporated from code review (original plan was 8/10, these bring it to 9.5/10):

| # | Addition | Where | Effort | Impact |
|---|----------|-------|--------|--------|
| 1 | Prompt caching in AnthropicClient | New Task 0 (Phase 0) | 5 lines | Highest cost savings (~60-80% on system tokens) |
| 2 | Cascade retry + error signals | Task 11 addendum | ~30 lines | LM can distinguish "no results" from "search failed" |
| 3 | `_child_scope` context manager | Task 11, explicit impl | 10 lines | Fixes fragile save/restore (exception-safe) |
| 4 | Prompt constants module | Task 14 expansion | ~20 lines | Completes "single source of truth" goal |
| 5 | `source_registry` live reference | Task 9 + EvidenceStore | ~5 lines | **Bug fix**: `as_dict()` snapshot breaks live reference contract |
| 6 | Update existing tests for SearchContext | Task 11 addendum | ~50 lines | Prevents test rot after cutover |
| 7 | `init_classify` via `llm_query` | Task 9 note | ~15 lines | Visible token tracking for classification calls |
| 8 | SearchContext `quality` init fix | Task 4 | 3 lines | **Bug fix**: `init=False` field rejected by constructor |
| 9 | Source extraction path in api_v2 | Task 10 | explicit | Clarifies that `EvidenceStore.top_rated()` replaces REPL locals walk |
| 10 | Remove dead `_categories_explored` field | Task 3 (QualityGate) | 1 line | Dead code — old diversity factor replaced by critique weight |
| 11 | Confidence formula change documented | Task 3 context | 0 lines | Weights changed: diversity(10%) + draft(20%) → critique(15%) + draft(15%) |
