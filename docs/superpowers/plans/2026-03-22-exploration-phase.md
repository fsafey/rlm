# Exploration Phase & Saturation Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `explore` phase to QualityGate that programmatically gates the transition from divergent corpus exploration to convergent answer synthesis, using a self-calibrating velocity-based saturation score.

**Architecture:** New `explore` phase sits before `continue` in QualityGate's state machine (`explore` → `continue` → `ready` → `finalize`). Saturation score uses exponentially-weighted information velocity (new unique IDs per search) + confidence gap + search floor. The score self-calibrates: narrow queries converge fast (velocity drops after 1-2 searches), broad queries explore longer (velocity stays high). `research()` relaxes tier-based gates during explore and records yield per batch. `guidance()` directs the LLM to search broadly during explore, converge during continue.

**Tech Stack:** Python 3.11, dataclasses, pytest, existing QualityGate/EvidenceStore/research() infrastructure.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `rlm_search/prompt_constants.py` | Modify | Add 5 explore constants |
| `rlm_search/quality.py` | Modify | Add explore state, saturation score, velocity, modified phase/guidance |
| `rlm_search/tools/composite_tools.py` | Modify | Record yield, gate relaxation during explore, saturation in emissions |
| `rlm_search/tools/progress_tools.py` | Modify | Add saturation_score to check_progress output |
| `rlm_search/prompts.py` | Modify | Add `explore` row to phase table, update iteration patterns |
| `tests/test_quality_gate.py` | Modify | Add TestExplorePhase class |
| `tests/test_progressive_gate.py` | Modify | Add explore-phase gate relaxation tests |

No new files created.

---

### Task 1: Add Explore Constants to prompt_constants.py

**Files:**
- Modify: `rlm_search/prompt_constants.py:24-27` (after existing saturation constants)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quality_gate.py — add at the top of file, after existing imports

def test_explore_constants_exist():
    """All explore constants are importable and have expected types."""
    from rlm_search.prompt_constants import (
        EXPLORE_SATURATION_THRESHOLD,
        EXPLORE_MIN_SEARCHES,
        VELOCITY_DECAY,
        VELOCITY_SATURATE,
        EXPLORE_EXTRA_BUDGET,
    )
    assert isinstance(EXPLORE_SATURATION_THRESHOLD, int)
    assert isinstance(EXPLORE_MIN_SEARCHES, int)
    assert isinstance(VELOCITY_DECAY, float)
    assert isinstance(VELOCITY_SATURATE, float)
    assert isinstance(EXPLORE_EXTRA_BUDGET, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py::test_explore_constants_exist -v`
Expected: FAIL with `ImportError: cannot import name 'EXPLORE_SATURATION_THRESHOLD'`

- [ ] **Step 3: Write minimal implementation**

Add to `rlm_search/prompt_constants.py` after line 27 (after `EVAL_CHECKPOINT_SEARCH`):

```python
# Explore phase: velocity-based saturation scoring
EXPLORE_SATURATION_THRESHOLD = 65   # saturation score (0-100) to exit explore phase
EXPLORE_MIN_SEARCHES = 2            # minimum searches before explore can graduate
VELOCITY_DECAY = 0.7                # exponential decay per search step (recent searches weighted more)
VELOCITY_SATURATE = 5.0             # 5+ new unique IDs per search = max velocity (1.0)
EXPLORE_EXTRA_BUDGET = 2            # additional extra_queries allowed during explore phase
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_quality_gate.py::test_explore_constants_exist -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix rlm_search/prompt_constants.py tests/test_quality_gate.py && uv run ruff format rlm_search/prompt_constants.py tests/test_quality_gate.py
git add rlm_search/prompt_constants.py tests/test_quality_gate.py
git commit -m "feat(search): add explore phase constants to prompt_constants"
```

---

### Task 2: Add Explore State & Velocity to QualityGate

**Files:**
- Modify: `rlm_search/quality.py` (add fields, `record_search_yield()`, `_info_velocity`, `saturation_score`)
- Test: `tests/test_quality_gate.py`

- [ ] **Step 1: Write the failing test for `record_search_yield`**

```python
# tests/test_quality_gate.py — new class

class TestExploreState:
    def test_record_search_yield_appends(self):
        gate = QualityGate(evidence=EvidenceStore())
        gate.record_search_yield(5)
        gate.record_search_yield(3)
        assert gate._search_yields == [5.0, 3.0]

    def test_explore_graduated_default_false(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate._explore_graduated is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py::TestExploreState -v`
Expected: FAIL with `AttributeError: 'QualityGate' object has no attribute 'record_search_yield'`

- [ ] **Step 3: Implement explore state fields and `record_search_yield()`**

Add to `QualityGate` dataclass in `rlm_search/quality.py`, after the existing `_last_critique` field (line 53):

```python
    # --- Explore phase tracking ---
    _search_yields: list[float] = dataclasses.field(default_factory=list, init=False)
    _explore_graduated: bool = dataclasses.field(default=False, init=False)

    def record_search_yield(self, new_unique: int) -> None:
        """Record how many new unique IDs a search batch produced."""
        self._search_yields.append(float(new_unique))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_quality_gate.py::TestExploreState -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for `_info_velocity`**

```python
# tests/test_quality_gate.py — add to TestExploreState class

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
        gate.record_search_yield(0)   # recent: zero
        gate.record_search_yield(0)   # recent: zero
        # Velocity should be low because recent searches are unproductive
        assert gate._info_velocity < 0.5
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py::TestExploreState::test_info_velocity_no_yields_returns_1 -v`
Expected: FAIL with `AttributeError: 'QualityGate' object has no attribute '_info_velocity'`

- [ ] **Step 7: Implement `_info_velocity` property**

Add to `QualityGate` in `rlm_search/quality.py`, after `record_search_yield()`. Import `VELOCITY_DECAY` and `VELOCITY_SATURATE` from `prompt_constants` at the top of the file.

```python
    @property
    def _info_velocity(self) -> float:
        """Exponentially-weighted new-ID rate. 0.0 = depleted, 1.0 = max novelty.

        Self-calibrates to query breadth: narrow queries deplete fast,
        broad queries sustain high velocity longer.
        """
        if not self._search_yields:
            return 1.0  # no data → assume high velocity
        n = len(self._search_yields)
        weights = [_VELOCITY_DECAY ** (n - 1 - i) for i in range(n)]
        weighted_sum = sum(y * w for y, w in zip(self._search_yields, weights))
        weight_total = sum(weights)
        avg_yield = weighted_sum / weight_total
        return min(avg_yield / _VELOCITY_SATURATE, 1.0)
```

Add imports at top of `quality.py` (alongside existing prompt_constants imports):

```python
from rlm_search.prompt_constants import (
    VELOCITY_DECAY as _VELOCITY_DECAY,
)
from rlm_search.prompt_constants import (
    VELOCITY_SATURATE as _VELOCITY_SATURATE,
)
```

- [ ] **Step 8: Run velocity tests to verify they pass**

Run: `uv run pytest tests/test_quality_gate.py::TestExploreState -v -k "velocity"`
Expected: All 4 velocity tests PASS

- [ ] **Step 9: Write the failing test for `saturation_score`**

```python
# tests/test_quality_gate.py — add to TestExploreState class

    def test_saturation_score_zero_initially(self):
        gate = QualityGate(evidence=EvidenceStore())
        assert gate.saturation_score == 0

    def test_saturation_score_rises_with_low_velocity(self):
        """When searches stop finding new things, saturation rises."""
        evidence = EvidenceStore()
        # Add some searches and evidence to build confidence
        for i in range(4):
            evidence.register_hit(
                {"id": f"h{i}", "question": "Q", "answer": "A", "score": 0.7, "metadata": {}}
            )
            evidence.set_rating(f"h{i}", "RELEVANT", confidence=3)
            evidence.log_search(query=f"q{i}", num_results=3)
        gate = QualityGate(evidence=evidence)
        # Simulate depleted velocity
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
```

- [ ] **Step 10: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py::TestExploreState::test_saturation_score_zero_initially -v`
Expected: FAIL with `AttributeError: 'QualityGate' object has no attribute 'saturation_score'`

- [ ] **Step 11: Implement `saturation_score` property**

Add to `QualityGate` in `rlm_search/quality.py`, after `_info_velocity`. Import `EXPLORE_MIN_SEARCHES` from `prompt_constants`.

```python
    @property
    def saturation_score(self) -> int:
        """Exploration saturation (0-100). High = territory well-mapped, time to converge.

        Three factors:
        - Velocity decay (45): inverted info velocity — when searches stop finding
          new things, saturation rises.
        - Confidence (40): evidence quality already captured by existing 5-factor score.
        - Search floor (15): minimum searches before explore can graduate.
        """
        n_searches = len(self.evidence.search_log)
        if n_searches == 0:
            return 0

        velocity_component = int(45 * (1.0 - self._info_velocity))
        confidence_component = int(40 * min(self.confidence / 100.0, 1.0))
        floor_component = int(15 * min(n_searches / _EXPLORE_MIN_SEARCHES, 1.0))

        return min(100, velocity_component + confidence_component + floor_component)
```

Add import:

```python
from rlm_search.prompt_constants import (
    EXPLORE_MIN_SEARCHES as _EXPLORE_MIN_SEARCHES,
)
```

- [ ] **Step 12: Run saturation score tests to verify they pass**

Run: `uv run pytest tests/test_quality_gate.py::TestExploreState -v -k "saturation"`
Expected: All 3 saturation tests PASS

- [ ] **Step 13: Lint and commit**

```bash
uv run ruff check --fix rlm_search/quality.py tests/test_quality_gate.py && uv run ruff format rlm_search/quality.py tests/test_quality_gate.py
git add rlm_search/quality.py tests/test_quality_gate.py
git commit -m "feat(search): add explore state, velocity, and saturation score to QualityGate"
```

---

### Task 3: Add Explore Phase to QualityGate State Machine

**Files:**
- Modify: `rlm_search/quality.py` (modify `phase` property, `guidance()` method)
- Test: `tests/test_quality_gate.py`

- [ ] **Step 1: Write the failing test for explore phase**

```python
# tests/test_quality_gate.py — new class

class TestExplorePhase:
    def test_initial_phase_is_explore(self):
        """Fresh gate with some searches but no velocity data → explore."""
        evidence = EvidenceStore()
        evidence.log_search(query="q1", num_results=5)
        gate = QualityGate(evidence=evidence)
        # No yields recorded yet → velocity=1.0, saturation low
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
        # Saturation should exceed threshold → not explore
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
        # Force graduation via depleted velocity
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        gate.record_search_yield(0)
        _ = gate.phase  # triggers graduation
        assert gate._explore_graduated is True
        # Now add high-velocity data — should NOT return to explore
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
        """Zero searches → saturation is 0, but phase should not be explore
        since there's nothing to explore yet. It should be continue."""
        gate = QualityGate(evidence=EvidenceStore())
        # No searches at all → saturation_score returns 0
        # But phase logic: no searches means nothing to explore
        assert gate.phase == "continue"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quality_gate.py::TestExplorePhase -v`
Expected: FAIL — `test_initial_phase_is_explore` returns "continue" instead of "explore"

- [ ] **Step 3: Implement modified `phase` property**

Replace the `phase` property in `rlm_search/quality.py` (lines 141-156). Import `EXPLORE_SATURATION_THRESHOLD`.

```python
    @property
    def phase(self) -> str:
        """Determine current search phase from evidence state.

        Phase progression: explore → continue → ready → finalize
        Stalled overrides explore (don't explore a desert).
        """
        n_searches = len(self.evidence.search_log)
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)

        if n_searches >= self.STALL_SEARCH_COUNT and relevant < 2:
            return "stalled"

        # Explore phase: at least 1 search, not yet graduated, below saturation
        if not self._explore_graduated and n_searches > 0:
            if self.saturation_score >= _EXPLORE_SATURATION_THRESHOLD:
                self._explore_graduated = True
                # Fall through to continue/ready/finalize
            else:
                return "explore"

        conf = self.confidence
        if conf >= self.READY_THRESHOLD:
            if self._has_draft and self._last_critique and self._last_critique["passed"]:
                return "finalize"
            return "ready"

        return "continue"
```

Add import:

```python
from rlm_search.prompt_constants import (
    EXPLORE_SATURATION_THRESHOLD as _EXPLORE_SATURATION_THRESHOLD,
)
```

- [ ] **Step 4: Run explore phase tests to verify they pass**

Run: `uv run pytest tests/test_quality_gate.py::TestExplorePhase -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run ALL existing QualityGate tests to verify no regressions**

Run: `uv run pytest tests/test_quality_gate.py -v`
Expected: All existing tests still PASS. Key check: `TestQualityGatePhase::test_phase_continue_below_threshold` — a gate with 1 PARTIAL hit and 0 searches should return "continue" (not "explore", since n_searches=0).

- [ ] **Step 6: Write the failing test for explore guidance**

```python
# tests/test_quality_gate.py — add to TestExplorePhase class

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
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py::TestExplorePhase::test_explore_guidance_says_dont_draft -v`
Expected: FAIL — guidance() doesn't handle "explore" phase yet

- [ ] **Step 8: Implement modified `guidance()` method**

Modify `guidance()` in `rlm_search/quality.py` (lines 160-180). Add the `explore` branch at the top of the method, before the `stalled` check:

```python
    def guidance(self) -> str:
        """Return guidance string for the LM based on current phase."""
        p = self.phase
        if p == "explore":
            sat = self.saturation_score
            return (
                f"Explore phase (saturation {sat}%). "
                "Run broad research() with diverse query angles and varied filters. "
                "Do NOT draft yet — map the territory first."
            )
        if p == "stalled":
            return (
                "Evidence insufficient after multiple searches."
                " Try reformulate() or broaden filters."
            )
        if p == "ready":
            return "Evidence sufficient. Call draft_answer() to synthesize."
        if p == "finalize":
            return "Draft passed critique. Call FINAL_VAR(answer) to deliver."
        # continue
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)
        if relevant == 0:
            return "No relevant results yet. Try different query angles or broader filters."
        return (
            f"{relevant} relevant sources found."
            " Continue searching for more evidence or draft if confident."
        )
```

- [ ] **Step 9: Run guidance tests to verify they pass**

Run: `uv run pytest tests/test_quality_gate.py::TestExplorePhase -v`
Expected: All 7 tests PASS

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check --fix rlm_search/quality.py tests/test_quality_gate.py && uv run ruff format rlm_search/quality.py tests/test_quality_gate.py
git add rlm_search/quality.py tests/test_quality_gate.py
git commit -m "feat(search): add explore phase to QualityGate state machine"
```

---

### Task 4: Integrate Explore Phase into research()

**Files:**
- Modify: `rlm_search/tools/composite_tools.py` (record yield, gate relaxation)
- Test: `tests/test_progressive_gate.py`

- [ ] **Step 1: Write the failing test for yield recording**

```python
# tests/test_progressive_gate.py — new class at end of file (before the import)

class TestExploreYieldRecording:
    """research() should call record_search_yield() after each search batch."""

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_yields_recorded_per_batch(self, mock_search, mock_eval):
        ctx = _make_ctx()
        mock_search.side_effect = [
            _make_results([1, 2, 3]),       # main: 3 new
            _make_results([1, 2, 4]),       # extra 1: 1 new (id 4)
        ]
        mock_eval.return_value = _make_eval_ratings([1, 2, 3], "PARTIAL")

        research(ctx, "test query", extra_queries=[{"query": "v1"}])

        # Should have recorded 2 yields
        assert len(ctx.quality._search_yields) == 2
        assert ctx.quality._search_yields[0] == 3.0  # main: 3 new
        assert ctx.quality._search_yields[1] == 1.0  # extra: 1 new
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_progressive_gate.py::TestExploreYieldRecording -v`
Expected: FAIL — `_search_yields` is empty (research doesn't call `record_search_yield` yet)

- [ ] **Step 3: Implement yield recording in research()**

Modify `rlm_search/tools/composite_tools.py`. Two places need `record_search_yield()` calls:

**After the main query search (after line 208, after `search_count += 1`, still inside the `try:` block):**

```python
                    # Record yield for explore phase velocity tracking
                    if ctx.quality:
                        ctx.quality.record_search_yield(len(batch_ids))
```

Note: for the main query, all results are new (seen_ids was empty), so yield = len(batch_ids).

**After the novelty tracking block in extra_queries loop (after line 295, after `consecutive_low = 0`):**

```python
                        # Record yield for explore phase velocity tracking
                        if ctx.quality:
                            ctx.quality.record_search_yield(new_unique)
```

`new_unique` is already computed at line 285.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_progressive_gate.py::TestExploreYieldRecording -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for gate relaxation during explore**

```python
# tests/test_progressive_gate.py — new class

class TestExploreGateRelaxation:
    """During explore phase, strong/medium tier gates should NOT stop search."""

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_strong_tier_does_not_stop_during_explore(self, mock_search, mock_eval):
        """Even with 6+ RELEVANT (strong tier), explore phase lets extras run."""
        ctx = _make_ctx()
        # Pre-seed: 8 RELEVANT results at high score → strong tier
        _seed_evidence(ctx, list(range(1, 9)), score=0.85)
        # Force explore phase: gate not graduated, has searches
        assert ctx.quality.phase == "explore"

        mock_search.side_effect = [
            _make_results(list(range(1, 9)), score=0.85),  # main
            _make_results([9, 10], score=0.85),             # extra 1: 2 new
            _make_results([11, 12], score=0.85),            # extra 2: 2 new
        ]
        mock_eval.return_value = _make_eval_ratings(list(range(1, 9)), "RELEVANT")

        result = research(
            ctx,
            "test query",
            extra_queries=[{"query": "v1"}, {"query": "v2"}],
        )

        # All 3 searches should run (explore overrides strong gate)
        assert mock_search.call_count == 3
        assert result["search_count"] == 3

    @patch("rlm_search.tools.composite_tools.evaluate_results")
    @patch("rlm_search.tools.composite_tools.search")
    def test_gate_applies_after_graduation(self, mock_search, mock_eval):
        """After explore graduates, tier gates resume normal behavior."""
        ctx = _make_ctx()
        _seed_evidence(ctx, list(range(1, 9)), score=0.85)
        # Force graduation
        ctx.quality._explore_graduated = True
        assert ctx.quality.phase != "explore"

        mock_search.side_effect = [
            _make_results(list(range(1, 9)), score=0.85),
            _make_results([9, 10]),
        ]
        mock_eval.return_value = _make_eval_ratings(list(range(1, 9)), "RELEVANT")

        result = research(
            ctx,
            "test query",
            extra_queries=[{"query": "should not run"}],
        )

        # Strong tier → stop after main query (normal gating resumes)
        assert mock_search.call_count == 1
        assert result["search_count"] == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_progressive_gate.py::TestExploreGateRelaxation::test_strong_tier_does_not_stop_during_explore -v`
Expected: FAIL — search stops at 1 call (strong gate fires during explore)

- [ ] **Step 7: Implement gate relaxation during explore**

Modify `rlm_search/tools/composite_tools.py`. Add an `is_exploring` flag after the search loop setup, and use it to skip tier gates.

**After line 189 (after `is_w3 = ctx.pipeline_mode == "w3"`):**

```python
            is_exploring = bool(ctx.quality and ctx.quality.phase == "explore")
```

**Wrap the strong-tier gate check after main query (lines 220-230) with `if not is_exploring:`:**

```python
                # Check tier after first evaluation
                if not is_exploring:
                    tier = ctx.quality.critique_tier if ctx.quality else "weak"
                    if tier == "strong":
                        print(
                            f"[research] GATE: strong tier after {search_count} searches, "
                            f"stopping extra queries"
                        )
                        _gate_stopped = True
                        _emit(ctx, "research", "gate_stopped", {
                            "reason": "strong", "search_count": search_count, "tier": tier,
                        })
                        break
```

**Wrap the strong/medium gates in the extra_queries loop (lines 234-258) similarly:**

```python
                    if not is_exploring:
                        # Gate check BEFORE issuing search
                        tier = ctx.quality.critique_tier if ctx.quality else "weak"

                        if tier == "strong":
                            # ... (existing strong gate code, unchanged)

                        if tier == "medium":
                            # ... (existing medium gate code, unchanged)
```

Note: the `consecutive_low >= SATURATION_CONSECUTIVE_MAX` gate (line 260) should still apply during explore — genuine depletion means stop even during explore.

Also import `EXPLORE_EXTRA_BUDGET` from `prompt_constants` and adjust medium budget during explore.

**After the `is_exploring` definition (right after `is_exploring = bool(...)`):**

```python
            if is_exploring:
                medium_budget = MEDIUM_EXTRA_BUDGET + EXPLORE_EXTRA_BUDGET
```

This must be AFTER `is_exploring` is defined and AFTER `medium_budget = MEDIUM_EXTRA_BUDGET` (line 172).

And add the import at the top:

```python
from rlm_search.prompt_constants import (
    EXPLORE_EXTRA_BUDGET,
)
```

- [ ] **Step 8: Run gate relaxation tests to verify they pass**

Run: `uv run pytest tests/test_progressive_gate.py::TestExploreGateRelaxation -v`
Expected: Both tests PASS

- [ ] **Step 9: Run ALL progressive gate tests to verify no regressions**

Run: `uv run pytest tests/test_progressive_gate.py -v`
Expected: All existing tests still PASS. The existing `TestTierGating::test_stops_on_strong_tier` should still pass because `_seed_evidence` logs a search, and the pre-seeded evidence with depleted velocity (no `record_search_yield` with high values) means saturation may be high enough to graduate → gates resume.

If `test_stops_on_strong_tier` fails because explore hasn't graduated: the test pre-seeds 1 search with 8 hits and no yield data, so `_info_velocity` returns 1.0 (high) and saturation stays low → stuck in explore. Fix: add `ctx.quality._explore_graduated = True` to the existing `_seed_evidence` helper OR after the `_seed_evidence` call in that specific test. **Preferred**: add it to `test_stops_on_strong_tier` specifically, since that test's intent is to test tier gating, not explore behavior.

```python
    # In test_stops_on_strong_tier, after _seed_evidence:
    ctx.quality._explore_graduated = True
```

Similarly check `test_caps_extras_on_medium_tier` — same fix if needed.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check --fix rlm_search/tools/composite_tools.py tests/test_progressive_gate.py && uv run ruff format rlm_search/tools/composite_tools.py tests/test_progressive_gate.py
git add rlm_search/tools/composite_tools.py tests/test_progressive_gate.py
git commit -m "feat(search): integrate explore phase into research() with gate relaxation"
```

---

### Task 5: Update check_progress to Surface Saturation Score

**Files:**
- Modify: `rlm_search/tools/progress_tools.py`
- Test: existing behavior verified via integration — no new test file needed

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quality_gate.py — add to TestExplorePhase class

def test_check_progress_includes_saturation_in_explore(self):
    """check_progress() should include saturation_score when in explore phase."""
    from rlm_search.tools.context import SearchContext
    from rlm_search.tools.progress_tools import check_progress
    from unittest.mock import MagicMock

    ctx = SearchContext(api_url="http://test:8095")
    ctx.llm_query = MagicMock(return_value="mocked")
    ctx.evidence.log_search(query="q1", num_results=5)
    assert ctx.quality.phase == "explore"

    result = check_progress(ctx)

    assert "saturation_score" in result
    assert isinstance(result["saturation_score"], int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py::TestExplorePhase::test_check_progress_includes_saturation_in_explore -v`
Expected: FAIL — `"saturation_score" not in result`

- [ ] **Step 3: Implement saturation_score in check_progress**

Modify `rlm_search/tools/progress_tools.py`. In the `check_progress()` function:

**After the confidence/phase/guidance if/else block (after line 226, before the audit trail section at line 228), add saturation_score extraction:**

```python
        # -- Saturation (explore phase) --
        saturation_score = None
        if quality is not None:
            saturation_score = quality.saturation_score
```

**In the stdout section (around line 233), add saturation to the explore-phase output:**

```python
        if saturation_score is not None and phase == "explore":
            print(f"  saturation={saturation_score}%")
```

**In `tc.set_summary()` (around line 240), add:**

```python
                "saturation_score": saturation_score,
```

**In the return dict (around line 253), add:**

```python
            "saturation_score": saturation_score,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_quality_gate.py::TestExplorePhase::test_check_progress_includes_saturation_in_explore -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix rlm_search/tools/progress_tools.py tests/test_quality_gate.py && uv run ruff format rlm_search/tools/progress_tools.py tests/test_quality_gate.py
git add rlm_search/tools/progress_tools.py tests/test_quality_gate.py
git commit -m "feat(search): surface saturation_score in check_progress output"
```

---

### Task 6: Update System Prompt Phase Table

**Files:**
- Modify: `rlm_search/prompts.py` (phase table + iteration patterns)

- [ ] **Step 1: Update the phase table**

In `rlm_search/prompts.py`, the phase table is at lines 108-114. Add the `explore` row:

```python
| Phase | Meaning | Action |
|-------|---------|--------|
| `explore` | Mapping corpus territory (saturation < 65%) | **Search broadly.** Run research() with diverse query angles and varied filters. Do NOT draft — map the territory first. |
| `ready` | Sufficient evidence gathered | **Draft now.** Call `draft_answer()`. |
| `continue` | Room to improve evidence | **Follow the `guidance` string.** It suggests specific queries, filters, or clusters to try next. |
| `stalled` | Many searches, few relevant results | **Change strategy.** Try a different category, drop filters, or use `reformulate()`. Follow `guidance`. |
| `repeating` | Low query diversity (same searches) | **New angles needed.** Use `reformulate()` or try synonyms/related terms. |
| `finalize` | Draft passed critique | **Emit answer.** Call `FINAL_VAR(answer)`. |
```

- [ ] **Step 2: Add saturation to key signals section**

After line 121 (`Searches tried:` line), add:

```python
- `saturation=N%` — corpus territory coverage (explore phase only; higher = more territory mapped)
```

- [ ] **Step 3: Update iteration budget section**

In `build_system_prompt()` (line 242-244), add explore-phase behavior:

```python
- **check_progress() returns phase 'explore'** → search broadly with diverse angles, do NOT draft yet
- **check_progress() returns phase 'ready'** → draft immediately (don't waste iterations)
```

- [ ] **Step 4: Run full test suite to verify no regressions**

Run: `uv run pytest -v`
Expected: All tests pass. The prompts are strings — no functional tests to break.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix rlm_search/prompts.py && uv run ruff format rlm_search/prompts.py
git add rlm_search/prompts.py
git commit -m "docs(search): add explore phase to system prompt phase table"
```

---

### Task 7: Full Integration Test & Regression Check

**Files:**
- Test: all test files

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -v
```

Expected: All tests pass (existing + new).

- [ ] **Step 2: Run ruff check on all modified files**

```bash
uv run ruff check --fix rlm_search/prompt_constants.py rlm_search/quality.py rlm_search/tools/composite_tools.py rlm_search/tools/progress_tools.py rlm_search/prompts.py tests/test_quality_gate.py tests/test_progressive_gate.py && uv run ruff format rlm_search/prompt_constants.py rlm_search/quality.py rlm_search/tools/composite_tools.py rlm_search/tools/progress_tools.py rlm_search/prompts.py tests/test_quality_gate.py tests/test_progressive_gate.py
```

Expected: No issues.

- [ ] **Step 3: Verify the explore→continue→ready→finalize progression end-to-end**

Manual verification: read the final `quality.py` and trace the state machine:
1. Fresh gate + 1 search → `explore` (velocity=1.0, saturation low)
2. Multiple searches, velocity drops → saturation rises → `explore` graduates → `continue`
3. Confidence crosses 60 → `ready`
4. Draft + critique pass → `finalize`
5. 6+ searches, <2 relevant → `stalled` (overrides explore)

- [ ] **Step 4: Commit final state if any lint fixes were needed**

```bash
git add -A && git commit -m "chore(search): lint fixes for explore phase integration"
```

Only run if Step 2 produced changes.

---

## Design Decisions & Rationale

**Why velocity-based scoring (not category/cluster coverage):**
Category/cluster scoring only works if the LLM uses those specific filters. Velocity measures what matters directly — are we still finding new things? — regardless of how the LLM formulates its searches.

**Why first-class phase (not sub-state in `continue`):**
Explicit phases make the state machine legible to both the LLM (via guidance) and developers (via phase property). A hidden sub-state would require reading implementation details to understand behavior.

**Why one-way graduation:**
Oscillation between explore and converge confuses the LLM and wastes budget. Once you've mapped enough territory, commit to convergence.

**Why tier gates relax during explore (not removed):**
The tier-based gates (strong/medium) are battle-tested. We relax them during explore to allow broader searching, then re-enable after graduation. The consecutive_low saturation gate still applies during explore — genuine depletion means stop.

**Why `stalled` overrides `explore`:**
If 6+ searches yield <2 relevant, the corpus is sparse for this query. Exploring more is wasteful — change strategy instead.
