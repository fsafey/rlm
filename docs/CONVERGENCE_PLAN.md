# RLM Search Convergence Plan

Cross-cutting fixes between **main** (`rlm/rlm_search/`) and **standalone** (`standalone-search/7_RLM_ENRICH/`).
Work progresses top-down — each phase is self-contained and shippable.

---

## Phase 1: Security & Hygiene (both repos)

Quick wins. No architectural changes. Each fix is independent.

### 1.1 — `repr=False` on `api_key` in main's `ToolContext`

**Problem**: Main's `ToolContext.api_key` appears in `repr()` output — any traceback, debug log, or `print(ctx)` leaks the Cascade API key.

**Standalone already fixed**: `api_key: str = dataclasses.field(default="", repr=False)`

**Fix**: One-line change in `rlm_search/tools/context.py:19`.

```python
# Before
api_key: str = ""
# After
api_key: str = dataclasses.field(default="", repr=False)
```

**Verify**: `uv run python -c "from rlm_search.tools.context import ToolContext; print(ToolContext(api_url='x', api_key='SECRET'))"`
Should NOT show `api_key='SECRET'` in output.

---

### 1.2 — API key via env var in main's `repl_tools.py`

**Problem**: Main embeds the Cascade API key as a string literal in `exec()`'d code:
```python
# rlm_search/repl_tools.py:46 (current)
api_key={api_key!r},
```
This means the key is visible to the LLM if it inspects REPL source or variables.

**Standalone already fixed**: Reads from env var at REPL runtime:
```python
# 7_RLM_ENRICH/core/repl_tools.py:48
api_key=_os.environ.get("_RLM_CASCADE_API_KEY", ""),
```

**Fix (two files)**:

1. `rlm_search/api.py` — set env var at startup (in `_run_search`, before RLM construction):
   ```python
   os.environ["_RLM_CASCADE_API_KEY"] = CASCADE_API_KEY
   ```
   Or better: set it once in module scope or `lifespan()`.

2. `rlm_search/repl_tools.py` — replace literal with env var read:
   ```python
   # Before (line 46 area)
   api_key={api_key!r},
   # After
   api_key=_os.environ.get("_RLM_CASCADE_API_KEY", ""),
   ```
   Also add `import os as _os` to the generated code string (standalone already does this).

**Verify**: Run a search, inspect the setup_code string — no API key literal should appear.

---

### 1.3 — `.gitignore` `rlm_logs/` in standalone

**Problem**: `7_RLM_ENRICH/rlm_logs/` contains 10 `.jsonl` files with real user-submitted Islamic questions — potentially PII. Committed to git.

**Fix**:
1. Add `rlm_logs/` to `7_RLM_ENRICH/.gitignore` (or project root `.gitignore`)
2. `git rm --cached 7_RLM_ENRICH/rlm_logs/*.jsonl`
3. Scrub from git history if sensitive (optional — `git filter-repo`)

**Verify**: `git status` shows deletions staged; `git log --diff-filter=A -- '*.jsonl'` to audit what was committed.

---

### 1.4 — Separate inbound auth key from outbound Cascade key (standalone)

**Problem**: Same `CASCADE_API_KEY` is used for:
- Authenticating inbound requests to `7_RLM_ENRICH` (`x-api-key` header check)
- Authenticating outbound requests to Cascade API

If the enrichment service is compromised, the attacker gets Cascade API access. If the Cascade key rotates, the enrichment service's auth also breaks.

**Fix**: Introduce `W3_ENRICH_API_KEY` (or `INBOUND_API_KEY`) env var for validating incoming requests. Keep `CASCADE_API_KEY` for outbound only.

**Files**: `config.py` (add new var), `main.py` (auth middleware uses new var), routes that check `x-api-key`.

**Verify**: Rotate one key without breaking the other.

---

## Phase 2: Config Correctness (standalone)

### 2.1 — Update `CASCADE_API_URL` default

**Problem**: `config.py:24` defaults to `https://cascade.vworksflow.com`. Comment says "TRANSITION: update to cascade.imam-us.org after DNS" — DNS is live, transition is stale.

**Fix**: Update default in `config.py`. Verify `.env` on production host (`gcp2-enrich`) already overrides this (it likely does, so the default is cosmetic but should still be correct).

---

### 2.2 — Sync README defaults with `config.py`

**Problem**: README documents different defaults than code:

| Variable | `config.py` | README |
|---|---|---|
| `RLM_BACKEND` | `claude_cli` | `anthropic` |
| `RLM_MODEL` | `claude-sonnet-4-6` | `claude-opus-4-6` |
| `CASCADE_API_URL` | `vworksflow.com` | `imam-us.org` |

**Fix**: Update README to match code (code is authoritative, README is stale).

---

### 2.3 — Fix `EnrichResponse` in sync endpoint

**Problem**: `POST /enrich` (`main.py:486-493`) always returns `confidence=0.0`, `needs_review=True`, empty `primary_topic`/`subtopics`/`ruling_numbers`. The actual values are in the logger's accumulated state and `tool_context.w3_state` — they're just never extracted.

**Fix**: After `rlm.completion()` returns, extract from `tool_context.w3_state`:
```python
tc = _extract_tool_context(rlm)
w3 = tc.w3_state if tc else {}
# Extract S4 classify output
classify_output = w3.get("s4_output", {})
response.primary_topic = classify_output.get("primary_topic", "")
response.subtopics = classify_output.get("subtopics", [])
response.ruling_numbers = classify_output.get("ruling_numbers", [])
# Extract S3 sanitize confidence
sanitize_output = w3.get("s3_output", {})
response.confidence = sanitize_output.get("confidence", 0.0)
response.needs_review = response.confidence < 0.7
```

**Verify**: `POST /enrich` with a test question, check response fields are populated.

---

### 2.4 — Add `requests` to `rlm-enrich` dependency group

**Problem**: `core/tools/api_tools.py` imports `requests`, but it's not in the `rlm-enrich` dependency group in `pyproject.toml`. Works only because the full dev env has it. A minimal `uv sync --only-group rlm-enrich` install would fail.

**Fix**: Add `requests` to the `rlm-enrich` group in `pyproject.toml`. Or migrate `api_tools.py` from `requests` to `httpx` (already a dep).

---

## Phase 3: Robustness (standalone)

### 3.1 — Concurrency cap with 503 on queue saturation

**Problem**: `ThreadPoolExecutor(max_workers=2)` limits concurrent work, but the executor's internal queue grows without bound. 100 concurrent POST requests = 100 queued `StreamingLogger` instances holding file handles and event loop iterators.

**Fix**: Track active + queued count. Return `503 Service Unavailable` when queue depth exceeds a threshold (e.g., 4 — 2 active + 2 queued).

```python
_MAX_QUEUED = 4  # 2 running + 2 waiting

@app.post("/api/search")
async def start_search(req):
    if len(_searches) >= _MAX_QUEUED:
        raise HTTPException(status_code=503, detail="Service busy, retry later")
    ...
```

---

### 3.2 — Thread `source_id` through `pipeline_complete` SSE event

**Problem**: `event_translator.py:146` hardcodes `"source_id": -1`. The frontend receives `-1` for every record, making it impossible to link the SSE event to the persisted `stage_results` row.

**Fix**: The `_run_single_enrich()` return dict contains the `source_id` from `persist_stage_results()`. Thread it through to the `done` event payload so the translator can include it. This requires the `mark_done()` call to accept and forward the `source_id`.

---

### 3.3 — Fix `progress_tools.py` stale suggestion signatures

**Problem**: Generated copy-paste code in `progress_tools.py:50` suggests `research(context, ...)` but the actual REPL wrapper signature is `research(query, ...)`. An LLM copying verbatim gets a `TypeError`.

**Fix**: Replace `context` with `query` (or the appropriate variable name) in the generated suggestion strings.

---

### 3.4 — Guard `CLAUDECODE` env var in Python, not just `start.sh`

**Problem**: `start.sh:25` does `unset CLAUDECODE` to prevent nested Claude CLI failures. But if the service starts without `start.sh`, the guard is absent.

**Fix**: Add to `main.py` or `config.py`:
```python
os.environ.pop("CLAUDECODE", None)
```
This makes the guard unconditional regardless of entry point.

---

## Phase 4: Feature Backports (main ← standalone)

### 4.1 — Add `search_multi()` to main

**Problem**: Main's `search()` only queries `enriched_gemini`. Standalone's `search_multi()` calls `/search/multi` with RRF + L5 reranking across multiple collections — strictly better for queries that span both Risala and enriched corpora.

**Source**: `7_RLM_ENRICH/core/tools/api_tools.py:128-209`

**Fix**:
1. Copy `search_multi()` to `rlm_search/tools/api_tools.py`
2. Add wrapper in `rlm_search/repl_tools.py` setup code
3. Document in `rlm_search/prompts.py` system prompt
4. Update `research()` in `composite_tools.py` to use `search_multi` when available

**Verify**: Run existing tests. Add a test for `search_multi()` in `tests/test_repl_tools.py`.

---

### 4.2 — Add `emit_event()` to main's `StreamingLogger`

**Problem**: Main lacks a generic event emitter. Every new SSE event type requires a dedicated method. Standalone added a 5-line `emit_event(event: dict)` at `core/streaming_logger.py:110-114`.

**Fix**:
```python
def emit_event(self, event: dict) -> None:
    """Emit an arbitrary event to the SSE stream."""
    if "timestamp" not in event:
        event["timestamp"] = datetime.now().isoformat()
    with self._lock:
        self.queue.append(event)
```

---

### 4.3 — Add API key auth to main (optional, pre-deployment)

**Problem**: Main exposes all endpoints without authentication. Fine for local dev, not for shared/cloud deployment.

**Fix**: Copy standalone's pattern — `x-api-key` header check as middleware or dependency. Gate behind an env var so local dev stays open:
```python
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")  # empty = no auth
```

---

## Phase 5: Tool Layer Unification (structural)

This is the big one. The shared tool layer exists as two diverging copies.

### 5.1 — Audit current divergence

Before unifying, enumerate every diff between the two `tools/` directories:

```bash
diff -rq rlm_search/tools/ 7_RLM_ENRICH/core/tools/
```

Known divergences:
- `context.py`: standalone adds `w3_state`, `pipeline_mode`, `existing_answer`, `repr=False`; main adds `classification`
- `api_tools.py`: standalone adds `search_multi()`
- `composite_tools.py`: standalone's `research()` may route through `search_multi` in `pipeline_mode="w3"`
- Import paths: main uses `rlm_search.tools.*`, standalone uses `core.tools.*`

### 5.2 — Make `rlm_search` an installable package

Currently `rlm_search/` is not in `pyproject.toml` as a package — it's run directly. To allow the standalone to `from rlm_search.tools import ...`, it needs to be installable.

**Options**:
- **A**: Add `rlm_search` to the existing `rlm` package's `pyproject.toml` as an extra package
- **B**: Keep `rlm_search` as a standalone installable with its own `pyproject.toml`
- **C**: Extract shared tools into `rlm/tools/` (within the core library) and have both consumers import from there

Option A is simplest. The standalone already does `uv pip install -e ~/projects/rlm`.

### 5.3 — Standalone subclasses main's `ToolContext`

Replace the vendored copy with:
```python
# 7_RLM_ENRICH/core/tools/context.py
from rlm_search.tools.context import ToolContext as _BaseToolContext

@dataclasses.dataclass
class W3ToolContext(_BaseToolContext):
    w3_state: dict = dataclasses.field(default_factory=dict)
    pipeline_mode: str = ""
    existing_answer: str | None = None
```

Main's `ToolContext` gets `repr=False` and `classification` stays. W3-specific fields live in the subclass.

### 5.4 — Standalone imports shared tools from `rlm_search`

Replace all `from core.tools import ...` with `from rlm_search.tools import ...` in:
- `core/repl_tools.py` (setup code string — uses string imports, so just change the module path)
- `core/tools/composite_tools.py` (if it imports from sibling modules)
- `core/tools/delegation_tools.py`

W3-specific tools (`w3/tools/`) stay local — they have no main equivalent.

### 5.5 — Delete vendored copies

Once imports are redirected, delete `7_RLM_ENRICH/core/tools/` files that are now imported from `rlm_search`:
- `api_tools.py`, `composite_tools.py`, `subagent_tools.py`, `tracker.py`
- `format_tools.py`, `normalize.py`, `constants.py`, `kb.py`
- `progress_tools.py`, `delegation_tools.py`

Keep only `context.py` (the subclass) and `__init__.py`.

**Verify**: Full test suite in both repos. The standalone's `start.sh` must have the correct `PYTHONPATH` for `rlm_search` imports to resolve.

---

## Phase 6: Feature Backports (standalone ← main)

Lower priority — standalone works, these are enhancements.

### 6.1 — Sessions / multi-turn support

Standalone creates a new RLM per request. Main's `SessionState` pattern allows follow-up queries to reuse the REPL (preserving `search_log`, `source_registry`, `tool_calls`). Valuable if the admin UI adds a "refine" flow.

### 6.2 — Two-step SSE with reconnect

Main's `POST → search_id → GET /stream` pattern allows:
- Browser tab reload without losing the stream
- Log replay from disk for completed searches
- Multiple clients watching the same search

### 6.3 — Sub-model routing for child RLMs

Main's `other_backends/other_backend_kwargs` routes depth-1 calls to a cheaper model. Standalone uses the same model for parent and child. Adding this would reduce cost on compound questions that fan out to `rlm_query()` children.

---

## Tracking

| Phase | Fix | Status |
|---|---|---|
| 1.1 | `repr=False` on main's `ToolContext.api_key` | done |
| 1.2 | API key via env var in main's `repl_tools.py` | done |
| 1.3 | `.gitignore` `rlm_logs/` in standalone | n/a (standalone not in repo) |
| 1.4 | Separate inbound/outbound auth keys | n/a (standalone not in repo) |
| 2.1 | Update `CASCADE_API_URL` default | done |
| 2.2 | Sync README defaults | done |
| 2.3 | Fix `EnrichResponse` in sync endpoint | n/a (standalone not in repo) |
| 2.4 | Add `requests` to dep group | n/a (standalone not in repo) |
| 3.1 | Concurrency cap with 503 | done |
| 3.2 | Thread `source_id` through SSE | n/a (standalone not in repo) |
| 3.3 | Fix `progress_tools` suggestion signatures | done |
| 3.4 | Guard `CLAUDECODE` in Python | done |
| 4.1 | Add `search_multi()` to main | |
| 4.2 | Add `emit_event()` to main's logger | |
| 4.3 | Add API key auth to main | |
| 5.1 | Audit tool layer divergence | |
| 5.2 | Make `rlm_search` installable | |
| 5.3 | Standalone subclasses `ToolContext` | |
| 5.4 | Redirect standalone imports | |
| 5.5 | Delete vendored copies | |
| 6.1 | Sessions in standalone | |
| 6.2 | Two-step SSE in standalone | |
| 6.3 | Sub-model routing in standalone | |
