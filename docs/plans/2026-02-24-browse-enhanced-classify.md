# Browse-Enhanced init_classify Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace single-shot 120-cluster LLM classification with a two-phase approach: LLM picks parent_code (6 options), then browse() gets live cluster data and deterministic matching selects clusters.

**Architecture:** Phase 1 is a simplified LLM prompt (6-way category classification). Phase 2 calls the existing `browse()` tool with `group_by="cluster_label"` to get the category's live cluster landscape + subtopic facets. Phase 3 does deterministic token matching between query terms and cluster sample questions + labels to rank clusters. Fallback to current single-shot classify if browse fails.

**Tech Stack:** Python (rlm_search tools), Cascade `/browse` API (existing), pytest

---

## Context

**Repo:** `~/projects/rlm/` (the rlm library, NOT standalone-search)
**Run tests:** `cd ~/projects/rlm && uv run pytest tests/ -x -q`
**Primary file:** `rlm_search/tools/subagent_tools.py` — `init_classify()` at line 366
**Browse tool:** `rlm_search/tools/api_tools.py` — `browse()` at line 94 (no changes needed)
**Config:** `rlm_search/config.py` — `RLM_CLASSIFY_MODEL` (no changes needed)
**Injection point:** `rlm_search/repl_tools.py:72-73` calls `init_classify()` (no changes needed)
**7_RLM_ENRICH integration:** `7_RLM_ENRICH/core/repl_tools.py:155-160` calls same function (no changes needed)

**Key data structures:**
- `ctx.kb_overview_data["categories"]` — `{code: {name, document_count, clusters: {label: sample_q}, facets: {clusters: [{value, count}], subtopics: [{value, count}]}}}`
- `browse()` returns — `{results, total, has_more, facets: {clusters: [{value, count}], subtopics: [{value, count}]}, grouped_results: [{label, total_count, hits: [{question, answer, ...}]}]}`
- `ctx.classification` output — `{raw, category, clusters, filters, strategy}`

**CATEGORIES constant** in `rlm_search/kb_overview.py:13`:
```python
CATEGORIES = {
    "PT": "Prayer & Tahara (Purification)",
    "WP": "Worship Practices",
    "MF": "Marriage & Family",
    "FN": "Finance & Transactions",
    "BE": "Beliefs & Ethics",
    "OT": "Other Topics",
}
```

---

### Task 1: Extract `_match_clusters` helper + test

**Files:**
- Create: `tests/test_classify.py`
- Modify: `rlm_search/tools/subagent_tools.py` (add `_match_clusters` function before `init_classify`)

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py -x -v`
Expected: FAIL with `ImportError: cannot import name '_match_clusters'`

**Step 3: Write minimal implementation**

Add to `rlm_search/tools/subagent_tools.py`, BEFORE the `init_classify` function (around line 365):

```python
# Stop words excluded from query token matching
_CLASSIFY_STOP_WORDS = frozenset(
    "is it a the to can i do how what in of for and or but from with this that are was were"
    " be been have has had my your his her its on at by an".split()
)


def _match_clusters(question: str, grouped_results: list) -> list[str]:
    """Rank clusters by token overlap with question against sample hits + labels.

    Returns up to 5 cluster labels, ordered by relevance score.
    Falls back to top 2 by document count when no tokens match.
    """
    if not grouped_results:
        return []

    query_tokens = set(question.lower().split()) - _CLASSIFY_STOP_WORDS

    scores: list[tuple[str, int, int]] = []
    for group in grouped_results:
        label = group.get("label", "")
        label_tokens = set(label.lower().split()) - _CLASSIFY_STOP_WORDS
        # Label matches weighted 3x (cluster name is high-signal)
        score = len(query_tokens & label_tokens) * 3
        # Sample hit question matches weighted 1x each
        for hit in group.get("hits", []):
            q = hit.get("question", "").lower()
            hit_tokens = set(q.split()) - _CLASSIFY_STOP_WORDS
            score += len(query_tokens & hit_tokens)
        scores.append((label, score, group.get("total_count", 0)))

    # Sort by match score desc, break ties by doc count desc
    scores.sort(key=lambda x: (-x[1], -x[2]))

    matched = [s[0] for s in scores if s[1] > 0]
    if matched:
        return matched[:5]
    # Fallback: top 2 by document count
    return [s[0] for s in scores[:2]]
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py -x -v`
Expected: all 7 tests PASS

**Step 5: Commit**

```bash
cd ~/projects/rlm && git add tests/test_classify.py rlm_search/tools/subagent_tools.py
git commit -m "feat(classify): add _match_clusters deterministic cluster ranking"
```

---

### Task 2: Extract `_build_category_prompt` helper + test

Isolate the Phase 1 LLM prompt builder so it can be tested independently and the main `init_classify` stays readable.

**Files:**
- Modify: `tests/test_classify.py` (add tests)
- Modify: `rlm_search/tools/subagent_tools.py` (add `_build_category_prompt`)

**Step 1: Write the failing test**

Append to `tests/test_classify.py`:

```python
from rlm_search.tools.subagent_tools import _build_category_prompt


class TestBuildCategoryPrompt:
    """Phase 1 prompt: simple 6-way category classification."""

    SAMPLE_KB = {
        "categories": {
            "PT": {"name": "Prayer & Tahara", "document_count": 4938},
            "FN": {"name": "Finance & Transactions", "document_count": 1891},
        }
    }

    def test_includes_all_category_codes(self):
        prompt = _build_category_prompt("test question", self.SAMPLE_KB)
        assert "PT" in prompt
        assert "FN" in prompt

    def test_includes_doc_counts(self):
        prompt = _build_category_prompt("test question", self.SAMPLE_KB)
        assert "4938" in prompt
        assert "1891" in prompt

    def test_includes_question(self):
        prompt = _build_category_prompt("is mortgage halal?", self.SAMPLE_KB)
        assert "is mortgage halal?" in prompt

    def test_does_not_include_cluster_labels(self):
        """Phase 1 prompt must NOT include cluster labels — that's Phase 3's job."""
        kb_with_clusters = {
            "categories": {
                "FN": {
                    "name": "Finance",
                    "document_count": 100,
                    "clusters": {"Banking Riba Operations": "sample"},
                    "facets": {"clusters": [{"value": "Banking Riba Operations", "count": 50}]},
                },
            }
        }
        prompt = _build_category_prompt("test", kb_with_clusters)
        assert "Banking Riba Operations" not in prompt

    def test_output_format_instruction(self):
        prompt = _build_category_prompt("test", self.SAMPLE_KB)
        assert "CATEGORY:" in prompt
        # Must NOT ask for CLUSTERS, FILTERS, or STRATEGY
        assert "CLUSTERS:" not in prompt.split("Respond")[1]  # not in the response format section
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py::TestBuildCategoryPrompt -x -v`
Expected: FAIL with `ImportError: cannot import name '_build_category_prompt'`

**Step 3: Write minimal implementation**

Add to `rlm_search/tools/subagent_tools.py`, after `_match_clusters` and before `init_classify`:

```python
def _build_category_prompt(question: str, kb_overview_data: dict) -> str:
    """Build Phase 1 prompt: 6-way category classification (no clusters).

    Returns the user-role content string for the classification LLM call.
    Deliberately excludes cluster labels — Phase 3 handles cluster selection
    via browse() + deterministic matching.
    """
    cat_lines = []
    for code, cat in kb_overview_data.get("categories", {}).items():
        name = cat.get("name", code)
        doc_count = cat.get("document_count", 0)
        cat_lines.append(f"{code} — {name} [{doc_count} docs]")
    cat_info = "\n".join(cat_lines)

    return (
        "Classify this Islamic Q&A question into one category.\n\n"
        f'Question: "{question}"\n\n'
        f"Categories:\n{cat_info}\n\n"
        "Examples:\n"
        '"Is it permissible to take a mortgage?" → FN\n'
        '"How do I perform ghusl?" → PT\n'
        '"Is it permissible for a wife to refuse intimacy?" → MF\n'
        '"What are the types of shirk?" → BE\n'
        '"Can I pray Eid salah at home?" → WP\n'
        '"Is it permissible to cremate the dead?" → OT\n\n'
        "Respond with exactly one line:\n"
        "CATEGORY: <code>"
    )
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py -x -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
cd ~/projects/rlm && git add tests/test_classify.py rlm_search/tools/subagent_tools.py
git commit -m "feat(classify): add _build_category_prompt for Phase 1"
```

---

### Task 3: Rewrite `init_classify` to two-phase flow

Replace the body of `init_classify()` with the two-phase architecture. Browse call is Phase 2. Cluster matching is Phase 3.

**Files:**
- Modify: `rlm_search/tools/subagent_tools.py:366-551` (rewrite `init_classify`)
- Modify: `tests/test_classify.py` (add integration test)

**Step 1: Write the failing test**

Append to `tests/test_classify.py`:

```python
from unittest.mock import MagicMock, patch

from rlm_search.tools.context import ToolContext


class TestInitClassifyTwoPhase:
    """Integration: init_classify uses Phase 1 (LLM) + Phase 2 (browse) + Phase 3 (match)."""

    def _make_ctx(self) -> ToolContext:
        ctx = ToolContext(api_url="http://test:8091")
        ctx.kb_overview_data = {
            "categories": {
                "FN": {"name": "Finance & Transactions", "document_count": 1891},
                "PT": {"name": "Prayer & Tahara", "document_count": 4938},
            }
        }
        ctx.llm_query = None  # not used in two-phase
        ctx.llm_query_batched = None
        ctx._parent_logger = None
        return ctx

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_two_phase_sets_classification(self, mock_post, mock_get_client):
        """Phase 1 LLM → Phase 2 browse → Phase 3 match → ctx.classification set."""
        # Phase 1: LLM returns category
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: FN"
        mock_get_client.return_value = mock_client

        # Phase 2: browse returns grouped results
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": [],
            "total": 1891,
            "has_more": False,
            "facets": {
                "clusters": [
                    {"value": "Banking Riba Operations", "count": 150},
                    {"value": "Shariah Investment Screening", "count": 80},
                ],
                "subtopics": [{"value": "riba", "count": 80}],
            },
            "grouped_results": {
                "clusters": [
                    {
                        "label": "Banking Riba Operations",
                        "total_count": 150,
                        "hits": [{"id": "1", "question": "Is mortgage permissible in Islam?", "answer": "..."}],
                    },
                    {
                        "label": "Shariah Investment Screening",
                        "total_count": 80,
                        "hits": [{"id": "2", "question": "How to screen halal funds?", "answer": "..."}],
                    },
                ]
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        ctx = self._make_ctx()
        init_classify(ctx, "can I take a mortgage?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "FN"
        assert "Banking Riba Operations" in ctx.classification["clusters"]
        assert ctx.classification["filters"] == {"parent_code": "FN"}

    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.tools.api_tools.requests.post")
    def test_browse_failure_falls_back_to_category_only(self, mock_post, mock_get_client):
        """When browse() fails, classification still has category but empty clusters."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT"
        mock_get_client.return_value = mock_client

        # Browse fails
        mock_post.side_effect = Exception("connection refused")

        ctx = self._make_ctx()
        init_classify(ctx, "how to perform ghusl?", model="test-model")

        assert ctx.classification is not None
        assert ctx.classification["category"] == "PT"
        assert ctx.classification["filters"] == {"parent_code": "PT"}
        # Clusters empty because browse failed, but classification still valid
        assert ctx.classification["clusters"] == ""

    @patch("rlm_search.tools.subagent_tools.get_client")
    def test_llm_failure_sets_none(self, mock_get_client):
        """When Phase 1 LLM fails entirely, ctx.classification is None."""
        mock_get_client.side_effect = Exception("API key invalid")

        ctx = self._make_ctx()
        init_classify(ctx, "test question", model="test-model")

        assert ctx.classification is None
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py::TestInitClassifyTwoPhase -x -v`
Expected: FAIL (current init_classify doesn't call browse, expects different LLM output format)

**Step 3: Rewrite init_classify**

Replace the entire `init_classify` function body (lines 366-551 of `subagent_tools.py`) with:

```python
def init_classify(
    ctx: ToolContext,
    question: str,
    model: str = "",
) -> None:
    """Pre-classify query via two-phase approach (zero iteration cost).

    Phase 1: LLM picks parent_code from 6 categories (simple, reliable).
    Phase 2: browse() gets live cluster landscape for that category.
    Phase 3: Deterministic token matching ranks clusters by relevance.

    On any failure, sets ``ctx.classification = None`` and logs a warning.
    """
    import logging
    import time

    _log = logging.getLogger("rlm_search")

    if not ctx.kb_overview_data:
        ctx.classification = None
        return

    # Resolve model
    if not model:
        from rlm_search.config import RLM_CLASSIFY_MODEL

        model = RLM_CLASSIFY_MODEL

    # Emit progress: classifying
    if ctx._parent_logger is not None:
        ctx._parent_logger.emit_progress("classifying", f"Pre-classifying with {model}")

    t0 = time.monotonic()

    with tool_call_tracker(
        ctx,
        "init_classify",
        {"question": question[:100], "model": model},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        try:
            # ── Phase 1: Category classification (LLM) ──────────────────
            from rlm.clients import get_client
            from rlm_search.config import ANTHROPIC_API_KEY, RLM_BACKEND

            if RLM_BACKEND == "claude_cli":
                client_kwargs: dict = {"model": model}
            else:
                client_kwargs = {"model_name": model}
                if ANTHROPIC_API_KEY:
                    client_kwargs["api_key"] = ANTHROPIC_API_KEY

            client = get_client(RLM_BACKEND, client_kwargs)
            prompt_text = _build_category_prompt(question, ctx.kb_overview_data)
            raw = client.completion([{"role": "user", "content": prompt_text}])

            # Parse category code from response
            category = ""
            for line in raw.strip().split("\n"):
                line_s = line.strip()
                if line_s.upper().startswith("CATEGORY:"):
                    category = line_s.split(":", 1)[1].strip().upper()
                    break

            if not category:
                _log.warning("Phase 1 returned no category, raw=%r", raw[:200])
                ctx.classification = None
                classify_ms = int((time.monotonic() - t0) * 1000)
                tc.set_summary({"error": "no category parsed", "duration_ms": classify_ms})
                return

            # ── Phase 2: Browse category clusters (API call) ────────────
            clusters_str = ""
            strategy = ""
            try:
                from rlm_search.tools.api_tools import browse as _browse

                browse_result = _browse(
                    ctx,
                    filters={"parent_code": category},
                    group_by="cluster_label",
                    group_limit=3,
                    limit=1,
                )

                # ── Phase 3: Deterministic cluster matching ─────────────
                grouped = browse_result.get("grouped_results", [])
                matched = _match_clusters(question, grouped)
                clusters_str = ", ".join(matched)

                # Build strategy from subtopic facets
                facets = browse_result.get("facets", {})
                subtopic_facets = facets.get("subtopics", [])
                if subtopic_facets:
                    top_subs = [f["value"] for f in subtopic_facets[:5]]
                    strategy = f"Browse-matched clusters. Top subtopics: {', '.join(top_subs)}"
                else:
                    strategy = f"Browse-matched {len(matched)} clusters in {category}"

            except Exception as e:
                _log.warning("Phase 2 browse failed, using category-only: %s", e)
                print(f"[classify] browse failed: {e}")
                strategy = "Browse unavailable — search broadly within category"

            # ── Assemble classification ─────────────────────────────────
            parsed: dict = {
                "raw": raw,
                "category": category,
                "clusters": clusters_str,
                "filters": {"parent_code": category},
                "strategy": strategy,
            }

            ctx.classification = parsed
            classify_ms = int((time.monotonic() - t0) * 1000)
            print(
                f"[classify] category={category} clusters={clusters_str!r} "
                f"time={classify_ms}ms"
            )
            tc.set_summary(
                {
                    "category": category,
                    "clusters": clusters_str,
                    "duration_ms": classify_ms,
                }
            )

            # Emit progress: classified
            if ctx._parent_logger is not None:
                ctx._parent_logger.emit_progress(
                    "classified",
                    f"Pre-classified in {classify_ms}ms",
                    duration_ms=classify_ms,
                    classification=parsed,
                )

        except Exception as e:
            _log.warning("Pre-classification failed, proceeding without: %s", e)
            ctx.classification = None
            classify_ms = int((time.monotonic() - t0) * 1000)
            print(f"[classify] FAILED: {e}")
            tc.set_summary({"error": str(e), "duration_ms": classify_ms})

            # Emit classified with no classification on failure
            if ctx._parent_logger is not None:
                ctx._parent_logger.emit_progress(
                    "classified",
                    f"Classification skipped ({classify_ms}ms)",
                    duration_ms=classify_ms,
                )
```

**Important:** The `get_client` import must be moved inside the function — it's already there in the current code. The new code keeps the same pattern.

**Step 4: Run all tests**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py -x -v`
Expected: all tests PASS

Run: `cd ~/projects/rlm && uv run pytest tests/ -x -q`
Expected: 58+ passed (same as baseline minus the pre-existing mock failure)

**Step 5: Commit**

```bash
cd ~/projects/rlm && git add rlm_search/tools/subagent_tools.py tests/test_classify.py
git commit -m "feat(classify): two-phase init_classify with browse-enhanced cluster matching"
```

---

### Task 4: Manual integration test via RLM search

Verify the two-phase classify works end-to-end with real API calls.

**Files:** None (manual testing)

**Step 1: Start RLM engine**

Run: `cd ~/projects/rlm && uv run python -m rlm_search.api`

Verify: `[CONFIG]` line prints, server starts on port 8092, KB overview built successfully.

**Step 2: Run a test search**

```bash
curl -s -X POST http://localhost:8092/api/search \
  -H "Content-Type: application/json" \
  -d '{"question": "can I take a mortgage from a bank?", "mode": "search", "max_iterations": 1}' | jq .search_id
```

Then stream results:
```bash
curl -s "http://localhost:8092/api/search/<search_id>/stream"
```

**Step 3: Verify classification in logs**

Expected log output:
```
[classify] category=FN clusters='Banking Riba Operations, Riba in Loan Contracts' time=XXXms
```

Verify:
- Category is FN (not wrong)
- Clusters include "Banking Riba Operations" or "Riba in Loan Contracts" (not "Shariah Investment Screening")
- Time is ~500ms or less (was ~800ms)

**Step 4: Test edge case — ambiguous query**

```bash
curl -s -X POST http://localhost:8092/api/search \
  -H "Content-Type: application/json" \
  -d '{"question": "what is the ruling?", "mode": "search", "max_iterations": 1}' | jq .search_id
```

Verify: Classification still works (may fall back to top clusters by count). No errors.

**Step 5: Commit if any fixes needed**

If manual testing reveals issues, fix and commit with descriptive message.

---

### Task 5: Update _suggest_strategy to handle browse-enhanced clusters

The `_suggest_strategy` function in `progress_tools.py` (already modified in Approach A) splits `ctx.classification["clusters"]` by comma. Verify it works with the new browse-matched cluster format (which is already comma-separated). This is a verification task.

**Files:**
- Modify: `tests/test_classify.py` (add test)

**Step 1: Write the test**

```python
from rlm_search.tools.progress_tools import _suggest_strategy


class TestSuggestStrategyWithBrowseClusters:
    """Verify _suggest_strategy works with browse-enhanced classification."""

    def _make_ctx_with_classification(self, category, clusters_str, kb_data):
        ctx = ToolContext(api_url="http://test:8091")
        ctx.kb_overview_data = kb_data
        ctx.classification = {
            "category": category,
            "clusters": clusters_str,
            "filters": {"parent_code": category},
            "strategy": "Browse-matched clusters",
        }
        ctx.search_log = []
        return ctx

    def test_suggests_first_unsearched_classified_cluster(self):
        kb = {
            "categories": {
                "FN": {
                    "name": "Finance & Transactions",
                    "document_count": 1891,
                    "facets": {"clusters": [{"value": "Banking Riba Operations", "count": 150}]},
                },
            }
        }
        ctx = self._make_ctx_with_classification("FN", "Banking Riba Operations, Riba in Loan Contracts", kb)
        result = _suggest_strategy(ctx, set())
        assert "Banking Riba Operations" in result
        assert "research(query" in result

    def test_returns_strategy_when_all_clusters_explored(self):
        kb = {
            "categories": {
                "FN": {
                    "name": "Finance & Transactions",
                    "document_count": 1891,
                    "facets": {"clusters": []},
                },
            }
        }
        ctx = self._make_ctx_with_classification("FN", "Banking Riba Operations", kb)
        # Mark the cluster as already searched
        ctx.search_log = [{"type": "search_multi", "query": "test", "filters": {"cluster_label": "Banking Riba Operations"}}]
        result = _suggest_strategy(ctx, set())
        assert "Browse-matched clusters" in result
```

**Step 2: Run test**

Run: `cd ~/projects/rlm && uv run pytest tests/test_classify.py::TestSuggestStrategyWithBrowseClusters -x -v`
Expected: PASS (existing code handles this format)

**Step 3: Commit**

```bash
cd ~/projects/rlm && git add tests/test_classify.py
git commit -m "test(classify): verify _suggest_strategy with browse-enhanced clusters"
```
