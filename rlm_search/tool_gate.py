"""Tool gating by classification confidence — controls REPL tool visibility."""

from __future__ import annotations

from typing import Any

# Tools removed per tier. Keyed by tier name.
# focused: HIGH confidence, single category — only core search + draft
# standard: MEDIUM confidence — drop rlm_query (expensive delegation)
# full: LOW or cross-category — all tools available
TIER_REMOVALS: dict[str, frozenset[str]] = {
    "focused": frozenset({
        "rlm_query",
        "browse",
        "reformulate",
        "critique_answer",
        "evaluate_results",
    }),
    "standard": frozenset({
        "rlm_query",
    }),
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
