# Session Handoff — 2026-02-09 — Claude CLI Client Research & Config Prep

## Active Tasks

- [ ] Research `claude -p` CLI flags for optimal RLM integration -> Next: test flag combos, decide on configurable params
- [ ] Make `ClaudeCLI` client user-configurable (model, timeout, tools, permissions) -> `rlm/clients/claude_cli.py` | Next: add constructor params, wire to CLI flags

## Key Decisions

- `claude_cli` backend added to RLM: shells out to `claude -p`, no API key needed -> `rlm/clients/claude_cli.py`
- Registered in `ClientBackend` Literal type and `get_client()` factory -> `rlm/core/types.py:15`, `rlm/clients/__init__.py:60-63`
- `--tools ""` disables all tools, `--no-session-persistence` prevents state leakage between calls
- `--output-format text` for clean stdout parsing (no JSON wrapper)
- Token tracking returns 0s — CLI doesn't expose usage stats

## Essential Files

```
rlm/clients/claude_cli.py       # The client — main work target
rlm/clients/base_lm.py          # BaseLM ABC — interface contract
rlm/clients/__init__.py          # get_client() factory — already wired
rlm/core/types.py                # ClientBackend Literal — already has "claude_cli"
rlm/clients/anthropic.py         # Reference: well-structured client with per-model tracking
demo_real.py                     # Working demo using claude_cli backend
demo_architecture.py             # Mock-based demo showing full RLM loop
```

## Claude CLI Flags Available for Configuration

Key `claude -p` flags to expose as constructor params:

| Flag | Current | Configurable? | Notes |
|------|---------|---------------|-------|
| `--model <model>` | not set | YES | Override model (sonnet, opus, etc.) |
| `--system-prompt` | from messages | already handled | Extracted in `_build_prompt()` |
| `--tools <tools>` | `""` (disabled) | YES | Could allow specific tools |
| `--output-format` | `text` | maybe `json` | `stream-json` for streaming |
| `--max-budget-usd` | not set | YES | Cost guardrail |
| `--no-session-persistence` | always on | keep default | Correct for RLM sub-calls |
| `--permission-mode` | not set | YES | `bypassPermissions` for automated |
| `--allowedTools` | not set | YES | Fine-grained tool control |
| `--dangerously-skip-permissions` | not set | CAUTION | Only for sandboxed envs |
| `--append-system-prompt` | not set | YES | Add to default system prompt |
| timeout | 300s | YES | Already a param in subprocess.run |

## Blockers

- None blocking. All plumbing is wired. Client works end-to-end with `demo_real.py`.

## Uncommitted Changes

Modified: `README.md` (claude_cli docs), `rlm/clients/__init__.py` (factory), `rlm/core/types.py` (Literal), `uv.lock`
Untracked: `rlm/clients/claude_cli.py`, `demo_real.py`, `demo_architecture.py`, `.claude/`, `CLAUDE.md`, `rlm_logs/`

## Next Steps (Sequenced)

1. Decide which CLI flags to expose as `ClaudeCLI.__init__` params -> review table above
2. Add params to constructor: `model`, `timeout`, `max_budget_usd`, `permission_mode`, `allowed_tools` -> edit `rlm/clients/claude_cli.py:15`
3. Wire params into `cmd` list in both `completion()` and `acompletion()` -> lines 47-54, 68-75
4. Add tests for the new params -> `tests/`
5. Run `uv run ruff check --fix . && uv run ruff format . && uv run pytest`
6. Commit all changes: `git add rlm/clients/claude_cli.py rlm/clients/__init__.py rlm/core/types.py README.md`

## Fresh Session Prompt

> Add user-configurable params to `ClaudeCLI` client at `rlm/clients/claude_cli.py`. The client shells out to `claude -p` and currently hardcodes flags. Expose: `model` (--model), `timeout` (subprocess timeout, default 300), `max_budget_usd` (--max-budget-usd), `permission_mode` (--permission-mode), `allowed_tools` (--allowedTools), `extra_flags` (passthrough list). Wire into both `completion()` and `acompletion()` cmd construction. Reference `rlm/clients/anthropic.py` for pattern. Run `make check` after.
