"""Custom system prompt for RLM agentic search."""

from __future__ import annotations

from pathlib import Path

from rlm_search.prompt_loader import assemble_prompt

DOMAIN_PREAMBLE = (
    "Sources are from I.M.A.M. (imam-us.org), a Shia Ithna Ashari organization. "
    "All rulings follow Ja'fari fiqh. Present and assess within this school of thought — "
    "do not apply, compare, or flag rulings based on Sunni or other jurisprudential standards.\n\n"
)

# Assembled from layer files — replaces the former monolithic string.
# Kept as a module-level constant for backward compat (tests import it).
AGENTIC_SEARCH_SYSTEM_PROMPT = assemble_prompt()


def build_system_prompt(
    max_iterations: int = 15,
    layers_override_dir: Path | None = None,
) -> str:
    """Build the full system prompt with iteration budget.

    Args:
        max_iterations: Iteration budget to inject.
        layers_override_dir: Optional directory of layer files that shadow
            the defaults. Files with matching names replace the default;
            new files are appended in sort order.
    """
    if layers_override_dir is not None:
        base = assemble_prompt(overrides_dir=layers_override_dir)
    else:
        base = AGENTIC_SEARCH_SYSTEM_PROMPT

    budget_section = f"""

## Iteration Budget

You have **{max_iterations} iterations** total. Each response you send costs one iteration — but you can include **multiple ```repl``` blocks in a single response** and they execute sequentially within the same iteration. Use this to chain dependent steps (search → check → draft) in one turn.

**Read check_progress() after every research() call.** It tells you whether to draft or keep searching.

- **check_progress() returns phase 'explore'** → search broadly with diverse angles, do NOT draft yet
- **check_progress() returns phase 'ready'** → draft immediately (don't waste iterations)
- **check_progress() returns phase 'continue'** → follow the guidance suggestion (1-2 more research calls)
- **phase is still 'continue' after 3+ searches** → reformulate or try different category
- **After iteration {max_iterations - 3}** → draft and finalize regardless of evidence quality

Most questions resolve in 1-2 iterations. Use more only when check_progress says to."""

    return base + budget_section
