# CLAUDE.md

Recursive Language Models (RLMs) — task-agnostic inference paradigm enabling LMs to programmatically examine, decompose, and recursively call themselves over input. Replaces `llm.completion()` with `rlm.completion()`.

## Stack & Structure

**Stack**: Python 3.11+ (uv/ruff/ty/pytest) + Next.js visualizer

| Directory            | Purpose                                                |
| -------------------- | ------------------------------------------------------ |
| `rlm/core/`          | Core engine: RLM class, types, LM handler              |
| `rlm/clients/`       | LM provider integrations (BaseLM subclasses)           |
| `rlm/environments/`  | REPL environments (local, Docker, Modal, Prime, E2B, Daytona) |
| `rlm/utils/`         | Parsing, prompts, constants                            |
| `rlm/logger/`        | Trajectory logging (.jsonl)                            |
| `tests/`             | pytest test suite                                      |
| `visualizer/`        | Next.js trajectory viewer (shadcn/ui)                  |
| `examples/`          | Usage examples                                         |
| `docs/`              | Documentation site (Next.js)                           |

## Critical Rules

### Python

- Ruff enforced: line-length 100, target py311, double quotes
- `ty` for type checking (in dev deps)
- Explicit types preferred. No `# type: ignore` without justification.
- Error handling: fail fast, fail loud. No silent fallbacks.

### Git

- Format: `type(scope): description`
- Run before PR: `make check` (lint + format + test)

### Security

- **NEVER** commit API keys or secrets
- Environment variables for all provider keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)

## Essential Commands

```bash
make check                              # Full lint + format + test (preferred)
uv run pytest                           # Run tests only
uv run ruff check --fix . && uv run ruff format .  # Lint + format
uv run python -c "from rlm import RLM"  # Verify import
uv sync --group dev --group test        # Install dev deps
cd visualizer && npm run dev            # Trajectory viewer (localhost:3001)
```

### Optional Dependency Groups

```bash
uv pip install -e ".[modal]"            # Modal sandbox
uv pip install -e ".[e2b]"             # E2B sandbox
uv pip install -e ".[daytona]"         # Daytona sandbox
uv pip install -e ".[prime]"           # Prime sandbox
```

## Architecture

### Completion Loop (core algorithm)

```
RLM.completion(prompt)
  │
  ├─ depth >= max_depth? → _fallback_answer() (plain LM call)
  │
  └─ _spawn_completion_context()          # context manager
       ├── get_client() → BaseLM          # factory, lazy import
       ├── LMHandler(client)              # ThreadingTCPServer wrapper
       └── get_environment() → BaseEnv    # factory, lazy import
       │
       for i in range(max_iterations):
         ├── lm_handler.completion(history) → response
         ├── find_code_blocks(response) → code strings
         ├── environment.execute_code(code) → REPLResult
         └── find_final_answer(response)?
               ├── yes → return RLMChatCompletion
               └── no  → append to history, continue
       │
       └── _default_answer() (ran out of iterations)
```

### Environment Hierarchy

```
BaseEnv (ABC)
  ├── NonIsolatedEnv — same machine as LM
  │     ├── LocalREPL (exec in-process, supports persistence)
  │     └── DockerREPL (Docker container)
  │
  └── IsolatedEnv — separate machine, HTTP broker
        ├── ModalREPL (Modal sandbox)
        ├── PrimeREPL (Prime sandbox)
        ├── E2BREPL (E2B sandbox)
        └── DaytonaREPL (Daytona sandbox)

SupportsPersistence (Protocol) — multi-turn state (only LocalREPL currently)
  Methods: update_handler_address, add_context, get_context_count, add_history, get_history_count

Communication:
  Non-isolated: TCP socket (4-byte length prefix + JSON)
  Isolated:     HTTP broker (Flask in sandbox ↔ poller on host)
```

### Data Model

```
RLMChatCompletion (top-level return from completion())
  └── UsageSummary → dict[str, ModelUsageSummary]

RLMIteration (one LLM turn + code execution)
  ├── CodeBlock (one code block)
  │     └── REPLResult (stdout, stderr, locals, execution_time, rlm_calls)
  └── final_answer: str | None

RLMMetadata (logged once per completion)
```

All types in `rlm/core/types.py`. Dataclasses with `to_dict()`/`from_dict()` round-trip.

### Supported Backends

`ClientBackend` literal: openai, anthropic, gemini, azure_openai, portkey, litellm, openrouter, vercel, vllm, claude_cli

### Key Abstractions

| Base Class           | File                            | Extend For          |
| -------------------- | ------------------------------- | ------------------- |
| `BaseLM`             | `rlm/clients/base_lm.py`       | New LM providers    |
| `NonIsolatedEnv`     | `rlm/environments/base_env.py` | Local-style REPLs   |
| `IsolatedEnv`        | `rlm/environments/base_env.py` | Cloud sandbox REPLs |
| `SupportsPersistence`| `rlm/environments/base_env.py` | Multi-turn envs     |

### Registration Pattern

Both `rlm/clients/__init__.py` and `rlm/environments/__init__.py` use the same pattern:
- Factory function (`get_client` / `get_environment`) with if/elif routing
- **Lazy imports** inside each branch to avoid pulling optional deps at module level
- New client/env: add elif branch + update `ClientBackend`/`EnvironmentType` literal in `rlm/core/types.py`

## Testing

```bash
uv run pytest                                     # All tests
uv run pytest tests/test_local_repl.py -v         # Specific file
uv run pytest -k "test_parsing" -v                # By pattern
```

- Tests live in `tests/`, mirror source structure loosely
- `tests/mock_lm.py` provides a mock BaseLM for tests that don't need real API calls
- Persistence tests: `tests/test_local_repl_persistent.py`, `tests/test_multi_turn_integration.py`
- No real API calls in CI — mock or skip
