# RLM Architecture Deep Dive

## Environment Hierarchy

```
BaseEnv (ABC)
  │
  ├── NonIsolatedEnv — same machine as LM, TCP socket communication
  │     ├── LocalREPL
  │     │     - Python exec() in-process with restricted builtins
  │     │     - Blocks: eval, exec, input (security)
  │     │     - Only env implementing SupportsPersistence
  │     │     - Thread-safe stdout capture via lock
  │     │     - Context stored to temp files for large strings
  │     │
  │     └── DockerREPL
  │           - Runs code in Docker container
  │           - TCP socket back to host LMHandler
  │
  └── IsolatedEnv — separate machine, HTTP broker pattern
        ├── ModalREPL (canonical reference for isolated pattern)
        ├── PrimeREPL
        ├── E2BREPL
        └── DaytonaREPL

SupportsPersistence (Protocol) — runtime_checkable
  - update_handler_address(address: tuple[str, int])
  - add_context(payload, context_index?) → int
  - get_context_count() → int
  - add_history(message_history, history_index?) → int
  - get_history_count() → int
```

## Communication Protocol Detail

### Non-Isolated (TCP Socket)

```
REPL code calls llm_query(prompt)
  │
  ├─ Build LMRequest(prompt=prompt, model=None, depth=current_depth+1)
  ├─ Serialize to JSON → UTF-8 bytes
  ├─ Send: [4-byte big-endian length][JSON payload]
  ├─ LMHandler receives on ThreadingTCPServer
  │   ├─ Decode length prefix → read exact bytes
  │   ├─ Parse JSON → LMRequest
  │   ├─ Route by depth:
  │   │   depth=1 + other_backend → other_client.completion()
  │   │   else → default_client.completion()
  │   └─ Build LMResponse(chat_completion=RLMChatCompletion)
  ├─ Send response same protocol (length prefix + JSON)
  └─ REPL receives → extracts response string
```

### Isolated (HTTP Broker)

```
Sandbox (Modal/Prime/E2B/Daytona)          Host (RLM process)
┌────────────────────────┐         ┌──────────────────────────┐
│ Flask broker server    │         │ Poller thread            │
│                        │         │                          │
│ Code calls llm_query() │         │ Loop:                    │
│   → POST /enqueue      │◄────────│   GET /pending           │
│   → blocks waiting     │         │   If request found:      │
│                        │         │     route to LM client   │
│ GET /respond (returns) │────────►│     POST /respond        │
│   → unblocks caller    │         │                          │
└────────────────────────┘         └──────────────────────────┘

Broker endpoints:
  POST /enqueue  — REPL code submits LM request, blocks until response
  GET  /pending  — Host polls for pending requests
  POST /respond  — Host sends LM response back
  GET  /health   — Liveness check
```

## LMHandler Internals

```python
class LMHandler:
    """ThreadingTCPServer wrapper managing LM client routing."""

    def __init__(
        self,
        client: BaseLM,
        host: str = "127.0.0.1",
        port: int = 0,  # auto-assign available port
        other_backend_client: BaseLM | None = None,
    ):
        self.default_client = client
        self.other_backend_client = other_backend_client
        self.clients: dict[str, BaseLM] = {}  # registered by model name
        self.register_client(client.model_name, client)

    def get_client(self, model: str | None = None, depth: int = 0) -> BaseLM:
        """Route by model name or depth."""
        if model and model in self.clients:
            return self.clients[model]
        if depth == 1 and self.other_backend_client is not None:
            return self.other_backend_client
        return self.default_client
```

### Batched Requests

`llm_query_batched(prompts)` sends all prompts concurrently:
1. REPL sends `LMRequest(prompts=[...], depth=1)`
2. LMHandler spawns `asyncio.gather(*[client.acompletion(p) for p in prompts])`
3. Returns `LMResponse(chat_completions=[...])`

## Message History Construction

Each iteration builds messages as:

```python
messages = [
    {"role": "system", "content": RLM_SYSTEM_PROMPT + context_metadata},
    {"role": "assistant", "content": "I have access to context..."},
    {"role": "user", "content": build_user_prompt(iteration=0)},
    # After iteration 0:
    {"role": "assistant", "content": "```repl\ncode...\n```"},
    {"role": "user", "content": format_iteration(result) + build_user_prompt(iteration=1)},
    # ... accumulates
]
```

User prompts vary by iteration index — early iterations encourage exploration,
later iterations push toward synthesis.

## System Prompt Structure

`rlm/utils/prompts.py:RLM_SYSTEM_PROMPT` (~800 lines):
- Role definition (Python REPL agent)
- Available tools: `llm_query()`, `llm_query_batched()`, `FINAL_VAR()`, `SHOW_VARS()`
- Code block format: ` ```repl ... ``` `
- Termination format: `FINAL(answer)` or `FINAL_VAR(varname)`
- Guidelines for decomposition, exploration, synthesis
- Examples of good REPL usage patterns

`custom_system_prompt` parameter prepends to or replaces this.

## Persistence Model (LocalREPL only)

```python
# Multi-turn: REPL state survives across completion() calls
rlm = RLM(environment="local")

# Turn 1: context loaded, REPL state established
result1 = rlm.completion("Analyze this data", context=data)

# Turn 2: REPL still has all variables from turn 1
# New context added as context_1, prior conversation as history_0
result2 = rlm.completion("Now compare with this", context=new_data)
```

Persistence protocol:
- `add_context()` → creates `context_N` variable, aliases `context_0` as `context`
- `add_history()` → stores deep copy of message history as `history_N`
- `update_handler_address()` → reconnects to new LMHandler between turns
- REPL global namespace persists between calls (variables, functions, imports survive)

## Error Handling Strategy

```
Code execution errors:
  1st error  → captured in REPLResult.stderr, continue to next block
  2nd consecutive error → skip all remaining blocks in this iteration
  → LM sees errors in next iteration's context, can self-correct

SetupCodeError:
  → Raised immediately at init if setup_code fails
  → Prevents silent degradation of injected tools

LM completion errors:
  → Propagated up (no retry logic in core)
  → Caller responsible for retry/fallback

Depth overflow:
  → depth >= max_depth → _fallback_answer() (plain LM, no REPL)
  → Graceful degradation, not error

Iteration overflow:
  → max_iterations reached → _default_answer()
  → Sends "please provide final answer" nudge, one more LM call
```
