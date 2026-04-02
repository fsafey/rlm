## Pre-Classification

`classification` starts as `None`. Your first `research()` should be broad (no filters).
After it returns, classification is populated from the search results. Use it for subsequent searches.

- `classification["category"]` — category code (e.g. "FN")
- `classification["confidence"]` — HIGH | MEDIUM | LOW
- `classification["clusters"]` — relevant cluster labels. **Read `strategy` first** — when strategy says "skip cluster filter", this field contains doc-count fallback labels, not semantic matches; ignore it.
- `classification["filters"]` — suggested filters for research()
- `classification["strategy"]` — concrete recommended approach — **read this first**

**Classification is a hypothesis.** Confidence determines both search strategy AND tool availability (see **Tool Availability** in Tools):
- **HIGH**: Use `classification["filters"]` and clusters. Drop filters if results are poor (<2 relevant). **Tool gate: focused** — only `research()`, `draft_answer()`, `search()`, `fiqh_lookup()`, `format_evidence()`, `check_progress()` available.
- **MEDIUM**: Use category filter only (skip cluster filter). Broaden if results are poor. **Tool gate: standard** — all tools except `rlm_query()`.
- **LOW**: Start broad — no filters. Add category filter only if initial results confirm the category. **Tool gate: full** — all tools available.

## Query Variants

`query_variants` is `[]` — L0 Query Intelligence handles query expansion automatically.
Do NOT generate or pass query variants manually.
