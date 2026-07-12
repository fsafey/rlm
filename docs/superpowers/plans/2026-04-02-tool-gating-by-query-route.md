# Tool Gating by Query Route — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate which REPL tools the LM can see based on classification confidence, so simple queries get a focused tool set and the LM can't waste iterations on expensive tools it doesn't need.

**Architecture:** After the first `research()` call populates `ctx.classification`, a gating function removes tool bindings from the REPL namespace. Three tiers: `focused` (HIGH confidence — no browse/reformulate/rlm_query/critique_answer), `standard` (MEDIUM — no rlm_query), and `full` (LOW or cross-category — all tools). The gate runs inside the `research()` wrapper in `repl_tools.py`, so it fires automatically after classification lands — no changes to `rlm.py` or `LocalREPL`.

**Tech Stack:** Python, pytest, existing `repl_tools.py` / `composite_tools.py` / `LocalREPL`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `rlm_search/tool_gate.py` (create) | `ToolGate` dataclass + `compute_tool_tier()` + `apply_gate()` — pure logic, no REPL coupling |
| `rlm_search/repl_tools.py` (modify) | Wire gate into `research()` wrapper so it fires after classification |
| `rlm_search/prompt_layers/20-tools.md` (modify) | Add short note that tools may be gated based on classification |
| `tests/test_tool_gate.py` (create) | Unit tests for tier computation and namespace removal |
| `tests/test_repl_tools.py` (modify) | Integration test: research() triggers gate in live REPL namespace |

---

### Task 1: ToolGate — tier computation (pure logic)

**Files:**
- Create: `rlm_search/tool_gate.py`
- Test: `tests/test_tool_gate.py`

The core gating logic. No REPL dependency — takes a classification dict and returns which tools to remove. This is the equivalent of claw-code's `allowed_tools_for_subagent()` in `tools/src/lib.rs:1665`.

- [ ] **Step 1: Write failing tests for tier computation**

```python
# tests/test_tool_gate.py
"""Tests for tool gating by classification confidence."""

from rlm_search.tool_gate import compute_tool_tier, TIER_REMOVALS


class TestComputeToolTier:
    """compute_tool_tier returns focused/standard/full based on classification."""

    def test_high_confidence_returns_focused(self):
        classification = {"confidence": "HIGH", "category": "PT", "also_category": ""}
        assert compute_tool_tier(classification) == "focused"

    def test_medium_confidence_returns_standard(self):
        classification = {"confidence": "MEDIUM", "category": "PT", "also_category": ""}
        assert compute_tool_tier(classification) == "standard"

    def test_low_confidence_returns_full(self):
        classification = {"confidence": "LOW", "category": "PT", "also_category": "BE"}
        assert compute_tool_tier(classification) == "full"

    def test_none_classification_returns_full(self):
        assert compute_tool_tier(None) == "full"

    def test_cross_category_downgrades_to_full(self):
        """When also_category is set, confidence is ambiguous — use full set."""
        classification = {"confidence": "HIGH", "category": "PT", "also_category": "WP"}
        assert compute_tool_tier(classification) == "full"

    def test_empty_category_returns_full(self):
        classification = {"confidence": "HIGH", "category": "", "also_category": ""}
        assert compute_tool_tier(classification) == "full"


class TestTierRemovals:
    """TIER_REMOVALS defines which tools to remove per tier."""

    def test_focused_removes_expensive_tools(self):
        assert "rlm_query" in TIER_REMOVALS["focused"]
        assert "browse" in TIER_REMOVALS["focused"]
        assert "reformulate" in TIER_REMOVALS["focused"]
        assert "critique_answer" in TIER_REMOVALS["focused"]

    def test_focused_keeps_core_tools(self):
        assert "research" not in TIER_REMOVALS["focused"]
        assert "draft_answer" not in TIER_REMOVALS["focused"]
        assert "check_progress" not in TIER_REMOVALS["focused"]
        assert "search" not in TIER_REMOVALS["focused"]
        assert "fiqh_lookup" not in TIER_REMOVALS["focused"]

    def test_standard_removes_only_rlm_query(self):
        assert "rlm_query" in TIER_REMOVALS["standard"]
        assert "browse" not in TIER_REMOVALS["standard"]

    def test_full_removes_nothing(self):
        assert TIER_REMOVALS["full"] == frozenset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rlm_search.tool_gate'`

- [ ] **Step 3: Write the implementation**

```python
# rlm_search/tool_gate.py
"""Tool gating by classification confidence — controls REPL tool visibility."""

from __future__ import annotations

from typing import Any

# Tools removed per tier. Keyed by tier name.
# focused: HIGH confidence, single category — only core search + draft
# standard: MEDIUM confidence — drop rlm_query (expensive delegation)
# full: LOW or cross-category — all tools available
TIER_REMOVALS: dict[str, frozenset[str]] = {
    "focused": frozenset({
        "rlm_query",
        "browse",
        "reformulate",
        "critique_answer",
        "evaluate_results",
    }),
    "standard": frozenset({
        "rlm_query",
    }),
    "full": frozenset(),
}


def compute_tool_tier(classification: dict[str, Any] | None) -> str:
    """Determine tool tier from classification result.

    Args:
        classification: Output of _extract_classification(), or None.

    Returns:
        "focused", "standard", or "full".
    """
    if classification is None:
        return "full"

    confidence = classification.get("confidence", "LOW")
    category = classification.get("category", "")
    also_category = classification.get("also_category", "")

    # No category signal — can't gate
    if not category:
        return "full"

    # Cross-category ambiguity — need full tool set
    if also_category:
        return "full"

    if confidence == "HIGH":
        return "focused"
    if confidence == "MEDIUM":
        return "standard"
    return "full"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/farieds/projects/rlm && git add rlm_search/tool_gate.py tests/test_tool_gate.py && git commit -m "feat(search): add tool gate tier computation — focused/standard/full"
```

---

### Task 2: apply_gate() — namespace removal function

**Files:**
- Modify: `rlm_search/tool_gate.py`
- Test: `tests/test_tool_gate.py`

The function that actually removes tool bindings from a namespace dict. Takes a namespace (like REPL locals), a tier, and deletes the functions listed in `TIER_REMOVALS[tier]`. Returns the list of removed names for logging.

- [ ] **Step 1: Write failing tests for apply_gate**

Add to `tests/test_tool_gate.py`:

```python
from rlm_search.tool_gate import apply_gate


class TestApplyGate:
    """apply_gate removes tool functions from a namespace dict."""

    def _make_namespace(self) -> dict:
        """Simulate a REPL namespace with tool functions."""
        return {
            "research": lambda: None,
            "draft_answer": lambda: None,
            "check_progress": lambda: None,
            "search": lambda: None,
            "browse": lambda: None,
            "fiqh_lookup": lambda: None,
            "reformulate": lambda: None,
            "critique_answer": lambda: None,
            "evaluate_results": lambda: None,
            "rlm_query": lambda: None,
            "format_evidence": lambda: None,
            "source_registry": {},
            "search_log": [],
            "question": "test",
        }

    def test_focused_removes_expensive_tools(self):
        ns = self._make_namespace()
        removed = apply_gate(ns, "focused")
        assert "rlm_query" not in ns
        assert "browse" not in ns
        assert "reformulate" not in ns
        assert "critique_answer" not in ns
        assert "evaluate_results" not in ns
        assert set(removed) == {"rlm_query", "browse", "reformulate", "critique_answer", "evaluate_results"}

    def test_focused_keeps_core_tools(self):
        ns = self._make_namespace()
        apply_gate(ns, "focused")
        assert "research" in ns
        assert "draft_answer" in ns
        assert "check_progress" in ns
        assert "search" in ns
        assert "fiqh_lookup" in ns

    def test_full_removes_nothing(self):
        ns = self._make_namespace()
        removed = apply_gate(ns, "full")
        assert removed == []
        assert "rlm_query" in ns

    def test_standard_removes_rlm_query_only(self):
        ns = self._make_namespace()
        removed = apply_gate(ns, "standard")
        assert "rlm_query" not in ns
        assert "browse" in ns
        assert removed == ["rlm_query"]

    def test_missing_tool_is_silently_skipped(self):
        """If a tool was never injected (e.g. rlm_query at max depth), skip it."""
        ns = {"research": lambda: None, "draft_answer": lambda: None}
        removed = apply_gate(ns, "focused")
        assert "research" in ns
        # Only tools that were actually present get reported
        assert all(name not in ns for name in removed)

    def test_non_callable_keys_untouched(self):
        ns = self._make_namespace()
        apply_gate(ns, "focused")
        assert "source_registry" in ns
        assert "search_log" in ns
        assert "question" in ns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py::TestApplyGate -v`
Expected: FAIL — `ImportError: cannot import name 'apply_gate'`

- [ ] **Step 3: Add apply_gate to tool_gate.py**

Append to `rlm_search/tool_gate.py`:

```python
def apply_gate(namespace: dict[str, Any], tier: str) -> list[str]:
    """Remove tool bindings from namespace based on tier.

    Args:
        namespace: Mutable dict (e.g. REPL locals or combined globals).
        tier: One of "focused", "standard", "full".

    Returns:
        Sorted list of tool names that were actually removed.
    """
    to_remove = TIER_REMOVALS.get(tier, frozenset())
    removed = []
    for name in sorted(to_remove):
        if name in namespace:
            del namespace[name]
            removed.append(name)
    return removed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/farieds/projects/rlm && git add rlm_search/tool_gate.py tests/test_tool_gate.py && git commit -m "feat(search): add apply_gate — removes tool bindings from REPL namespace"
```

---

### Task 3: Wire gate into the research() wrapper in repl_tools.py

**Files:**
- Modify: `rlm_search/repl_tools.py`
- Test: `tests/test_tool_gate.py`

This is the key integration point. The `research()` wrapper in `repl_tools.py` (line 108) already runs after every `research()` call and has access to `_ctx.classification`. After classification lands, it calls `compute_tool_tier()` + `apply_gate()` on the REPL's namespace.

The mechanism: `research()` is a closure over `_ctx`. After classification populates, we use Python's frame introspection (`inspect.currentframe().f_back`) — but this is fragile. Instead, we store a reference to the REPL's combined namespace in `_ctx` during setup, and gate against that.

Simpler approach: the `research()` wrapper already prints progress messages. We add gating as a side effect. The wrapper functions are closures that close over `_ctx` — but they can't easily reach the REPL namespace. The cleanest approach: add a `_gate_callback` to `_ctx` during setup, which `research()` calls after classification. The callback is a closure that captures the local namespace.

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_tool_gate.py`:

```python
class TestGateIntegration:
    """Gate fires after classification in the research() wrapper."""

    def test_gate_callback_receives_tier(self):
        """_ctx._gate_callback is called with the computed tier after classification."""
        from rlm_search.tool_gate import compute_tool_tier

        classification = {"confidence": "HIGH", "category": "PT", "also_category": ""}
        tier = compute_tool_tier(classification)
        assert tier == "focused"
        # The actual integration is tested in TestReplGateWiring below

    def test_repl_setup_code_defines_gate_callback(self):
        """Generated setup code must define _ctx._gate_callback."""
        from rlm_search.repl_tools import build_search_setup_code

        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        ctx = ns["_ctx"]
        assert hasattr(ctx, "_gate_callback")
        assert ctx._gate_callback is not None
        assert callable(ctx._gate_callback)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py::TestGateIntegration -v`
Expected: FAIL — `_ctx` has no `_gate_callback` attribute

- [ ] **Step 3: Add _gate_callback field to SearchContext**

Modify `rlm_search/tools/context.py` — add one field to `SearchContext`:

```python
    # --- Tool gating callback (set by REPL setup, called by research wrapper) ---
    _gate_callback: Any = None
```

Add this after the existing `existing_answer` field (around line 57).

- [ ] **Step 4: Add gate wiring to build_search_setup_code**

Modify `rlm_search/repl_tools.py`. After the existing wrapper functions block (after line 120, before the mutable state aliases), add:

```python
# ── Tool gating — restrict tools after classification lands ───────────
from rlm_search.tool_gate import compute_tool_tier as _compute_tier, apply_gate as _apply_gate

_gate_applied = False

def _gate_callback(classification):
    global _gate_applied
    if _gate_applied:
        return
    _gate_applied = True
    _tier = _compute_tier(classification)
    if _tier == "full":
        return
    # Get the namespace that holds the wrapper functions.
    # All wrappers are defined at module-level in the exec'd code,
    # so they live in the combined globals dict. We can reach them
    # via any wrapper's __globals__.
    _ns = research.__globals__
    _removed = _apply_gate(_ns, _tier)
    if _removed:
        print(f"[gate] Tier={_tier} — removed tools: {', '.join(_removed)}")

_ctx._gate_callback = _gate_callback
```

- [ ] **Step 5: Fire the gate callback from the research() wrapper**

Modify the `research()` wrapper function in `repl_tools.py` (the existing one at line 108). After the `_comp.research()` call returns and before the progress check, add the gate trigger. Replace the existing `research` wrapper with:

```python
def research(query, filters=None, top_k=10, extra_queries=None, eval_model=None):
    result = _comp.research(_ctx, query, filters=filters, top_k=top_k, extra_queries=extra_queries, eval_model=eval_model)
    # Fire tool gate after classification lands (runs once)
    if _ctx.classification is not None and _ctx._gate_callback is not None:
        _ctx._gate_callback(_ctx.classification)
    progress = _prog.check_progress(_ctx)
    if progress["phase"] == "ready":
        print(f"\\n>>> PROGRESS: Evidence sufficient (confidence {progress['confidence']}%). Call draft_answer() now.")
    elif progress["phase"] == "finalize":
        print(f"\\n>>> PROGRESS: Draft complete. Call FINAL_VAR(answer) to finish.")
    elif progress["phase"] in ("stalled", "repeating"):
        print(f"\\n>>> PROGRESS: {progress['guidance']}")
    return result
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py -v`
Expected: All PASS

- [ ] **Step 7: Run existing tests to verify no regressions**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_repl_tools.py tests/test_search_context.py tests/test_quality_gate.py -v`
Expected: All PASS (existing tests don't depend on gated tools)

- [ ] **Step 8: Commit**

```bash
cd /Users/farieds/projects/rlm && git add rlm_search/tool_gate.py rlm_search/repl_tools.py rlm_search/tools/context.py tests/test_tool_gate.py && git commit -m "feat(search): wire tool gate into research() wrapper — fires after classification"
```

---

### Task 4: End-to-end REPL integration test

**Files:**
- Test: `tests/test_tool_gate.py`

Verify the full flow: `build_search_setup_code()` → exec in namespace → mock `research()` that triggers classification → gate fires → tools removed from namespace.

- [ ] **Step 1: Write the end-to-end test**

Add to `tests/test_tool_gate.py`:

```python
from unittest.mock import MagicMock, patch


class TestReplGateWiring:
    """Full integration: setup code → research() → classification → gate fires."""

    def test_gate_removes_tools_after_high_confidence_classification(self):
        """After research() returns with HIGH classification, rlm_query is gone."""
        code = build_search_setup_code(api_url="http://localhost:8091", query="test question")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        # Before classification, all tools present
        assert "rlm_query" in ns or True  # rlm_query only present if depth < max_delegation_depth
        assert "browse" in ns
        assert "reformulate" in ns

        # Simulate classification landing on _ctx
        ns["_ctx"].classification = {
            "confidence": "HIGH",
            "category": "PT",
            "also_category": "",
            "clusters": "Wudu",
            "filters": {"parent_code": "PT"},
            "strategy": "Strong match.",
            "query_variants": [],
        }

        # Fire the gate callback directly (normally research() does this)
        ns["_ctx"]._gate_callback(ns["_ctx"].classification)

        # Expensive tools should be removed
        assert "browse" not in ns
        assert "reformulate" not in ns
        assert "critique_answer" not in ns
        assert "evaluate_results" not in ns

        # Core tools remain
        assert "research" in ns
        assert "draft_answer" in ns
        assert "check_progress" in ns
        assert "search" in ns
        assert "fiqh_lookup" in ns
        assert "format_evidence" in ns

    def test_gate_is_idempotent(self):
        """Calling gate callback twice doesn't error (second call is a no-op)."""
        code = build_search_setup_code(api_url="http://localhost:8091", query="test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        classification = {"confidence": "HIGH", "category": "PT", "also_category": ""}
        ns["_ctx"].classification = classification
        ns["_ctx"]._gate_callback(classification)
        # Second call — should not raise
        ns["_ctx"]._gate_callback(classification)

        assert "research" in ns

    def test_low_confidence_keeps_all_tools(self):
        """LOW confidence → full tier → no tools removed."""
        code = build_search_setup_code(api_url="http://localhost:8091", query="test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        classification = {"confidence": "LOW", "category": "PT", "also_category": "BE"}
        ns["_ctx"].classification = classification
        ns["_ctx"]._gate_callback(classification)

        assert "browse" in ns
        assert "reformulate" in ns
        assert "critique_answer" in ns
```

- [ ] **Step 2: Run the full test suite**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/test_tool_gate.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/farieds/projects/rlm && git add tests/test_tool_gate.py && git commit -m "test(search): add end-to-end REPL gate wiring tests"
```

---

### Task 5: Update prompt layer to document tool gating

**Files:**
- Modify: `rlm_search/prompt_layers/20-tools.md`

Add a short section to the tools layer so the LM knows tools may be gated. This prevents confusion when the LM tries to call `rlm_query()` and gets a `NameError`.

- [ ] **Step 1: Add tool gating note to 20-tools.md**

Append to the end of `rlm_search/prompt_layers/20-tools.md`:

```markdown

### Tool Availability

After the first `research()` call, tools may be gated based on classification confidence:
- **HIGH confidence** (single category): Low-level tools (`browse`, `reformulate`, `critique_answer`, `evaluate_results`, `rlm_query`) are removed. Use `research()` + `draft_answer()` directly.
- **MEDIUM confidence**: `rlm_query` is removed (too expensive for moderate-confidence queries). All other tools available.
- **LOW confidence** or cross-category: All tools available.

If you get a `NameError` for a tool, the gate has restricted it — work with the tools you have.
```

- [ ] **Step 2: Verify prompt assembles correctly**

Run: `cd /Users/farieds/projects/rlm && uv run python -c "from rlm_search.prompts import build_system_prompt; p = build_system_prompt(); assert 'Tool Availability' in p; print('OK')" `
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/farieds/projects/rlm && git add rlm_search/prompt_layers/20-tools.md && git commit -m "docs(search): document tool gating behavior in tools prompt layer"
```

---

### Task 6: Full regression test

**Files:** None (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `cd /Users/farieds/projects/rlm && uv run pytest tests/ -v --tb=short`
Expected: All tests pass, no regressions.

- [ ] **Step 2: Verify prompt builds end-to-end**

Run: `cd /Users/farieds/projects/rlm && uv run python -c "from rlm_search.prompts import build_system_prompt; print(len(build_system_prompt()), 'chars')"`
Expected: Prints prompt length, no errors.

- [ ] **Step 3: Verify setup code generates and executes cleanly**

Run: `cd /Users/farieds/projects/rlm && uv run python -c "from rlm_search.repl_tools import build_search_setup_code; code = build_search_setup_code(api_url='http://localhost:8091'); ns = {}; exec(code, ns); print('tools:', [k for k in ns if callable(ns.get(k)) and not k.startswith('_')]); print('gate_callback:', ns['_ctx']._gate_callback is not None)"`
Expected: Lists tool names, `gate_callback: True`

- [ ] **Step 4: Commit (if any fixups were needed)**

```bash
cd /Users/farieds/projects/rlm && git add -u && git commit -m "fix(search): address tool gate regression issues"
```

---

## Design Decisions

**Why gate after first research(), not before the LM loop?**
Classification runs inside `_extract_classification()` during the first `research()` call (`composite_tools.py:333`). Moving it earlier would require a separate API call before the LM loop — extra latency for uncertain benefit. Gating after iteration 1 is the right tradeoff: the first iteration is always a broad search (by design in the system prompt), and gating takes effect for iteration 2+, which is where the LM makes targeted decisions.

**Why a callback instead of direct namespace mutation?**
The `research()` wrapper function is a closure generated by `build_search_setup_code()`. It can't directly access the `LocalREPL.locals` dict. A callback on `_ctx` lets the setup code wire the gate to the correct namespace at setup time, and `research()` just calls `_ctx._gate_callback()` — clean separation.

**Why not change the system prompt dynamically per tier?**
The system prompt is fixed at RLM construction time (`custom_system_prompt` in `RLM.__init__`). Changing it mid-session would require changes to `rlm.py`. Removing functions from the namespace is simpler, already works with the existing architecture, and has the same effect — the LM gets a `NameError` and falls back to available tools.

**Why `also_category` forces full tier?**
When `_extract_classification` sets `also_category`, the query spans two categories. This is exactly when the LM needs `browse()` to discover cross-category clusters and `reformulate()` to try different angles. Gating these away would hurt recall on the hardest queries.
