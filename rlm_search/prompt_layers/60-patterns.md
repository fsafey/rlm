## Iteration Patterns

### Pattern A: Straightforward question (1 iteration)
The I.M.A.M. corpus has a direct match. Most questions follow this pattern.
Multiple ```repl``` blocks in one response execute in the same iteration.

```repl
# Broad first search — progress auto-checked, classification computed
results = research(question)
```

```repl
# Draft and finalize (same iteration — no extra cost)
result = draft_answer(question, results["results"])
answer = result["answer"]
```

FINAL_VAR(answer)

### Pattern B: Complex question (2-3 iterations)
Question spans conditions, exceptions, or practical applications — or first search yields low relevance.

```repl
# Iteration 1: Broad search — progress auto-checked
results = research(question)
```

```repl
# Iteration 2: Branch on results["progress"] from research()
progress = results["progress"]
if progress["phase"] == "continue" and '"' in progress.get("guidance", ""):
    suggested = progress["guidance"].split('"')[1]
    results2 = research(question, filters={"parent_code": classification["category"], "cluster_label": suggested})
elif progress["phase"] in ("stalled", "repeating"):
    try:
        alt_queries = reformulate(question, question, top_score=progress.get("top_score", 0))
        results2 = research(alt_queries[0], extra_queries=[{"query": q} for q in alt_queries[1:]])
    except NameError:
        results2 = research(question, filters={"parent_code": classification["category"]})
else:
    results2 = research(question, filters=classification["filters"])
```

```repl
# Draft in same iteration as final search (no extra cost)
all_results = results["results"] + results2["results"]
result = draft_answer(question, all_results)
answer = result["answer"]
```

FINAL_VAR(answer)

## Efficient Tool Usage

- **Multiple ```repl``` blocks per response** — all blocks in one response execute in the same iteration. Chain search → check → draft to finish in fewer iterations.
- **L0 handles query expansion** — do NOT manually pass extra_queries for variant coverage. L0 generates domain-specific variants automatically.
- **`extra_queries` in one `research()` call** — all results merged, deduped, and evaluated together in one pass. Use for targeted angle expansion, not variant generation.
- **Second `research()` call** — doesn't re-evaluate results from the first call (cross-call rating cache). Add new angles without wasted LLM calls.
- **`rlm_query()`** — spawns a full child agent (~3 iterations). Only use when dimensions are truly independent and need their own search depth.
- **`browse()`** — zero LLM cost. Use to discover clusters before filtering: `browse(filters={"parent_code": "PT"}, group_by="cluster_label")`.
- **`reformulate()`** — generates 3 alternative queries. Use when top_score < 0.3 or when stalled.

> **Note:** Some tools above may be unavailable depending on your gate tier — see **Tool Availability**.

## Anti-Patterns (avoid these)

- **Searching the same query twice** — check `search_log` or the audit trail in `results["progress"]`.
- **Ignoring progress guidance** — `results["progress"]["guidance"]` suggests specific next steps. Follow them.
- **Calling `check_progress()` after `research()`** — redundant. `research()` already auto-checks and includes progress in its return value.
- **Extra blocks to inspect results** — don't write blocks just to print or read data. `research()` already prints summaries.
- **Drafting with low confidence when iterations remain** — if confidence < 40% and you have iterations left, invest in more research.
- **Using rlm_query for single-topic questions** — direct `research()` with `extra_queries` is 3x cheaper.
- **Calling `critique_answer()` after `draft_answer()`** — `draft_answer()` already critiques and revises internally (tier-dependent). Additional standalone critique is redundant and adds 40-70s of wasted LLM time.
- **Calling a gated tool without a try/except** — if a tool gets `NameError`, the gate removed it. Don't retry — use `research()` with different filters or angles instead.
