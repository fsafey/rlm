# Discoverable Prompt Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic `AGENTIC_SEARCH_SYSTEM_PROMPT` string with a layered system that assembles the prompt from discovered markdown files, enabling per-corpus customization without code changes.

**Architecture:** A `PromptLayer` loader reads markdown files from `rlm_search/prompt_layers/`, ordered by numeric filename prefix (e.g. `00-core.md`, `10-domain.md`). `build_system_prompt()` discovers, orders, and concatenates these layers — plus an optional override directory path for corpus-specific layers. `DOMAIN_PREAMBLE` is read from `10-domain.md` at module load time so tools that import it stay in sync with the layer file.

**Tech Stack:** Python, pathlib, existing pytest suite. No YAML parsing needed — filename prefixes handle ordering.

---

## File Structure

```
rlm_search/
  prompts.py                    # MODIFY — replace monolith with layer assembly
  prompt_layers/                # CREATE — default layer files
    00-core.md                  # REPL contract, FINAL_VAR, critical rules
    10-domain.md                # DOMAIN_PREAMBLE content, role, grounding rules
    20-tools.md                 # Tool signatures and docs
    30-taxonomy.md              # Category codes, filter keys
    40-classification.md        # Pre-classification section
    50-quality.md               # check_progress phases, signals
    60-patterns.md              # Iteration patterns A/B, efficient usage, anti-patterns
    70-evidence.md              # Grounding rules, insufficient evidence
    80-final.md                 # Final answer format (FINAL_VAR/FINAL)
  prompt_loader.py              # CREATE — layer discovery, frontmatter parsing, assembly
tests/
  test_prompt_loader.py         # CREATE — layer loading, ordering, override tests
  test_api.py                   # MODIFY — update existing prompt builder tests
```

### Design Decisions

1. **Numbered filename prefixes for ordering** — not YAML `order` field. Simpler, visible in `ls`, no parsing needed for ordering. The prefix IS the order. Files without numeric prefix sort last.
2. **`DOMAIN_PREAMBLE` sourced from `10-domain.md`** — `composite_tools.py` and `subagent_tools.py` import it as a Python constant, but its content is read from the layer file at module load time. Single source of truth, no drift.
3. **Override directory** — `build_system_prompt(layers_dir=...)` accepts an optional path. If provided, files there replace same-named defaults (matched by filename stem, not prefix number). This is the claw-code pattern: project-level files shadow defaults.
4. **No YAML frontmatter** — the filename prefix handles ordering, and sections don't need metadata beyond their content. Keep it simple: each file is pure markdown, concatenated in order.

---

### Task 1: Create the prompt layer loader

**Files:**
- Create: `rlm_search/prompt_loader.py`
- Test: `tests/test_prompt_loader.py`

- [ ] **Step 1: Write the failing test — discover layers from a directory**

```python
# tests/test_prompt_loader.py
"""Tests for prompt layer discovery and assembly."""

from __future__ import annotations

import textwrap
from pathlib import Path

from rlm_search.prompt_loader import discover_layers, assemble_prompt


class TestDiscoverLayers:
    """Layer discovery from a directory of numbered markdown files."""

    def test_discovers_and_orders_by_prefix(self, tmp_path: Path):
        (tmp_path / "20-tools.md").write_text("## Tools\nresearch() docs")
        (tmp_path / "00-core.md").write_text("## Core\nREPL rules")
        (tmp_path / "10-domain.md").write_text("## Domain\nI.M.A.M. preamble")

        layers = discover_layers(tmp_path)

        assert [l.name for l in layers] == ["00-core.md", "10-domain.md", "20-tools.md"]
        assert "REPL rules" in layers[0].content
        assert "I.M.A.M. preamble" in layers[1].content

    def test_skips_non_markdown(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("core")
        (tmp_path / "README.txt").write_text("ignore me")
        (tmp_path / "notes.py").write_text("# not a layer")

        layers = discover_layers(tmp_path)
        assert len(layers) == 1
        assert layers[0].name == "00-core.md"

    def test_skips_empty_files(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("real content")
        (tmp_path / "10-empty.md").write_text("   \n  ")

        layers = discover_layers(tmp_path)
        assert len(layers) == 1

    def test_empty_directory(self, tmp_path: Path):
        layers = discover_layers(tmp_path)
        assert layers == []

    def test_missing_directory_returns_empty(self, tmp_path: Path):
        layers = discover_layers(tmp_path / "nonexistent")
        assert layers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestDiscoverLayers -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rlm_search.prompt_loader'`

- [ ] **Step 3: Implement discover_layers**

```python
# rlm_search/prompt_loader.py
"""Prompt layer discovery and assembly — claw-code-inspired layered prompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_DEFAULT_LAYERS_DIR = Path(__file__).resolve().parent / "prompt_layers"


@dataclass(frozen=True)
class PromptLayer:
    """A single prompt layer file."""
    name: str
    content: str
    path: Path


def discover_layers(layers_dir: Path | None = None) -> list[PromptLayer]:
    """Discover and return prompt layers sorted by filename prefix.

    Files must be .md and non-empty. Sorted lexicographically by name
    (numeric prefixes like 00-, 10-, 20- control order).
    """
    directory = layers_dir or _DEFAULT_LAYERS_DIR
    if not directory.is_dir():
        return []

    layers = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text().strip()
        if not content:
            continue
        layers.append(PromptLayer(name=path.name, content=content, path=path))

    return layers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestDiscoverLayers -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Write the failing test — assemble prompt from layers**

```python
# Append to tests/test_prompt_loader.py

class TestAssemblePrompt:
    """Assemble a system prompt from discovered layers."""

    def test_concatenates_in_order(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("CORE RULES")
        (tmp_path / "10-domain.md").write_text("DOMAIN RULES")
        (tmp_path / "20-tools.md").write_text("TOOL DOCS")

        result = assemble_prompt(layers_dir=tmp_path)

        assert result.index("CORE RULES") < result.index("DOMAIN RULES")
        assert result.index("DOMAIN RULES") < result.index("TOOL DOCS")

    def test_double_newline_separator(self, tmp_path: Path):
        (tmp_path / "00-a.md").write_text("section a")
        (tmp_path / "10-b.md").write_text("section b")

        result = assemble_prompt(layers_dir=tmp_path)
        assert "section a\n\n\nsection b" not in result  # no triple newlines
        assert "section a\n\nsection b" in result

    def test_empty_dir_returns_empty_string(self, tmp_path: Path):
        result = assemble_prompt(layers_dir=tmp_path)
        assert result == ""
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestAssemblePrompt -v`
Expected: FAIL — `assemble_prompt` not defined or wrong signature

- [ ] **Step 7: Implement assemble_prompt**

```python
# Append to rlm_search/prompt_loader.py

def assemble_prompt(
    layers_dir: Path | None = None,
    overrides_dir: Path | None = None,
) -> str:
    """Assemble system prompt from discovered layers.

    Args:
        layers_dir: Directory of default layer files. Uses built-in default if None.
        overrides_dir: Optional override directory. Files here replace default layers
            with the same filename stem (e.g., ``10-domain.md`` overrides the default
            ``10-domain.md``).

    Returns:
        Concatenated prompt string with double-newline separators.
    """
    layers = discover_layers(layers_dir)

    if overrides_dir is not None:
        overrides = {l.name: l for l in discover_layers(overrides_dir)}
        layers = [overrides.get(l.name, l) for l in layers]
        # Also add any override-only layers (new files not in defaults)
        default_names = {l.name for l in layers}
        for override in discover_layers(overrides_dir):
            if override.name not in default_names:
                layers.append(override)
        layers.sort(key=lambda l: l.name)

    if not layers:
        return ""

    return "\n\n".join(l.content for l in layers)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestAssemblePrompt -v`
Expected: PASS (all 3 tests)

- [ ] **Step 9: Write the failing test — override layers**

```python
# Append to tests/test_prompt_loader.py

class TestOverrideLayers:
    """Override directory replaces matching default layers."""

    def test_override_replaces_matching_file(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "00-core.md").write_text("default core")
        (defaults / "10-domain.md").write_text("default domain")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "10-domain.md").write_text("custom domain for medical corpus")

        result = assemble_prompt(layers_dir=defaults, overrides_dir=overrides)

        assert "default core" in result
        assert "custom domain for medical corpus" in result
        assert "default domain" not in result

    def test_override_adds_new_layer(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "00-core.md").write_text("core")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "90-custom.md").write_text("corpus-specific rules")

        result = assemble_prompt(layers_dir=defaults, overrides_dir=overrides)

        assert "core" in result
        assert "corpus-specific rules" in result
        # Custom layer sorts after core by prefix
        assert result.index("core") < result.index("corpus-specific rules")
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestOverrideLayers -v`
Expected: PASS (both tests — override logic already implemented in step 7)

- [ ] **Step 11: Commit**

```bash
cd ~/projects/rlm
git add rlm_search/prompt_loader.py tests/test_prompt_loader.py
git commit -m "feat(prompts): add prompt layer loader with discovery and override support"
```

---

### Task 2: Extract the monolithic prompt into layer files

**Files:**
- Create: `rlm_search/prompt_layers/00-core.md` through `80-final.md`
- Test: `tests/test_prompt_loader.py` (add round-trip test)

The split follows the existing `##` heading boundaries in `AGENTIC_SEARCH_SYSTEM_PROMPT`. Each file maps to one or more sections that form a logical unit.

- [ ] **Step 1: Write the failing round-trip test**

This test verifies the extracted layers produce the exact same prompt as the current monolith.

```python
# Append to tests/test_prompt_loader.py

class TestRoundTrip:
    """Extracted layers must reproduce the original monolithic prompt."""

    def test_assembled_matches_monolith(self):
        """The assembled default layers must match AGENTIC_SEARCH_SYSTEM_PROMPT exactly."""
        from rlm_search.prompt_loader import assemble_prompt
        from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT

        assembled = assemble_prompt()  # uses default layers_dir

        assert assembled == AGENTIC_SEARCH_SYSTEM_PROMPT, (
            "Assembled layers diverged from AGENTIC_SEARCH_SYSTEM_PROMPT. "
            "Diff the two strings to find the discrepancy."
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestRoundTrip -v`
Expected: FAIL — `prompt_layers/` directory doesn't exist yet, so `assemble_prompt()` returns `""`

- [ ] **Step 3: Create the layer files**

Split `AGENTIC_SEARCH_SYSTEM_PROMPT` along its existing `##` boundaries. Each file below is the **exact text** from the monolith for that section, with no modifications.

Create `rlm_search/prompt_layers/00-core.md`:
```
The content from the CRITICAL opening through the end of "## REPL Environment" section (lines 11-24 of prompts.py, the text inside the triple-quoted string).
```

Create `rlm_search/prompt_layers/10-domain.md`:
```
The DOMAIN_PREAMBLE-equivalent content that's embedded in the system prompt — the "You are the search concierge for I.M.A.M." paragraph and role description.
```

Create `rlm_search/prompt_layers/20-tools.md`:
```
The "## Tools" section through "## Low-Level Tools" (lines 27-63).
```

Create `rlm_search/prompt_layers/30-taxonomy.md`:
```
The "## Taxonomy" section (lines 65-76).
```

Create `rlm_search/prompt_layers/40-classification.md`:
```
"## Pre-Classification" + "## Query Variants" sections (lines 78-97).
```

Create `rlm_search/prompt_layers/50-quality.md`:
```
"## Reading check_progress()" section (lines 99-118).
```

Create `rlm_search/prompt_layers/60-patterns.md`:
```
"## Iteration Patterns" + "## Efficient Tool Usage" + "## Anti-Patterns" sections (lines 120-189).
```

Create `rlm_search/prompt_layers/70-evidence.md`:
```
"## Grounding Rules" + "## When Evidence is Insufficient" sections (lines 191-204).
```

Create `rlm_search/prompt_layers/80-final.md`:
```
"## Final Answer" section (lines 206-215).
```

**Important:** The concatenation of all files with `\n\n` separators must exactly reproduce the original `AGENTIC_SEARCH_SYSTEM_PROMPT` string. Use the round-trip test to verify. You will need to be precise about leading/trailing newlines in each file.

- [ ] **Step 4: Run the round-trip test iteratively until it passes**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestRoundTrip -v`

If it fails, diff the assembled output against the original:

```python
# Quick debug script — run in Python REPL
from rlm_search.prompt_loader import assemble_prompt
from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT
a, b = assemble_prompt(), AGENTIC_SEARCH_SYSTEM_PROMPT
for i, (ca, cb) in enumerate(zip(a, b)):
    if ca != cb:
        print(f"First diff at char {i}: assembled={repr(ca)} original={repr(cb)}")
        print(f"Context: ...{repr(a[max(0,i-20):i+20])}...")
        break
if len(a) != len(b):
    print(f"Length diff: assembled={len(a)} original={len(b)}")
```

Adjust whitespace in layer files until the test passes. The most common issues will be:
- Missing/extra blank lines between sections
- Trailing whitespace in files
- The `\n\n` join adding one too many or too few newlines at section boundaries

Expected: PASS after adjustments

- [ ] **Step 5: Commit**

```bash
cd ~/projects/rlm
git add rlm_search/prompt_layers/
git commit -m "refactor(prompts): extract system prompt into discoverable layer files"
```

---

### Task 3: Wire build_system_prompt to use the layer assembler

**Files:**
- Modify: `rlm_search/prompts.py`
- Modify: `tests/test_api.py:106-121`
- Test: existing tests must still pass

- [ ] **Step 1: Write the failing test — build_system_prompt uses layers**

```python
# Append to tests/test_prompt_loader.py

class TestBuildSystemPromptLayers:
    """build_system_prompt() uses layer assembly internally."""

    def test_build_with_override_dir(self, tmp_path: Path):
        from rlm_search.prompts import build_system_prompt

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "10-domain.md").write_text("You are a medical search concierge.")

        prompt = build_system_prompt(max_iterations=10, layers_override_dir=overrides)

        assert "medical search concierge" in prompt
        assert "10 iterations" in prompt  # budget section still appended
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py::TestBuildSystemPromptLayers -v`
Expected: FAIL — `build_system_prompt` doesn't accept `layers_override_dir`

- [ ] **Step 3: Update prompts.py to use the layer assembler**

```python
# rlm_search/prompts.py
"""Custom system prompt for RLM agentic search."""

from __future__ import annotations

from rlm_search.prompt_loader import assemble_prompt, _DEFAULT_LAYERS_DIR

# DOMAIN_PREAMBLE: read from the layer file so tools that import it
# stay in sync with the assembled prompt. Single source of truth.
_domain_path = _DEFAULT_LAYERS_DIR / "10-domain.md"
DOMAIN_PREAMBLE = _domain_path.read_text().strip() + "\n\n" if _domain_path.exists() else ""

# Assembled from layer files — replaces the former monolithic string.
# Kept as a module-level constant for backward compat (tests import it).
AGENTIC_SEARCH_SYSTEM_PROMPT = assemble_prompt()


def build_system_prompt(
    max_iterations: int = 15,
    layers_override_dir: Path | None = None,
) -> str:
    """Build the full system prompt with iteration budget.

    Args:
        max_iterations: Iteration budget to inject.
        layers_override_dir: Optional directory of layer files that shadow
            the defaults. Files with matching names replace the default;
            new files are appended in sort order.
    """
    if layers_override_dir is not None:
        base = assemble_prompt(overrides_dir=layers_override_dir)
    else:
        base = AGENTIC_SEARCH_SYSTEM_PROMPT

    budget_section = f"""

## Iteration Budget

You have **{max_iterations} iterations** total. Each response you send costs one iteration — but you can include **multiple ```repl``` blocks in a single response** and they execute sequentially within the same iteration. Use this to chain dependent steps (search → check → draft) in one turn.

**Read check_progress() after every research() call.** It tells you whether to draft or keep searching.

- **check_progress() returns phase 'explore'** → search broadly with diverse angles, do NOT draft yet
- **check_progress() returns phase 'ready'** → draft immediately (don't waste iterations)
- **check_progress() returns phase 'continue'** → follow the guidance suggestion (1-2 more research calls)
- **phase is still 'continue' after 3+ searches** → reformulate or try different category
- **After iteration {max_iterations - 3}** → draft and finalize regardless of evidence quality

Most questions resolve in 1-2 iterations. Use more only when check_progress says to."""

    return base + budget_section
```

- [ ] **Step 4: Run all prompt-related tests**

Run: `cd ~/projects/rlm && uv run pytest tests/test_prompt_loader.py tests/test_api.py::TestBuildSystemPrompt -v`
Expected: ALL PASS — round-trip test confirms assembled == original, existing tests confirm budget section

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd ~/projects/rlm && uv run pytest tests/ -v --timeout=30`
Expected: No regressions. The `AGENTIC_SEARCH_SYSTEM_PROMPT` constant still exists with the same value. `DOMAIN_PREAMBLE` still importable. `build_system_prompt()` still returns the same output when called without overrides.

- [ ] **Step 6: Verify the hardcoded prompt string is fully replaced**

Run: `cd ~/projects/rlm && grep -c '"""' rlm_search/prompts.py`
Expected: Should be 2 or fewer (the module docstring). The 200-line triple-quoted string should be gone.

Also verify the prefill compliance script still works:
Run: `cd ~/projects/rlm && uv run python scripts/test_prefill_compliance.py`
Expected: PASS — it imports `build_system_prompt` which still works identically.

- [ ] **Step 7: Commit**

```bash
cd ~/projects/rlm
git add rlm_search/prompts.py tests/test_prompt_loader.py tests/test_api.py
git commit -m "refactor(prompts): wire build_system_prompt to layer assembler, remove hardcoded prompt"
```

---

### Task 4: Wire override directory through the API

**Files:**
- Modify: `rlm_search/config.py`
- Modify: `rlm_search/api.py:303`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_api.py

class TestLayerOverrideConfig:
    """PROMPT_LAYERS_DIR config flows through to build_system_prompt."""

    def test_override_dir_env_var(self, tmp_path, monkeypatch):
        overrides = tmp_path / "layers"
        overrides.mkdir()
        (overrides / "10-domain.md").write_text("Custom domain layer.")

        monkeypatch.setenv("PROMPT_LAYERS_DIR", str(overrides))

        # Re-import to pick up env var
        import importlib
        import rlm_search.config as cfg
        importlib.reload(cfg)

        assert cfg.PROMPT_LAYERS_DIR == overrides
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_api.py::TestLayerOverrideConfig -v`
Expected: FAIL — `PROMPT_LAYERS_DIR` not defined in config

- [ ] **Step 3: Add config variable**

Add to `rlm_search/config.py`, after the existing config variables:

```python
# Optional: override directory for prompt layer files.
# Files here shadow defaults in rlm_search/prompt_layers/.
_prompt_layers_env = os.getenv("PROMPT_LAYERS_DIR", "")
PROMPT_LAYERS_DIR: Path | None = Path(_prompt_layers_env) if _prompt_layers_env else None
```

- [ ] **Step 4: Thread it through api.py**

In `rlm_search/api.py`, update the import:

```python
from rlm_search.config import (
    # ... existing imports ...
    PROMPT_LAYERS_DIR,
)
```

Update line 303 in `_run_search_v2` (inside the new-session branch):

```python
custom_system_prompt=build_system_prompt(
    kw["max_iterations"],
    layers_override_dir=PROMPT_LAYERS_DIR,
),
```

- [ ] **Step 5: Run tests**

Run: `cd ~/projects/rlm && uv run pytest tests/test_api.py -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd ~/projects/rlm
git add rlm_search/config.py rlm_search/api.py tests/test_api.py
git commit -m "feat(prompts): wire PROMPT_LAYERS_DIR config for per-deployment overrides"
```

---

---

## Verification Checklist

After all tasks are complete:

- [ ] `uv run pytest tests/ -v --timeout=30` — all pass
- [ ] `uv run python scripts/test_prefill_compliance.py` — pass
- [ ] `from rlm_search.prompts import DOMAIN_PREAMBLE` — still works (tools depend on it)
- [ ] `from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT` — still works (computed from layers)
- [ ] `from rlm_search.prompts import build_system_prompt` — accepts `layers_override_dir` param
- [ ] `PROMPT_LAYERS_DIR=/path/to/custom/layers` env var overrides default layers
- [ ] Editing `rlm_search/prompt_layers/30-taxonomy.md` changes the assembled prompt without touching Python
