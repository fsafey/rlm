# RLM Agentic Search

LM-driven search over Islamic jurisprudence. Instead of a fixed cascade pipeline, the LM itself decides how to search — decomposing queries, running multiple searches, cross-referencing sources, and synthesizing answers with citations.

## Architecture

```
React Frontend (search-app/, port 3002)
  │ POST /api/search → { search_id }
  │ GET  /api/search/{id}/stream → SSE
  ▼
FastAPI Backend (rlm_search/, port 8092)
  │ ThreadPoolExecutor → rlm.completion()
  ▼
RLM Engine (rlm/)
  │ LM orchestrates via REPL:
  │   search("prayer menstruation", top_k=20)    ──→ Cascade API
  │   evaluate_results(question, results)          ──→ llm_query (sub-agent)
  │   reformulate(question, failed_query, score)  ──→ llm_query (sub-agent)
  │   format_evidence(results) + llm_query(...)   ──→ synthesis
  │   critique_answer(question, answer)            ──→ llm_query (sub-agent)
  │   FINAL_VAR("answer")
  ▼
Cascade Search API (https://cascade.imam-us.org)
```

### Capability Layers

```
Layer 2: Sub-agent tools (evaluate_results, reformulate, critique_answer)
         Wrap llm_query() with role-specific prompts. Fired by the main agent on demand.

Layer 1: REPL tools (search, browse, kb_overview, fiqh_lookup, format_evidence)
         Python functions calling Cascade API. Injected via setup_code.

Layer 0: Orchestrating LM
         Multi-turn REPL loop. Decides which tools and sub-agents to call.
```

Zero changes to the RLM core library. Uses `custom_system_prompt` and `environment_kwargs={"setup_code": ...}` to inject search tools into the REPL.

## Quick Start

### Prerequisites

- Cascade search API reachable (default: `https://cascade.imam-us.org`)
- `ANTHROPIC_API_KEY` set in environment or `.env`

### Backend

```bash
# Install deps (not in pyproject.toml — separate from core rlm)
uv pip install fastapi uvicorn httpx

# Run
uvicorn rlm_search.api:app --port 8092
```

### Frontend

```bash
cd search-app
npm install
npm run dev  # → http://localhost:3002
```

The Vite dev server proxies `/api/*` to the backend at port 8092.

## Team Testing (Cloudflare Tunnel)

Share a live URL with the scholar team — no infrastructure setup needed.

### Prerequisites

- `brew install cloudflared`
- Claude Code CLI authenticated (for `claude_cli` backend), or set `RLM_BACKEND=anthropic` + `ANTHROPIC_API_KEY`

### One Command

```bash
make tunnel
```

This starts backend + frontend + Cloudflare Tunnel. Look for the `*.trycloudflare.com` URL in the output and share it with the team.

**How it works:** Vite serves the React app and proxies `/api` to the backend. Cloudflared exposes the Vite dev server to the internet via an ephemeral tunnel — no DNS or firewall changes needed.

**Note:** The URL changes on each restart. For a persistent URL, configure a named Cloudflare Tunnel.

### Managing the Tunnel

**Stop everything:**

```bash
pkill -f "cloudflared tunnel"
lsof -ti :8092 :3002 | xargs kill
```

Ctrl+C on `make tunnel` only kills cloudflared — the backgrounded backend and frontend become orphan processes. Always clean up both ports.

**Restart just the backend** (e.g., after code changes to `rlm_search/`):

```bash
lsof -ti :8092 | xargs kill
make backend
```

The tunnel and frontend stay up — the Vite proxy reconnects automatically.

**Restart just the frontend:**

```bash
lsof -ti :3002 | xargs kill
make frontend
```

**Full restart:**

```bash
lsof -ti :8092 :3002 | xargs kill; pkill -f "cloudflared tunnel"
make tunnel
```

`make tunnel` kills any existing processes on the target ports before starting, so this is safe even if something is still running.

**Port conflicts:** If you see `[Errno 48] address already in use` or Vite falls back to another port, stale processes are occupying the ports. Kill them with `lsof -ti :8092 :3002 | xargs kill` and retry.

## Configuration

All via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `CASCADE_API_URL` | `https://cascade.imam-us.org` | Cascade search API base URL |
| `CASCADE_API_KEY` | `""` | API key for cascade (sent as `x-api-key` header) |
| `ANTHROPIC_API_KEY` | — | Required for default Anthropic backend |
| `RLM_BACKEND` | `anthropic` | LM backend (`anthropic`, `openai`, etc.) |
| `RLM_MODEL` | `claude-opus-4-6` | Model name |
| `RLM_MAX_ITERATIONS` | `15` | Max REPL iterations per search |
| `RLM_MAX_DEPTH` | `1` | Max RLM recursion depth |

## API Reference

### `POST /api/search`

Start an agentic search. Returns immediately with a search ID.

```json
// Request
{
  "query": "What are the rules for prayer during travel?",
  "settings": {
    "backend": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "max_iterations": 15,
    "max_depth": 1
  }
}

// Response
{ "search_id": "a1b2c3d4e5f6" }
```

### `GET /api/search/{search_id}/stream`

SSE stream of search progress. Events:

```
data: {"type": "metadata", "root_model": "...", "max_iterations": 15, ...}

data: {"type": "iteration", "iteration": 1, "response": "...", "code_blocks": [...], ...}

data: {"type": "done", "answer": "...", "sources": [...], "execution_time": 12.3, "usage": {...}}

data: {"type": "error", "message": "..."}
```

Stream terminates after `done` or `error`. 10-minute timeout.

#### Structured Tool Calls

Each `iteration` event includes a `tool_calls` array — structured records of every REPL tool invoked during that iteration, extracted from `REPLResult.locals`:

```json
{
  "tool": "search",
  "args": {"query": "prayer rules", "top_k": 10},
  "result_summary": {"num_results": 5, "total": 42, "query": "prayer rules"},
  "duration_ms": 150,
  "children": [],
  "error": null
}
```

Composite tools (`research`, `draft_answer`) record parent-child relationships via `children` indices — e.g. a `research` call's children include its `search` and `evaluate_results` calls.

`result_summary` fields per tool:

| Tool | Fields |
|---|---|
| `search` | `num_results`, `total`, `query` |
| `browse` | `num_results`, `total` |
| `fiqh_lookup` | `num_bridges`, `num_related` |
| `kb_overview` | `num_categories`, `total_documents` |
| `evaluate_results` | `num_rated`, `relevant`, `partial`, `off_topic` |
| `reformulate` | `num_queries` |
| `critique_answer` | `verdict` |
| `research` | `search_count`, `raw`, `unique`, `filtered`, `eval_summary` |
| `draft_answer` | `passed`, `revised`, `answer_length` |

The frontend's `SearchProgress.tsx` prefers structured `tool_calls` when present, falling back to stdout `[tag]` regex parsing for backward compatibility.

### `GET /api/health`

```json
{ "status": "ok", "version": "0.1.0" }
```

## REPL Tools

The LM has access to these functions inside its Python REPL. Tools are injected via `setup_code` — zero changes to RLM core.

### Search & Retrieval

| Tool | Signature | Purpose |
|------|-----------|---------|
| `kb_overview()` | `-> dict \| None` | Pre-cached taxonomy: categories, cluster labels (with doc counts), sample questions, subtopic tags. Call first to orient. |
| `search()` | `(query, filters=None, top_k=10) -> dict` | Semantic search. Returns `{results: [{id, score, question, answer, metadata}], total}`. Auto-bridges Arabic/English. |
| `browse()` | `(filters=None, offset=0, limit=20, sort_by=None, group_by=None, group_limit=4) -> dict` | Filter-based browsing. Returns results, facets, grouped_results. Use for exploration, not answering. |
| `fiqh_lookup()` | `(query) -> dict` | 453-term fiqh dictionary with Arabic/English bridging. For written answers, not search queries. |
| `format_evidence()` | `(results, max_per_source=3) -> list[str]` | Format results as `[Source: <id>] Q: ... A: ...` citation strings. Accepts `search()` return dict directly. |

### Synthesis

| Tool | Signature | Purpose |
|------|-----------|---------|
| `llm_query()` | `(prompt, model=None) -> str` | Cold sub-LLM call (~500K char input). No tools or history — prompt in, text out. |
| `llm_query_batched()` | `(prompts, model=None) -> list[str]` | Parallel version of `llm_query()`. |

### Sub-Agent Tools

These wrap `llm_query()` with role-specific prompts. Each costs one sub-LLM call but saves full iterations by catching problems early.

| Tool | Signature | When to use |
|------|-----------|-------------|
| `evaluate_results()` | `(question, results, top_n=5) -> str` | After search — rates each result RELEVANT/PARTIAL/OFF-TOPIC, suggests next step. Use when scores are mixed (0.2–0.5). |
| `reformulate()` | `(question, failed_query, top_score) -> list[str]` | Top score < 0.3 — returns up to 3 alternative query strings. |
| `critique_answer()` | `(question, draft) -> str` | Before FINAL — returns PASS/FAIL verdict checking citations, topic drift, unsupported claims. |

Classification is pre-computed at search init via `init_classify()` — access the result via the `classification` variable in the REPL.

### Utility

| Tool | Purpose |
|------|---------|
| `search_log` | Auto-populated list of every search/browse call with query, filters, result count. |
| `SHOW_VARS()` | Inspect all variables in the REPL. |
| `FINAL_VAR(name)` | Return the named variable as the final answer. |

### Taxonomy & Filters

| Code | Category |
|------|----------|
| `PT` | Prayer & Tahara (Purification) |
| `WP` | Worship Practices |
| `MF` | Marriage & Family |
| `FN` | Finance & Transactions |
| `BE` | Beliefs & Ethics |
| `OT` | Other Topics |

**Filter keys:** `parent_code` (str, e.g. `"PT"`), `cluster_label` (str, discover via `kb_overview()`), `subtopics` (str), `primary_topic` (str).

Example: `search("zakat", filters={"parent_code": "FN", "cluster_label": "Khums Asset Liability"})`

### Tool Selection Guide

| Situation | Action |
|-----------|--------|
| Starting a question | `kb_overview()` → `search(query, ...)` |
| Search scores < 0.3 | `reformulate(question, failed_query, top_score)` → search alternatives |
| Unsure if results match | `evaluate_results(question, results)` |
| Large result set | `format_evidence()` → `llm_query()` |
| Draft answer ready | `critique_answer(question, draft)` |
| Unsure which category | Inspect pre-computed `classification` variable |

### Score Interpretation

| Score | Meaning | Action |
|-------|---------|--------|
| > 0.5 | Strong match | Use directly |
| 0.3–0.5 | Partial | Verify relevance or call `evaluate_results()` |
| < 0.3 | Off-topic | Call `reformulate()` or change filters |
| 0 results | Filter too narrow | Drop filters, broaden query |

## Project Structure

```
rlm_search/
  __init__.py
  api.py                 # FastAPI app — department-model orchestrator
  bus.py                 # EventBus: single append-only event channel
  config.py              # Env var loading
  evidence.py            # EvidenceStore: owns source_registry, search_log, ratings
  kb_overview.py         # build_kb_overview() — async startup taxonomy fetch
  models.py              # Pydantic request/response models
  prompt_constants.py    # Shared thresholds and confidence weights
  prompts.py             # System prompt: tool docs, selection guide, worked examples
  quality.py             # QualityGate: confidence scoring, phases, critique tracking
  repl_tools.py          # build_search_setup_code() — injects all REPL tools + sub-agents
  sessions.py            # SessionManager: session lifecycle protocol
  sse.py                 # SSE router: reads from EventBus, supports replay
  streaming_logger.py    # StreamingLoggerV2 — delegates to EventBus
  tools/
    context.py           # SearchContext (thin wiring harness), ToolContext alias

search-app/
  src/
    App.tsx              # Main layout
    components/
      SearchInput.tsx    # Query box + settings panel
      SearchProgress.tsx # Phase-aware loading (structured tool_calls + stdout fallback)
      ExecutionPanel.tsx # Iteration detail: Code / Sub-LM Calls / Tool Calls tabs
      AnswerPanel.tsx    # Markdown-rendered answer with citations
      SourceCards.tsx    # Grid of cited source documents
      TracePanel.tsx     # Collapsible iteration trace
    lib/
      useSearch.ts       # SSE hook (POST → subscribe → state)
      parseCitations.ts  # Extract [Source: id] markers
      types.ts           # TypeScript interfaces for SSE events

tests/
  test_repl_tools.py     # Setup code, tool signatures, sub-agents, tool call tracking
  test_api_v2.py         # Endpoints, SSE streaming, tool_calls enrichment
  test_event_bus.py      # EventBus append-only semantics and replay
  test_evidence_store.py # EvidenceStore: source_registry, search_log, ratings
  test_quality_gate.py   # QualityGate: confidence scoring and phase transitions
  test_session_manager.py # SessionManager lifecycle protocol
  test_sse.py            # SSE router and replay support
  test_streaming_v2.py   # StreamingLoggerV2 → EventBus delegation
  test_tracker_v2.py     # Tool call tracker v2
```

## Testing

```bash
# Search-specific tests
uv run pytest tests/test_repl_tools.py tests/test_api_v2.py tests/test_event_bus.py tests/test_evidence_store.py tests/test_quality_gate.py tests/test_session_manager.py tests/test_sse.py tests/test_streaming_v2.py tests/test_tracker_v2.py -v

# Full RLM suite (~14s)
uv run pytest
```

## How It Works

1. **User submits query** → `POST /api/search`: SessionManager creates a session with an EventBus
2. **Search setup**: `_run_search()` builds a SearchContext with all departments, creates `StreamingLoggerV2(bus=bus)`, and launches `rlm.completion()` in a thread pool
3. **RLM execution**: LM orchestrates via REPL (orient, search, evaluate, synthesize, critique); the logger emits all events directly to the EventBus
4. **SSE stream**: `GET /api/search/{id}/stream` reads from EventBus via `sse.py`; supports replay on reconnection so no events are lost
5. **Frontend events**: typed SSE events consumed by the React UI — `metadata`, `iteration`, `tool_start`, `tool_end`, `done`/`error`
