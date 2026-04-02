"""Custom system prompt for RLM agentic search."""

from __future__ import annotations

from rlm_search.config import PROMPT_LAYERS_DIR
from rlm_search.prompt_loader import assemble_prompt, load_layer_file, load_preamble
from rlm_search.tool_gate import generate_availability_section

# Sourced from _preamble.md — single source of truth.
# PROMPT_LAYERS_DIR override is checked first, so per-corpus deployments
# get a consistent preamble across system prompt and tool sub-prompts.
DOMAIN_PREAMBLE = load_preamble(override_dir=PROMPT_LAYERS_DIR)
VOICE = load_layer_file("_voice.md", override_dir=PROMPT_LAYERS_DIR)
ANSWER_FORMAT = load_layer_file("_answer_format.md", override_dir=PROMPT_LAYERS_DIR)

# Both cached at import time — restart server to pick up changes.
_raw_prompt = assemble_prompt(overrides_dir=PROMPT_LAYERS_DIR)
# Inject programmatically generated sections (single source of truth from code).
AGENTIC_SEARCH_SYSTEM_PROMPT = _raw_prompt.replace(
    "{TOOL_GATE_SECTION}", generate_availability_section()
)


def build_system_prompt(
    max_iterations: int = 15,
) -> str:
    """Build the full system prompt with iteration budget."""

    budget_section = f"""

## Iteration Budget

You have **{max_iterations} iterations** total. Each response you send costs one iteration — but you can include **multiple ```repl``` blocks in a single response** and they execute sequentially within the same iteration. Use this to chain dependent steps (search → check → draft) in one turn.

**Read `results["progress"]` after every `research()` call** — progress is auto-checked.

- **phase 'explore'** → search broadly with diverse angles, do NOT draft yet
- **phase 'ready'** → draft immediately (don't waste iterations)
- **phase 'continue'** → follow the guidance suggestion (1-2 more research calls)
- **phase still 'continue' after 3+ searches** → reformulate or try different category
- **After iteration {max_iterations - 3}** → draft and finalize regardless of evidence quality

Most questions resolve in 1-2 iterations. Use more only when check_progress says to."""

    return AGENTIC_SEARCH_SYSTEM_PROMPT + budget_section
