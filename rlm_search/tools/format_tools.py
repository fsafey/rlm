"""Evidence formatting — pure functions, no ToolContext needed."""

from __future__ import annotations

from typing import Any

from rlm_search.prompt_constants import RATING_ORDER

# Rating display labels for evidence annotation
_RATING_LABELS: dict[str, str] = {
    "RELEVANT": "RELEVANT",
    "PARTIAL": "PARTIAL",
    "OFF-TOPIC": "OFF-TOPIC",
}


def _sort_by_rating(
    results: list[dict[str, Any]],
    ratings: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort results by rating tier (RELEVANT > PARTIAL > unrated), confidence, score."""

    def sort_key(r: dict[str, Any]) -> tuple[int, int, float]:
        rid = str(r.get("id", ""))
        rating_info = ratings.get(rid, {})
        tier = RATING_ORDER.get(rating_info.get("rating", "UNKNOWN"), 99)
        confidence = rating_info.get("confidence", 0)
        score = r.get("score", 0)
        return (tier, -confidence, -score)

    return sorted(results, key=sort_key)


def format_evidence(
    results: list | dict,
    max_per_source: int = 3,
    ratings: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Format search results as citation strings for synthesis.

    Accepts either a list of result dicts or a dict with a ``results`` key
    (i.e. the return value of ``search()`` can be passed directly).

    When ``ratings`` is provided (id -> {"rating": str, "confidence": int}),
    results are sorted by rating tier (RELEVANT first) and annotated with
    their rating label.

    Args:
        results: List of result dicts, or a dict with a ``results`` key.
        max_per_source: Max results to include per unique source ID.
        ratings: Optional rating data from EvidenceStore._ratings.

    Returns:
        List of formatted strings: ``[Source: <id>] Q: ... A: ...``
    """
    if isinstance(results, dict):
        results = results.get("results", [])

    if ratings:
        results = _sort_by_rating(list(results), ratings)

    seen: dict[str, int] = {}
    lines: list[str] = []
    for r in results[:50]:
        rid = r.get("id", "unknown")
        seen.setdefault(rid, 0)
        if seen[rid] >= max_per_source:
            continue
        seen[rid] += 1
        q = (r.get("question", "") or "")[:200]
        a = (r.get("answer", "") or "")[:1500]
        meta = r.get("metadata", {})
        topic = meta.get("primary_topic", "")
        category = meta.get("parent_category", "")
        tag = (
            f" | {category} > {topic}"
            if category and topic
            else (f" | {topic}" if topic else "")
        )

        # Annotate with rating when available
        rating_tag = ""
        if ratings:
            rid_str = str(rid)
            rating_info = ratings.get(rid_str, {})
            label = _RATING_LABELS.get(rating_info.get("rating", ""), "")
            if label:
                rating_tag = f" | {label}"

        lines.append(f"[Source: {rid}{tag}{rating_tag}] Q: {q} A: {a}")
    return lines


def build_must_cite_brief(
    results: list[dict[str, Any]],
    ratings: dict[str, dict[str, Any]],
    max_priority: int = 8,
    max_supporting: int = 5,
) -> str:
    """Build a must-cite brief from rating data — zero LLM cost.

    Groups sources into PRIORITY (RELEVANT) and SUPPORTING (PARTIAL),
    extracting the key topic from each for the synthesis prompt.

    Args:
        results: Search result dicts with id, question, score.
        ratings: Rating data from EvidenceStore._ratings.
        max_priority: Max RELEVANT sources to list.
        max_supporting: Max PARTIAL sources to list.

    Returns:
        Formatted brief string, or empty string if no rated sources.
    """
    priority: list[str] = []
    supporting: list[str] = []

    sorted_results = _sort_by_rating(list(results), ratings)

    for r in sorted_results:
        rid = str(r.get("id", ""))
        rating_info = ratings.get(rid, {})
        rating = rating_info.get("rating", "")
        q = (r.get("question", "") or "")[:120]

        if rating == "RELEVANT" and len(priority) < max_priority:
            priority.append(f"- [Source: {rid}]: {q}")
        elif rating == "PARTIAL" and len(supporting) < max_supporting:
            supporting.append(f"- [Source: {rid}]: {q}")

    if not priority and not supporting:
        return ""

    parts: list[str] = []
    if priority:
        parts.append(
            "PRIORITY SOURCES (RELEVANT — must cite if they address the question):\n"
            + "\n".join(priority)
        )
    if supporting:
        parts.append(
            "SUPPORTING SOURCES (PARTIAL — cite if relevant to specific aspects):\n"
            + "\n".join(supporting)
        )
    return "\n\n".join(parts) + "\n\n"
