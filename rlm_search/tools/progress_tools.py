"""Progress advisor: confidence scoring, strategy suggestions, audit trail."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def _compute_confidence(
    relevant: int,
    partial: int,
    top_score: float,
    has_draft: bool,
    categories_explored: set,
) -> int:
    """Numeric confidence score (0-100) from evidence signals."""
    evidence = min(relevant / 3, 1.0) * 35
    # Cascade scores > 0.5 already indicate strong semantic match; saturate early
    quality = min(top_score / 0.5, 1.0) * 25
    breadth = min(partial / 2, 1.0) * 10
    diversity = min(len(categories_explored) / 2, 1.0) * 10
    draft = 20 if has_draft else 0
    return min(int(evidence + quality + breadth + diversity + draft), 100)


def _suggest_strategy(ctx: ToolContext, categories_explored: set) -> str:
    """Taxonomy-aware next-action suggestion with copy-paste-ready code."""
    kb = ctx.kb_overview_data
    if not kb:
        return "Try broader search terms or different filters."

    all_categories = kb.get("categories", {})
    unexplored = {
        code: cat
        for code, cat in all_categories.items()
        if code not in categories_explored and cat.get("document_count", 0) > 50
    }

    if unexplored:
        best_code, best_cat = max(unexplored.items(), key=lambda x: x[1].get("document_count", 0))
        clusters = best_cat.get("facets", {}).get("clusters", [])
        top_cluster = clusters[0]["value"] if clusters else None
        suggestion = f"Unexplored: {best_cat['name']} ({best_cat['document_count']} docs)."
        if top_cluster:
            suggestion += (
                f" Try: research(query, "
                f'filters={{"parent_code": "{best_code}", '
                f'"cluster_label": "{top_cluster}"}})'
            )
        return suggestion

    # All categories explored — suggest cluster-level exploration
    used_clusters = {
        e.get("filters", {}).get("cluster_label") for e in ctx.search_log if e.get("filters")
    } - {None}

    for code, cat in all_categories.items():
        clusters = cat.get("facets", {}).get("clusters", [])
        for cluster in clusters[:5]:
            if cluster["value"] not in used_clusters and cluster["count"] > 20:
                return (
                    f'Try cluster "{cluster["value"]}" in {cat["name"]}'
                    f" ({cluster['count']} docs): "
                    f"research(query, "
                    f'filters={{"parent_code": "{code}", '
                    f'"cluster_label": "{cluster["value"]}"}})'
                )

    return "All major categories and clusters explored. Draft with current evidence."


def _format_audit_trail(ctx: ToolContext) -> str:
    """Structured summary of searches tried so far."""
    searches = [e for e in ctx.search_log if e["type"] in ("search", "search_multi")]
    if not searches:
        return "  No searches run yet."

    lines = []
    for i, s in enumerate(searches, 1):
        filters_str = ""
        if s.get("filters"):
            parts = [f"{k}={v}" for k, v in s["filters"].items()]
            filters_str = f" [{', '.join(parts)}]"
        lines.append(f'  {i}. "{s["query"]}"{filters_str} \u2192 {s["num_results"]} results')

    queries = [s["query"] for s in searches]
    unique = len(set(queries))
    lines.append(f"  Diversity: {unique}/{len(queries)} unique queries")

    return "\n".join(lines)


def check_progress(ctx: ToolContext) -> dict:
    """Assess search progress: signals, confidence, strategy, audit trail.

    Returns a dict consumed by the LM and the frontend confidence ring.
    """
    with tool_call_tracker(
        ctx,
        "check_progress",
        {},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        # -- Signal computation --
        n_searches = sum(1 for e in ctx.search_log if e["type"] in ("search", "search_multi"))
        n_sources = len(ctx.source_registry)

        # Relevant/partial counts from the last evaluate_results tool_call
        relevant_count = 0
        partial_count = 0
        for call in reversed(ctx.tool_calls):
            if call["tool"] == "evaluate_results":
                rs = call.get("result_summary", {})
                relevant_count = rs.get("relevant", 0)
                partial_count = rs.get("partial", 0)
                break

        top_score = max((r.get("score", 0) for r in ctx.source_registry.values()), default=0.0)

        # Query diversity
        queries = [e["query"] for e in ctx.search_log if e["type"] in ("search", "search_multi")]
        diversity = len(set(queries)) / len(queries) if queries else 0.0

        has_draft = any(c["tool"] == "draft_answer" for c in ctx.tool_calls)

        categories_explored = {
            e.get("filters", {}).get("parent_code")
            for e in ctx.search_log
            if e.get("filters") and e["filters"].get("parent_code")
        }

        # -- Confidence --
        confidence = _compute_confidence(
            relevant_count, partial_count, top_score, has_draft, categories_explored
        )

        # -- Phase + guidance --
        if has_draft:
            phase = "finalize"
            guidance = "Draft complete. Emit FINAL_VAR."
        elif confidence >= 60:
            phase = "ready"
            guidance = f"Sufficient evidence (confidence {confidence}%). Proceed to draft_answer()."
        elif n_searches >= 6 and relevant_count < 2:
            phase = "stalled"
            strategy = _suggest_strategy(ctx, categories_explored)
            guidance = f"6+ searches with <2 relevant. {strategy}"
        elif diversity < 0.5 and n_searches >= 3:
            phase = "repeating"
            strategy = _suggest_strategy(ctx, categories_explored)
            guidance = f"Low query diversity. {strategy}"
        else:
            phase = "continue"
            strategy = _suggest_strategy(ctx, categories_explored)
            guidance = f"Confidence at {confidence}%. {strategy}"

        # -- Audit trail --
        audit = _format_audit_trail(ctx)

        # -- Stdout (what the LM sees) --
        print(f"[check_progress] {phase} \u2014 {guidance}")
        print(
            f"  confidence={confidence}% | searches={n_searches} | "
            f"sources={n_sources} | relevant={relevant_count} | "
            f"partial={partial_count} | top_score={top_score:.2f}"
        )
        print(f"  Searches tried:\n{audit}")

        tc.set_summary({
            "phase": phase,
            "confidence": confidence,
            "relevant": relevant_count,
            "searches": n_searches,
            "guidance": guidance,
            "partial": partial_count,
            "top_score": round(top_score, 3),
            "categories_explored": sorted(categories_explored),
        })

        return {
            "phase": phase,
            "confidence": confidence,
            "guidance": guidance,
            "searches_run": n_searches,
            "unique_sources": n_sources,
            "relevant": relevant_count,
            "partial": partial_count,
            "top_score": round(top_score, 3),
            "query_diversity": round(diversity, 2),
            "categories_explored": sorted(categories_explored),
        }
