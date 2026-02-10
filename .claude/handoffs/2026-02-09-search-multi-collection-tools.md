# Session Handoff — 2026-02-09 — Search: fiqh_lookup, health rework, backend trap

## Active Tasks

- [ ] Commit 7 uncommitted files: fiqh_lookup tool + health endpoint rework + Makefile trap + test updates -> all in `rlm_search/` + `tests/` + `Makefile` | Next: `make check`, then commit
- [ ] Source extraction TODO: REPL namespace cleaned up before `search_log`/`sources_cited` can be read -> `rlm_search/api.py:~103` | Next: parse `[REPL:search]` lines from iteration SSE events

## Key Decisions

- **fiqh_lookup() REPL tool**: New `fiqh_lookup(query)` calls Cascade `/bridge` endpoint for 453-term Arabic/English dictionary -> `rlm_search/repl_tools.py`
- **Prompt: glossary replaced by fiqh_lookup**: Static 22-row terminology table removed from system prompt; replaced with `fiqh_lookup()` tool doc + updated search strategy steps -> `rlm_search/prompts.py`
- **Health endpoint rework**: Lifespan does full Cascade discovery + async ping, caches URL in `app.state.cascade_url`; `/api/health` does lightweight re-ping only, returns `cascade_api: connected|unreachable` + `status: ok|degraded` -> `rlm_search/api.py`
- **HealthResponse model**: Added `cascade_api` field -> `rlm_search/models.py`
- **Makefile backend trap**: `make backend` now traps INT/TERM to kill orphan uvicorn on the port -> `Makefile`
- **Test fixture rework**: `client()` fixture patches `discover_cascade_url` to avoid network in tests; health tests now cover connected/unreachable/discovered-but-unhealthy scenarios -> `tests/test_search_api.py`

## Blockers

- **Source extraction from REPL**: `search_log` and `sources_cited` in REPL namespace but env cleaned up before `_run_search()` can read them -> Needs: parse `[REPL:search]` lines from iteration events or serialize to temp file

## Essential Files

```
rlm_search/repl_tools.py       # New fiqh_lookup() function + existing multi-collection tools
rlm_search/prompts.py          # Glossary table removed, fiqh_lookup doc + search strategy steps renumbered
rlm_search/api.py              # _check_cascade_health(), lifespan caching, health endpoint rework
rlm_search/models.py           # HealthResponse.cascade_api field added
Makefile                        # backend target: port kill trap on INT/TERM
tests/test_repl_tools.py       # TestFiqhLookup class (4 tests) + fiqh_lookup assertions in LocalREPL test
tests/test_search_api.py       # Reworked TestHealthEndpoint (3 scenarios) + fixture patches discovery
```

## Prompt Evaluation Backlog (address one at a time)

Full evaluation completed — all 10 original recommendations implemented. 7 refinements remain, ordered by impact:

1. **Orphaned bullet points** (prompts.py:197-200): 4 lines duplicating content already covered elsewhere (scholars disagree, write code, prefer FINAL). Remove them — they contradict the worked example which uses FINAL_VAR.

2. **Worked example multi-turn clarity** (prompts.py:101-138): 5 separate ```repl blocks shown as if sequential in one shot, but RLM executes per-turn. Add "In your first turn:" / "In your next turn:" commentary so the agent understands it's multi-turn.

3. **fiqh_lookup endpoint mismatch**: repl_tools.py:170 calls `GET /bridge` but Cascade API exposes `POST /bridge/query` and `GET /bridge/dictionary`. Verify which endpoint exists — may 404 at runtime.

4. **sources_cited never flows back**: repl_tools.py:124 tracks cited source IDs but api.py:107-110 can't read them (REPL cleaned up). `sources` in done event is always `[]`. Related to the source extraction blocker above.

5. **format_evidence truncation too aggressive**: Answers truncated to 500 chars (repl_tools.py:147). When fed to llm_query for synthesis, sub-LLM sees incomplete rulings. Consider configurable limit or `format_evidence_full()` variant.

6. **No iteration budget awareness**: Agent doesn't know max_iterations=15 (config.py:22). May exhaust turns before reaching FINAL. Add a note like "You have ~15 turns — budget accordingly."

7. **browse() guidance too thin**: Prompt says "Browse documents by filter criteria" but doesn't say when to use browse vs search. Add: "Use browse for category exploration when you don't have a specific query."

## Next Steps (Sequenced)

1. Run `make check` to validate lint + format + tests
2. Commit all 7 files: `feat(search): add fiqh_lookup tool, rework health endpoint with cascade caching`
3. Pick one backlog item above — work it, test it, commit it

## Fresh Session Prompt

> Continue search backend work on `main`. 7 uncommitted files add `fiqh_lookup()` REPL tool (calls Cascade `/bridge`), replace static fiqh glossary in prompt, rework `/api/health` to cache Cascade URL at startup with async ping, add `cascade_api` field to `HealthResponse`, and add Makefile port-kill trap. Run `make check`, commit, then address source extraction TODO (REPL namespace cleaned up before sources readable — parse `[REPL:search]` lines from iteration SSE events).
