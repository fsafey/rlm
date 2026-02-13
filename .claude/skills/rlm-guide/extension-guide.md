# RLM Extension Guide

## Adding a New LM Client

### Checklist

1. Create `rlm/clients/my_provider.py`
2. Add `"my_provider"` to `ClientBackend` literal in `rlm/core/types.py`
3. Add elif branch in `rlm/clients/__init__.py:get_client()`
4. Add optional dependency group in `pyproject.toml` (if needed)
5. Write tests in `tests/test_my_provider.py`

### Implementation Template

```python
# rlm/clients/my_provider.py
from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class MyProviderClient(BaseLM):
    def __init__(self, model_name: str = "default-model", **kwargs):
        super().__init__(model_name=model_name, **kwargs)
        # Initialize SDK client using env vars, NOT hardcoded keys
        self.client = MySDK(api_key=os.environ.get("MY_PROVIDER_API_KEY"))
        self._usage_history: list[ModelUsageSummary] = []

    def completion(self, prompt: str | dict[str, Any]) -> str:
        """Synchronous completion. Must return string."""
        # Handle both str and dict (message list) prompts
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = prompt  # Already a message list

        response = self.client.chat(model=self.model_name, messages=messages)
        self._track_usage(response)
        return response.content

    async def acompletion(self, prompt: str | dict[str, Any]) -> str:
        """Async completion for batched requests."""
        # Same logic, async SDK call
        response = await self.client.achat(model=self.model_name, messages=messages)
        self._track_usage(response)
        return response.content

    def get_usage_summary(self) -> UsageSummary:
        """Cumulative usage across all calls."""
        total = ModelUsageSummary(
            total_calls=len(self._usage_history),
            total_input_tokens=sum(u.total_input_tokens for u in self._usage_history),
            total_output_tokens=sum(u.total_output_tokens for u in self._usage_history),
        )
        return UsageSummary(model_usage_summaries={self.model_name: total})

    def get_last_usage(self) -> ModelUsageSummary:
        """Usage from most recent call."""
        return self._usage_history[-1] if self._usage_history else ModelUsageSummary(0, 0, 0)
```

### Registration

```python
# rlm/clients/__init__.py — add elif branch (lazy import)
def get_client(backend: ClientBackend, backend_kwargs: dict) -> BaseLM:
    # ... existing branches ...
    elif backend == "my_provider":
        from rlm.clients.my_provider import MyProviderClient
        return MyProviderClient(**backend_kwargs)
```

```python
# rlm/core/types.py — extend literal
ClientBackend = Literal[
    "openai", "anthropic", "gemini", "azure_openai", "portkey",
    "litellm", "openrouter", "vercel", "vllm", "claude_cli",
    "my_provider",  # NEW
]
```

### Key Requirements

- `completion()` must accept both `str` and `dict` (message history)
- `acompletion()` required for `llm_query_batched()` support
- Usage tracking must be per-call (not cumulative-only)
- Use env vars for API keys, NEVER hardcode
- Lazy import in `get_client()` to avoid pulling deps at module level

---

## Adding a New Environment

### Decision: NonIsolated vs Isolated

| Factor | NonIsolatedEnv | IsolatedEnv |
|--------|---------------|-------------|
| Runs on | Same machine as RLM | Remote machine/sandbox |
| Communication | TCP socket (direct) | HTTP broker (polled) |
| Latency | Low (local socket) | Higher (HTTP round-trips) |
| Security | Shared process space | Full isolation |
| Use when | Local dev, trusted code | Production, untrusted code |

### NonIsolatedEnv Checklist

1. Create `rlm/environments/my_env.py`
2. Subclass `NonIsolatedEnv`
3. Implement: `setup()`, `load_context()`, `execute_code()`
4. Add to `EnvironmentType` literal + `get_environment()` factory
5. Optional: implement `SupportsPersistence` protocol

```python
# rlm/environments/my_env.py
from rlm.environments.base_env import NonIsolatedEnv
from rlm.core.types import REPLResult


class MyEnv(NonIsolatedEnv):
    def __init__(self, lm_handler_address: tuple[str, int], **kwargs):
        super().__init__(lm_handler_address=lm_handler_address, **kwargs)

    def setup(self):
        """Initialize environment. Called once at creation."""
        # Set up execution context, inject llm_query, etc.
        pass

    def load_context(self, context_payload: dict | list | str):
        """Load user context into environment as variable."""
        # Make context_payload accessible as `context` in exec scope
        pass

    def execute_code(self, code: str) -> REPLResult:
        """Execute Python code, return structured result."""
        # Run code, capture stdout/stderr/locals
        return REPLResult(
            stdout=captured_stdout,
            stderr=captured_stderr,
            locals=accessible_vars,
            execution_time=elapsed,
            rlm_calls=sub_calls,
        )
```

### IsolatedEnv Checklist

1. Create environment class subclassing `IsolatedEnv`
2. Implement the HTTP broker in the sandbox (Flask app)
3. Implement host-side poller that hits broker endpoints
4. Handle serialization (dill for complex objects)
5. Reference: `rlm/environments/modal_repl.py` (canonical)

Broker endpoints your sandbox must expose:
- `POST /enqueue` — receives LM request from REPL code, blocks until response
- `GET /pending` — host polls for waiting requests
- `POST /respond` — host sends LM response back
- `GET /health` — liveness check

### SupportsPersistence Protocol

Only implement if your environment needs multi-turn state:

```python
@runtime_checkable
class SupportsPersistence(Protocol):
    def update_handler_address(self, address: tuple[str, int]) -> None: ...
    def add_context(self, payload, context_index: int | None = None) -> int: ...
    def get_context_count(self) -> int: ...
    def add_history(self, history, history_index: int | None = None) -> int: ...
    def get_history_count(self) -> int: ...
```

Currently only `LocalREPL` implements this.

---

## Injecting Custom Tools (Zero Core Changes)

### Pattern

```python
setup_code = """
import requests

def my_tool(query: str) -> dict:
    \"\"\"Search external API.\"\"\"
    print(f"[my_tool] Searching: {query}")  # stdout tag for UI detection
    response = requests.post(API_URL, json={"query": query})
    return response.json()
"""

rlm = RLM(
    custom_system_prompt="You have access to my_tool(query). Use it to...",
    environment_kwargs={"setup_code": setup_code},
)
result = rlm.completion(user_query)
```

### Rules for setup_code

1. **Executes at init time** via `execute_code()` — failure raises `SetupCodeError`
2. **Must be self-contained** — all imports inside the string
3. **Print `[tool_name]` tags** for stdout-based UI activity detection
4. **Test independently** before injecting:
   ```python
   env = LocalREPL(lm_handler_address=("127.0.0.1", 0))
   result = env.execute_code(setup_code)
   assert not result.stderr, f"Setup failed: {result.stderr}"
   ```

### Stdout-Tag Contract (for rlm_search UI)

Every REPL tool should print `[tag] description` to stdout:
- `[search] Searching for: quantum computing`
- `[browse] Browsing collection: articles, offset: 0`
- `[research] Investigating: climate change effects`

The frontend (`SearchProgress.tsx:detectActivity()`) classifies iterations by
matching these tags. Composite tools checked first (`[research]` before `[search]`)
to avoid sub-tool collisions.

When adding a new tool for rlm_search:
1. Include `[tool_name]` stdout prefix in the tool function
2. Add detection in `search-app/src/components/SearchProgress.tsx:detectActivity()`
3. Add transition text in `getActiveText()`

---

## Adding a New Sandbox Provider (End-to-End)

For a complete isolated environment (e.g., new cloud sandbox):

1. **Sandbox side**: Deploy Flask broker app with `/enqueue`, `/pending`, `/respond`, `/health`
2. **Host side**: Create `rlm/environments/my_sandbox.py` subclassing `IsolatedEnv`
3. **Poller**: Implement polling loop that checks `/pending`, routes to LMHandler, posts to `/respond`
4. **Serialization**: Use `dill` for complex objects (lambdas, closures)
5. **Optional dep**: Add to `pyproject.toml` as optional group
6. **Types**: Add to `EnvironmentType` literal
7. **Factory**: Add elif in `get_environment()` with lazy import
8. **Example**: Add `examples/my_sandbox_example.py`
9. **Tests**: Add `tests/test_my_sandbox.py` (mock or skip without credentials)

Reference implementation: `rlm/environments/modal_repl.py` + `AGENTS.md` (contributing guide)
