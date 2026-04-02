---

## Reading Progress

`research()` auto-checks progress and includes it in `results["progress"]`. These are the phases:

| Phase | Meaning | Action |
|-------|---------|--------|
| `explore` | Mapping corpus territory (saturation < 65%) | **Search broadly.** Run research() with diverse query angles and varied filters. Do NOT draft — map the territory first. |
| `ready` | Sufficient evidence gathered | **Draft now.** Call `draft_answer()`. |
| `continue` | Room to improve evidence | **Follow the `guidance` string.** It suggests specific queries, filters, or clusters to try next. |
| `stalled` | Many searches, few relevant results | **Change strategy.** Try a different category, drop filters, or rephrase your query. Use `reformulate()` if available — if gated, try synonyms or related terms directly with `research()`. |
| `repeating` | Low query diversity (same searches) | **New angles needed.** Use `reformulate()` if available — if gated, rephrase manually and vary filters with `research()`. |
| `finalize` | Draft passed critique | **Emit answer.** Call `FINAL_VAR(answer)`. |

**Key signals** printed by check_progress:
- `confidence=N%` — composite of evidence relevance, search quality, breadth, draft, and critique outcome
- `relevant=N` — results rated RELEVANT (directly answers the question)
- `partial=N` — results rated PARTIAL (related but indirect)
- `top_score=0.XX` — best semantic match score (>0.5 is strong)
- `Searches tried:` — audit trail of queries + filters used (avoid repeating these)
- `saturation=N%` — corpus territory coverage (explore phase only; higher = more territory mapped)
