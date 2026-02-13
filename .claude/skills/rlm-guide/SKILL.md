---
name: rlm-guide
description: >
  RLM consultant and teacher — explains the Recursive Language Models paradigm,
  architecture, algorithm, type system, extension points, and debugging. Use when
  the user asks "how does RLM work", "explain RLM", "RLM architecture", "how to
  extend RLM", "add a new client/environment", "RLM vs", "what is context rot",
  "RLM recursion", "completion loop", "REPL protocol", "rlm_search", or any
  question about RLM concepts, design, or usage.
disable-model-invocation: true
---

# RLM Guide — Consultant & Teacher

You are an expert consultant on the Recursive Language Models (RLM) paradigm.
Apply the ACRE method (Anchor, Chunk, Render, Expose edges) from the explainer skill
when teaching. Match depth to the user's signal.

---

## 1. The Paradigm in One Sentence

RLM replaces `llm.completion(prompt)` with `rlm.completion(prompt)` — the LM writes
and executes Python code to examine its input, then calls itself recursively on
sub-problems, trading latency for unbounded context scalability.

### Anchor (for newcomers)

Think of a librarian. A normal LLM tries to read the entire library at once and
answer your question from memory — it forgets the middle shelves (context rot).
An RLM librarian instead:
1. Writes a card catalog query (Python code) to find relevant books
2. Reads only the relevant pages (REPL execution)
3. If a page references another book, sends an assistant to fetch it (recursive `llm_query()`)
4. Compiles the answer from focused reads, never holding the whole library in mind

The REPL is the card catalog. Recursion is the assistant. Context never rots because
the LM only processes what it explicitly retrieves.

### Key Design Choices

1. **Context as Python variable** — data lives in REPL memory, processable programmatically
2. **Recursive LM calls from REPL** — root model never sees full context, avoiding context rot

### Results

- Processes inputs **100x beyond model context windows**
- Outperforms vanilla long-context LLMs and common scaffolds (RAG, map-reduce)
- First post-trained model (RLM-Qwen3-8B) approaches GPT-5 on 3 benchmarks

---

## 2. Core Algorithm

```
RLM.completion(prompt)
  │
  ├─ depth >= max_depth? → _fallback_answer() (plain LM call, no REPL)
  │
  └─ _spawn_completion_context()
       ├── LMHandler (TCP server on ephemeral port)
       ├── Environment (LocalREPL, ModalREPL, etc.)
       └── Inject: context var, llm_query(), llm_query_batched(),
           FINAL_VAR(), SHOW_VARS(), + any setup_code tools
       │
       for i in range(max_iterations):
         ├── lm_handler.completion(history) → LM response
         ├── find_code_blocks(response) → ```repl``` blocks (regex)
         ├── For each block:
         │     environment.execute_code(code) → REPLResult
         │     (SyntaxError → immediate skip; 2+ consecutive errors → skip remaining)
         ├── find_final_answer(response)?
         │     FINAL(answer) → direct answer
         │     FINAL_VAR(varname) → retrieve variable value
         │     Found → return RLMChatCompletion
         └── Not found → format results, append to history, continue
       │
       └── max_iterations exhausted → _default_answer() (nudge + final call)
```

### Iteration Data Flow

Each iteration: LM produces response with `\`\`\`repl` code blocks → code executes
in persistent REPL → stdout/stderr/locals captured → formatted and appended to
message history → next iteration sees all prior results.

---

## 3. Recursion Semantics

**Critical distinction**: "Recursive" means the LM can call itself via `llm_query()`
from within REPL code. It does NOT mean nested RLM loops.

```
RLM (depth=0) [has REPL loop, iterates]
  └─ llm_query() → depth=1 LM [plain completion, NO REPL]
       └─ Returns string directly
```

- **depth=0**: Full RLM loop (REPL + iterations)
- **depth=1**: Plain `BaseLM.completion()` — no REPL, no code execution
- **depth >= 2**: Not supported (falls back)
- `other_backends` / `other_backend_kwargs` route depth=1 to a different model

**NOT recursive RLM spawning** — `llm_query()` sends a raw prompt to LMHandler,
which routes to the appropriate client. No new environment or completion loop.

---

## 4. Type System

```
RLMChatCompletion          ← top-level return
  ├── root_model: str
  ├── prompt: str | dict
  ├── response: str        ← final answer
  ├── usage_summary: UsageSummary
  │     └── model_usage_summaries: dict[str, ModelUsageSummary]
  │           ├── total_calls: int
  │           ├── total_input_tokens: int
  │           └── total_output_tokens: int
  └── execution_time: float

RLMIteration               ← one LLM turn (logged)
  ├── prompt, response
  ├── code_blocks: list[CodeBlock]
  │     └── CodeBlock
  │           ├── code: str
  │           └── result: REPLResult
  │                 ├── stdout, stderr: str
  │                 ├── locals: dict
  │                 ├── execution_time: float
  │                 └── rlm_calls: list[RLMChatCompletion]
  ├── final_answer: str | None
  └── iteration_time: float

RLMMetadata                ← config snapshot (logged once)
  └── root_model, max_depth, max_iterations, backend, environment_type, ...
```

Literal types:
- `ClientBackend`: openai, anthropic, gemini, azure_openai, portkey, litellm, openrouter, vercel, vllm, claude_cli
- `EnvironmentType`: local, docker, modal, prime, daytona, e2b

All dataclasses with `to_dict()` / `from_dict()` round-trip. Types in `rlm/core/types.py`.

---

## 5. Architecture Overview

```
                        ┌─────────────────────────────────┐
                        │           RLM Engine             │
                        │  rlm/core/rlm.py                │
                        │  (completion loop, depth routing)│
                        └──────────┬──────────┬───────────┘
                                   │          │
                    ┌──────────────┘          └──────────────┐
                    ▼                                        ▼
          ┌─────────────────┐                     ┌──────────────────┐
          │   LM Clients    │                     │  Environments    │
          │ rlm/clients/    │                     │ rlm/environments/│
          │ BaseLM subclass │                     │ BaseEnv subclass │
          └────────┬────────┘                     └────────┬─────────┘
                   │                                       │
        ┌──────────┼──────────┐              ┌─────────────┼──────────────┐
        ▼          ▼          ▼              ▼             ▼              ▼
    OpenAI   Anthropic   Gemini...    NonIsolatedEnv   IsolatedEnv
                                      ├─ LocalREPL     ├─ ModalREPL
                                      └─ DockerREPL    ├─ PrimeREPL
                                                       ├─ E2BREPL
                                                       └─ DaytonaREPL
```

### Communication Protocols

| Type | Protocol | Details |
|------|----------|---------|
| Non-isolated | TCP socket | 4-byte big-endian length prefix + UTF-8 JSON |
| Isolated | HTTP broker | Flask in sandbox, poller on host (`/enqueue`, `/pending`, `/respond`) |

### Factory/Registration Pattern

Both `rlm/clients/__init__.py` and `rlm/environments/__init__.py`:
- Factory function (`get_client` / `get_environment`) with if/elif routing
- **Lazy imports** inside each branch (no optional deps at module level)
- Add new: elif branch + update literal in `types.py`

For deep architecture details: Read [architecture.md](architecture.md)

---

## 6. Extension Points

### Add a New LM Client

1. Create `rlm/clients/my_provider.py`
2. Subclass `BaseLM` — implement `completion()`, `acompletion()`, `get_usage_summary()`, `get_last_usage()`
3. Add `"my_provider"` to `ClientBackend` literal in `rlm/core/types.py`
4. Add elif branch in `rlm/clients/__init__.py:get_client()`

### Add a New Environment

1. Create `rlm/environments/my_env.py`
2. Subclass `NonIsolatedEnv` or `IsolatedEnv`
3. Implement `setup()`, `load_context()`, `execute_code()`
4. Add to `EnvironmentType` literal, add elif in `get_environment()`
5. Optional: implement `SupportsPersistence` for multi-turn state

### Inject Custom Tools (zero core changes)

```python
rlm = RLM(
    custom_system_prompt="You have access to search() and browse()...",
    environment_kwargs={"setup_code": setup_code_string}
)
```

`setup_code` executes at environment init time via `execute_code()`.
Failure raises `SetupCodeError` immediately (fail fast).

For extension checklists and patterns: Read [extension-guide.md](extension-guide.md)

---

## 7. rlm_search — Application Layer Example

Demonstrates the injection pattern — zero core modifications.

```
POST /api/search → search_id → GET /api/search/{id}/stream (SSE)

SSE events: metadata → iteration* → done | error

_run_search():
  build_search_setup_code()       # injects search(), browse(), search_log
  RLM(
    custom_system_prompt=...,     # tool docs + domain taxonomy
    environment_kwargs={"setup_code": setup_code},
    logger=StreamingLogger        # sync thread → async SSE bridge
  ).completion(query)
```

**Stack**: FastAPI (port 8092) + Vite/React (port 3002, proxies `/api/*`)
**REPL tools**: `search(query, collection, filters, top_k)`, `browse(collection, filters, offset, limit)` → Cascade API
**Bridge**: `StreamingLogger(RLMLogger)` — sync RLM thread → async SSE via list+lock drain

---

## 8. Key Files Reference

| File | Purpose |
|------|---------|
| `rlm/core/rlm.py` | Completion loop, depth routing, iteration management |
| `rlm/core/types.py` | Full data model (all dataclasses + literals) |
| `rlm/core/lm_handler.py` | TCP server, client routing, batched requests |
| `rlm/core/comms_utils.py` | Socket protocol (LMRequest/LMResponse) |
| `rlm/utils/prompts.py` | System prompt (~800 lines), user prompt builder |
| `rlm/utils/parsing.py` | Code block regex, FINAL/FINAL_VAR extraction |
| `rlm/environments/base_env.py` | BaseEnv, NonIsolatedEnv, IsolatedEnv, SupportsPersistence |
| `rlm/environments/local_repl.py` | Python exec sandbox, llm_query injection, persistence |
| `rlm/clients/base_lm.py` | BaseLM abstract interface |

---

## 9. Gotchas & Debugging

| Gotcha | Impact | Mitigation |
|--------|--------|------------|
| `max_depth=1` only tested depth | depth > 1 not designed | Stick to default |
| Message history NOT truncated | Long conversations hit context limits | User must manage |
| `setup_code` runs at init time | `SetupCodeError` on injection failure | Test code strings independently |
| SyntaxError or 2+ consecutive errors | Remaining code blocks silently skipped | Fix errors early in block sequence |
| `fastapi`/`uvicorn` not in pyproject.toml | Import errors for rlm_search | `uv pip install fastapi uvicorn httpx` |
| `context` always aliases `context_0` | Adding context_1+ doesn't change alias | Access by index explicitly |
| Batched requests use `asyncio.run()` | New event loop per call in LocalREPL | Fine for single-threaded REPL |
| Ruff import sorting | Lint failures | Separate stdlib/third-party/local blocks |

---

## 10. External Resources (ranked by pedagogical value)

1. **[arXiv Paper](https://arxiv.org/abs/2512.24601)** — Full spec, experiments, RLM-Qwen3-8B training
2. **[Author's Blog](https://alexzhang13.github.io/blog/2025/rlm/)** — Accessible intro (Oct 2025)
3. **[Official GitHub](https://github.com/alexzhang13/rlm)** — Production code, examples
4. **[DSpy Module](https://dspy.ai/api/modules/RLM/)** — Framework integration
5. **[Prime Intellect Blog](https://www.primeintellect.ai/blog/rlm)** — "The paradigm of 2026"
6. **[Context Rot Study](https://research.trychroma.com/context-rot)** — Empirical motivation
7. **[RLM-Qwen3-8B](https://huggingface.co/mit-oasys/rlm-qwen3-8b-v0.1)** — Post-trained model
8. **[Official Docs](https://alexzhang13.github.io/rlm/)** — Online reference

**Recommended reading order**: Blog (2) → Paper (1) → `docs/getting-started.md` → `AGENTS.md` → source code

---

## Routing: How to Respond

| User signal | Depth | Approach |
|-------------|-------|----------|
| "what is RLM", "explain RLM" | Surface | Section 1 (anchor + paradigm) |
| "how does the completion loop work" | Medium | Section 2 (algorithm) + read `rlm/core/rlm.py` |
| "how does recursion work in RLM" | Medium | Section 3 (recursion semantics) |
| "RLM architecture", "environment hierarchy" | Deep | Section 5 + read [architecture.md](architecture.md) |
| "add a new client/environment" | Practical | Section 6 + read [extension-guide.md](extension-guide.md) |
| "how does rlm_search work" | Applied | Section 7 + read `rlm_search/` source |
| "RLM vs RAG", "vs long-context" | Comparative | Sections 1 + 10 (context rot motivation) |
| "debugging", "error", "gotcha" | Diagnostic | Section 9 + inspect specific files |
| "types", "data model" | Reference | Section 4 + read `rlm/core/types.py` |

When answering, always:
1. Start from the user's context (problem-first, not implementation-first)
2. Include a visual (diagram, table, or code block) for non-trivial concepts
3. Point to specific files with `file:line` references
4. Expose at least one edge case or misconception
5. If the question requires code-level detail, **read the actual source files** — don't rely solely on this skill's summaries
