"""Evidence formatting — pure functions, no ToolContext needed."""

from __future__ import annotations


def format_evidence(results: list | dict, max_per_source: int = 3) -> list[str]:
    """Format search results as citation strings for synthesis.

    Accepts either a list of result dicts or a dict with a ``results`` key
    (i.e. the return value of ``search()`` can be passed directly).

    Args:
        results: List of result dicts, or a dict with a ``results`` key.
        max_per_source: Max results to include per unique source ID.

    Returns:
        List of formatted strings: ``[Source: <id>] Q: ... A: ...``
    """
    if isinstance(results, dict):
        results = results.get("results", [])
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
        lines.append(f"[Source: {rid}] Q: {q} A: {a}")
    return lines
