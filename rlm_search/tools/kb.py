"""Knowledge base overview tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def kb_overview(ctx: ToolContext) -> dict | None:
    """Print and return a knowledge base taxonomy overview.

    PRINTS a formatted summary: categories, top clusters (with doc counts
    and sample questions), and top subtopic filter values.

    Args:
        ctx: Per-session tool context.

    Returns:
        None if unavailable, otherwise a dict with collection info and categories.
    """
    if ctx.kb_overview_data is None:
        print("WARNING: Knowledge base overview unavailable — use search() directly.")
        return None
    with tool_call_tracker(
        ctx, "kb_overview", {"overview": "kb"}, parent_idx=ctx.current_parent_idx
    ) as tc:
        ov = ctx.kb_overview_data
        collection = ov.get("collection", "?")
        total = ov.get("total_documents", 0)
        print(f"=== Knowledge Base: {collection} ({total:,} documents) ===\n")
        categories = []
        for code, cat in ov.get("categories", {}).items():
            name = cat.get("name", code)
            count = cat.get("document_count", 0)
            clusters = cat.get("clusters", {})
            facets = cat.get("facets", {})
            # Cluster doc counts from facets (capped at top 20 by API)
            cluster_counts = {c["value"]: c["count"] for c in facets.get("clusters", [])}
            # Subtopic tags from facets
            subtopic_facets = facets.get("subtopics", [])
            print(f"{code} — {name} [{count:,} docs]")
            # Show top 8 clusters with doc counts
            shown = 0
            for label, sample_q in clusters.items():
                if shown >= 8:
                    remaining = len(clusters) - shown
                    if remaining > 0:
                        print(f"  ... and {remaining} more clusters")
                    break
                doc_n = cluster_counts.get(label, "")
                count_str = f" ({doc_n})" if doc_n else ""
                if sample_q:
                    q_short = sample_q[:80] + "..." if len(sample_q) > 80 else sample_q
                    print(f'  · {label}{count_str} — "{q_short}"')
                else:
                    print(f"  · {label}{count_str}")
                shown += 1
            # Show top subtopic tags
            if subtopic_facets:
                top_subs = [f"{s['value']} ({s['count']})" for s in subtopic_facets[:8]]
                print(f"  Subtopics: {', '.join(top_subs)}")
            print()
            top_subtopics = [s["value"] for s in subtopic_facets[:15]]
            categories.append(
                {
                    "code": code,
                    "name": name,
                    "document_count": count,
                    "cluster_labels": list(clusters.keys()),
                    "top_subtopics": top_subtopics,
                }
            )
        print("Filter keys: parent_code, cluster_label, subtopics, primary_topic")
        print("Tip: Use cluster_label or subtopics for precise targeting")
        tc.set_summary({"num_categories": len(categories), "total_documents": total})
        return {"collection": collection, "total_documents": total, "categories": categories}
