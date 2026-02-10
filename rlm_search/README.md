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
  │ LM writes Python in REPL:
  │   search("prayer menstruation", top_k=20)
  │   browse(filters={"parent_code": "PT"})
  │   llm_query("synthesize these findings...")
  │   FINAL_VAR("answer")
  ▼
Cascade Search API (port 8091, existing)
```

Zero changes to the RLM core library. Uses `custom_system_prompt` and `environment_kwargs={"setup_code": ...}` to inject search tools into the REPL.

## Quick Start

### Prerequisites

- Cascade search API running on port 8091
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

## Configuration

All via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `CASCADE_API_URL` | `http://localhost:8091` | Cascade search API base URL |
| `CASCADE_API_KEY` | `""` | API key for cascade (sent as `x-api-key` header) |
| `ANTHROPIC_API_KEY` | — | Required for default Anthropic backend |
| `RLM_BACKEND` | `anthropic` | LM backend (`anthropic`, `openai`, etc.) |
| `RLM_MODEL` | `claude-sonnet-4-20250514` | Model name |
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

### `GET /api/health`

```json
{ "status": "ok", "version": "0.1.0" }
```

## REPL Tools

The LM has access to these functions inside its Python REPL:

### `search(query, filters=None, top_k=10)`

Semantic search against the knowledge base. Returns `{"results": [{"id", "score", "question", "answer", "metadata"}]}`.

### `browse(filters=None, offset=0, limit=20)`

Browse documents by filter (no query needed). Useful for exploring a category.

### `llm_query(prompt, model=None)`

Sub-LM call for synthesis or analysis of retrieved documents.

### `FINAL_VAR(variable_name)`

Return the final answer stored in the named variable.

### Taxonomy Filters

| Code | Category |
|------|----------|
| `PT` | Prayer & Tahara (Purification) |
| `WP` | Worship Practices |
| `MF` | Marriage & Family |
| `FN` | Finance & Transactions |
| `BE` | Beliefs & Ethics |
| `OT` | Other Topics |

Example: `search("zakat", filters={"parent_code": "FN"})`

## Project Structure

```
rlm_search/
  __init__.py
  config.py              # Env var loading
  repl_tools.py          # build_search_setup_code() — injects tools into REPL
  prompts.py             # Custom system prompt with tool docs + taxonomy
  streaming_logger.py    # StreamingLogger(RLMLogger) — sync→async bridge
  models.py              # Pydantic request/response models
  api.py                 # FastAPI app with SSE streaming

search-app/
  src/
    App.tsx              # Main layout
    components/
      SearchInput.tsx    # Query box + settings panel
      SearchProgress.tsx # Phase-aware loading indicator
      AnswerPanel.tsx    # Markdown-rendered answer with citations
      SourceCards.tsx    # Grid of cited source documents
      TracePanel.tsx     # Collapsible iteration trace
    lib/
      useSearch.ts       # SSE hook (POST → subscribe → state)
      parseCitations.ts  # Extract [Source: id] markers
      types.ts           # TypeScript interfaces for SSE events

tests/
  test_repl_tools.py     # 19 tests — setup code validity, signatures, mocked API
  test_search_api.py     # 10 tests — endpoints, SSE streaming, cleanup
```

## Testing

```bash
# Search-specific tests (29 tests, <1s)
uv run pytest tests/test_repl_tools.py tests/test_search_api.py -v

# Full RLM suite (181+ tests, ~14s)
uv run pytest
```

## How It Works

1. **User submits query** → `POST /api/search` creates a `StreamingLogger` and launches `rlm.completion()` in a thread pool
2. **RLM REPL loop** — the LM writes Python code that calls `search()` and `browse()`, which hit the cascade API at port 8091. Each iteration is logged via `StreamingLogger`
3. **SSE stream** — the frontend polls `StreamingLogger.drain()` every 200ms, pushing events to the React UI as they arrive
4. **Answer** — when the LM calls `FINAL_VAR("answer")`, the completion returns and a `done` event is emitted with the synthesized answer, sources, and usage stats
