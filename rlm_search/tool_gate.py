"""Tool gating by classification confidence — controls REPL tool visibility."""

from __future__ import annotations

from typing import Any

# Tools removed per tier. Keyed by tier name.
# focused: HIGH confidence, single category — only core search + draft
# standard: MEDIUM confidence — drop rlm_query (expensive delegation)
# full: LOW or cross-category — all tools available
TIER_REMOVALS: dict[str, frozenset[str]] = {
    "focused": frozenset(
        {
            "rlm_query",
            "browse",
            "reformulate",
            "critique_answer",
            "evaluate_results",
        }
    ),
    "standard": frozenset(
        {
            "rlm_query",
        }
    ),
    "full": frozenset(),
}


def compute_tool_tier(classification: dict[str, Any] | None) -> str:
    """Determine tool tier from classification result.

    Args:
        classification: Output of _extract_classification(), or None.

    Returns:
        "focused", "standard", or "full".
    """
    if classification is None:
        return "full"

    confidence = classification.get("confidence", "LOW")
    category = classification.get("category", "")
    also_category = classification.get("also_category", "")

    # No category signal — can't gate
    if not category:
        return "full"

    # Cross-category ambiguity — need full tool set
    if also_category:
        return "full"

    if confidence == "HIGH":
        return "focused"
    if confidence == "MEDIUM":
        return "standard"
    return "full"


# All tools that can appear in the REPL namespace (used for "available" computation).
ALL_REPL_TOOLS: frozenset[str] = frozenset(
    {
        "research",
        "draft_answer",
        "check_progress",
        "search",
        "browse",
        "fiqh_lookup",
        "format_evidence",
        "evaluate_results",
        "reformulate",
        "critique_answer",
        "rlm_query",
    }
)

# Tier descriptions for prompt generation.
TIER_CONDITIONS: dict[str, str] = {
    "focused": "HIGH confidence, single category",
    "standard": "MEDIUM confidence",
    "full": "LOW confidence or cross-category",
}


def generate_availability_section() -> str:
    """Generate the Tool Availability prompt section from TIER_REMOVALS.

    Single source of truth — no hand-typed tool lists in prompt layers.
    Uses a table for scannability + a core-tools line for quick reference.
    """
    # Core tools = tools never removed in any tier
    all_removed = frozenset().union(*(TIER_REMOVALS.values()))
    core = sorted(ALL_REPL_TOOLS - all_removed)

    # Build table rows
    rows = []
    for tier in ("focused", "standard", "full"):
        removed = TIER_REMOVALS[tier]
        condition = TIER_CONDITIONS[tier]
        if not removed:
            removed_str = "—"
        else:
            removed_str = ", ".join(f"`{t}`" for t in sorted(removed))
        rows.append(f"| **{tier}** | {condition} | {removed_str} |")

    core_str = ", ".join(f"`{t}`" for t in core)

    return "\n".join(
        [
            "### Tool Availability",
            "",
            "After `research()`, tools are gated by classification confidence."
            " **Gating is permanent for the session.**",
            "",
            f"Core tools (always available): {core_str}",
            "",
            "| Tier | Condition | Removed |",
            "|------|-----------|---------|",
            *rows,
            "",
            "If a tool raises `NameError`, the gate removed it — work with what you have.",
        ]
    )


def apply_gate(namespace: dict[str, Any], tier: str) -> list[str]:
    """Remove tool bindings from namespace based on tier.

    Args:
        namespace: Mutable dict (e.g. REPL locals or combined globals).
        tier: One of "focused", "standard", "full".

    Returns:
        Sorted list of tool names that were actually removed.
    """
    to_remove = TIER_REMOVALS.get(tier, frozenset())
    removed = []
    for name in sorted(to_remove):
        if name in namespace:
            del namespace[name]
            removed.append(name)
    return removed
