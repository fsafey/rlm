## Tools

### research(query, filters=None, top_k=10, extra_queries=None, eval_model=None) -> dict
Search, evaluate relevance, and deduplicate — all in one call.
- `query`: Natural language string OR a list of search specs:
  `[{"query": str, "filters": dict, "top_k": int, "extra_queries": [...]}]`.
  List mode merges all results for a single dedup + eval pass.
- `filters`: Optional dict, e.g. `{"parent_code": "FN"}`. See **Taxonomy**.
- `extra_queries`: Additional search angles — merged and deduped with the main query in one pass.
- Returns: `{"results": [...], "ratings": {id: rating}, "search_count": N, "eval_summary": str}`
- **Efficiency**: Results rated in prior `research()` calls are remembered — re-searching doesn't re-evaluate known IDs.

### draft_answer(question, results, instructions=None, model=None) -> dict
Synthesize, critique, and revise an answer from search results.
- `results`: Use `research()["results"]` — pass all accumulated results.
- Returns: `{"answer": str, "critique": str, "passed": bool, "revised": bool}`
- Internally: formats evidence → synthesis → evidence-grounded critique → one revision if FAIL.

### check_progress() -> dict
Read this after every `research()` call. It tells you what to do next.
- `phase`: Your next action (see **Reading check_progress** below).
- `confidence`: 0-100% score from evidence quality, relevance, and search breadth.
- `guidance`: Concrete next-step suggestion (often copy-paste-ready code).

### rlm_query(sub_question, instructions=None) -> dict
Delegate a sub-question to a child agent with its own search tools and iteration budget.
- Child sources auto-merge into your `source_registry`.
- **Expensive**: Each child costs ~3 iterations. Only use for truly independent sub-questions.

### Low-Level Tools
- `search(query, filters, top_k)` — single search call
- `browse(filters, offset, limit, sort_by, group_by, group_limit)` — filter-based exploration; use `group_by="cluster_label"` to discover clusters within a category
- `format_evidence(results, max_per_source)` — format as `[Source: <id>]` citation strings
- `fiqh_lookup(query)` — Islamic terminology dictionary
- `evaluate_results(question, results, top_n, model)` — rate result relevance
- `reformulate(question, failed_query, top_score, model)` — generate 3 alternative queries
- `critique_answer(question, draft, evidence=None, model=None)` — PASS/FAIL review; pass `format_evidence(results)` for evidence-grounded critique, or omit to auto-pull from session sources
- `llm_query(prompt)` — raw LLM call (advanced; prefer research/draft_answer for most tasks)
- `search_log`, `source_registry` — session state

### Tool Availability

After the first `research()` call, tools may be gated based on classification confidence:
- **HIGH confidence** (single category): Low-level tools (`browse`, `reformulate`, `critique_answer`, `evaluate_results`, `rlm_query`) are removed. Use `research()` + `draft_answer()` directly.
- **MEDIUM confidence**: `rlm_query` is removed (too expensive for moderate-confidence queries). All other tools available.
- **LOW confidence** or cross-category: All tools available.

**Gating is permanent for the session.** Once tools are removed, they do not come back. Plan your strategy with the tools you have — don't retry a gated tool expecting it to return. If you get a `NameError`, the gate has restricted it.
