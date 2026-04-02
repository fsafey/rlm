## Pre-Classification

`classification` starts as `None`. Your first `research()` should be broad (no filters).
After it returns, classification is populated from the search results. Use it for subsequent searches.

- `classification["category"]` — category code (e.g. "FN")
- `classification["confidence"]` — HIGH | MEDIUM | LOW
- `classification["clusters"]` — relevant cluster labels. **Read `strategy` first** — when strategy says "skip cluster filter", this field contains doc-count fallback labels, not semantic matches; ignore it.
- `classification["filters"]` — suggested filters for research()
- `classification["strategy"]` — concrete recommended approach — **read this first**

**Classification is a hypothesis.** Let confidence guide your subsequent searches:
- **HIGH**: Use `classification["filters"]` and clusters. Drop filters if results are poor (<2 relevant).
- **MEDIUM**: Use category filter only (skip cluster filter). Broaden if results are poor.
- **LOW**: Start broad — no filters. Add category filter only if initial results confirm the category.

## Query Variants

`query_variants` is `[]` — L0 Query Intelligence handles query expansion automatically.
Do NOT generate or pass query variants manually.
