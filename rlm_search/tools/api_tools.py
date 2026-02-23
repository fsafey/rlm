"""API tools: search(), browse(), fiqh_lookup() — call the Cascade API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from rlm_search.tools.constants import MAX_QUERY_LEN
from rlm_search.tools.normalize import normalize_hit
from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def _truncate_hits(results: list[dict], max_hits: int = 10) -> list[dict]:
    """Truncate hits for SSE payload — question[100], answer[200], keep score/id/collection/topic."""
    out = []
    for h in results[:max_hits]:
        entry: dict = {
            "id": h.get("id", ""),
            "score": round(h.get("score", 0.0), 3),
            "question": h.get("question", "")[:100],
            "answer": h.get("answer", "")[:200],
        }
        meta = h.get("metadata", {})
        if meta.get("primary_topic"):
            entry["topic"] = meta["primary_topic"]
        if h.get("collection"):
            entry["collection"] = h["collection"]
        out.append(entry)
    return out


def search(
    ctx: ToolContext,
    query: str,
    filters: dict | None = None,
    top_k: int = 10,
) -> dict:
    """Search the Islamic Q&A knowledge base (18,835 scholar-answered questions).

    The search engine automatically handles Arabic/English term bridging,
    so you can query in either language without manual translation.

    Args:
        ctx: Per-session tool context.
        query: Natural language search query.
        filters: Optional filter dict, e.g. ``{"parent_code": "PT"}``.
        top_k: Number of results to return (default 10).

    Returns:
        Dict with ``results`` list, each containing ``id``, ``score``, ``question``,
        ``answer``, ``metadata`` (parent_code, cluster_label, etc.).
    """
    if len(query) > MAX_QUERY_LEN:
        print(
            f"[search] WARNING: query too long ({len(query)} chars), truncating to {MAX_QUERY_LEN}"
        )
        query = query[:MAX_QUERY_LEN]
    with tool_call_tracker(
        ctx, "search", {"query": query, "top_k": top_k}, parent_idx=ctx.current_parent_idx
    ) as tc:
        payload: dict = {"query": query, "collection": "enriched_gemini", "top_k": top_k}
        if filters:
            payload["filters"] = filters
        resp = requests.post(
            f"{ctx.api_url}/search", json=payload, headers=ctx.headers, timeout=ctx.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        results = [normalize_hit(h, ctx.source_registry) for h in hits]
        print(f"[search] query={query!r} top_k={top_k} results={len(results)}")
        ctx.search_log.append(
            {
                "type": "search",
                "query": query,
                "filters": filters,
                "top_k": top_k,
                "num_results": len(results),
            }
        )
        tc.set_summary({
            "num_results": len(results),
            "total": data.get("total", len(results)),
            "query": query,
            "hits": _truncate_hits(results),
        })
        return {"results": results, "total": data.get("total", len(results))}


def browse(
    ctx: ToolContext,
    filters: dict | None = None,
    offset: int = 0,
    limit: int = 20,
    sort_by: str | None = None,
    group_by: str | None = None,
    group_limit: int = 4,
) -> dict:
    """Browse the knowledge base by filter — no search query needed.

    Use for: exploring categories, discovering clusters, paginated access.

    Args:
        ctx: Per-session tool context.
        filters: e.g. ``{"parent_code": "PT", "cluster_label": "Ghusl"}``.
        offset: Pagination offset (default 0).
        limit: Results per page, 1-100 (default 20).
        sort_by: Sort field, e.g. ``"quality_score"``, ``"id"``.
        group_by: Group by field, e.g. ``"cluster_label"`` for clustered view.
        group_limit: Max hits per group (default 4).

    Returns:
        Dict with results, total, has_more, facets, grouped_results.
    """
    with tool_call_tracker(
        ctx,
        "browse",
        {"filters": filters, "offset": offset, "limit": limit},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        payload: dict = {"collection": "enriched_gemini", "include_facets": True}
        if filters:
            payload["filters"] = filters
        payload["offset"] = offset
        payload["limit"] = limit
        if sort_by:
            payload["sort_by"] = sort_by
        if group_by:
            payload["group_by"] = group_by
            payload["group_limit"] = group_limit
        resp = requests.post(
            f"{ctx.api_url}/browse", json=payload, headers=ctx.headers, timeout=ctx.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        results = [normalize_hit(h, ctx.source_registry) for h in data.get("hits", [])]
        raw_grouped = data.get("grouped_results", {})
        # Cascade returns {"clusters": [...], ...} — normalize to list
        group_list = (
            raw_grouped.get("clusters", []) if isinstance(raw_grouped, dict) else raw_grouped
        )
        for group in group_list:
            group["hits"] = [normalize_hit(h, ctx.source_registry) for h in group.get("hits", [])]
        log_entry: dict = {"type": "browse", "filters": filters, "offset": offset, "limit": limit}
        if group_by:
            log_entry["group_by"] = group_by
        ctx.search_log.append(log_entry)
        print(f"[browse] filters={filters} results={len(results)} total={data.get('total', 0)}")
        tc.set_summary({
            "num_results": len(results),
            "total": data.get("total", 0),
            "hits": _truncate_hits(results),
        })
        return {
            "results": results,
            "total": data.get("total", 0),
            "has_more": data.get("has_more", False),
            "facets": data.get("facets", {}),
            "grouped_results": group_list,
        }


def search_multi(
    ctx: ToolContext,
    query: str,
    collections: list[str] | None = None,
    top_k_per_collection: int = 50,
    final_top_k: int = 10,
    # Deprecated — use final_top_k instead
    filters: dict | None = None,
    top_k: int | None = None,
) -> dict:
    """Search across multiple collections with server-side RRF + L5 reranking.

    Strictly better than single-collection search() for queries that span
    both Risala and enriched corpora.

    Args:
        ctx: Per-session tool context.
        query: Natural language search query.
        collections: Collections to search (default: ["enriched_gemini", "risala"]).
        top_k_per_collection: Candidates per collection before merge (default 50).
        final_top_k: Final results after reranking (default 10).
        filters: Optional filter dict, e.g. ``{"parent_code": "PT"}``.
        top_k: Deprecated — use final_top_k instead.

    Returns:
        Dict with ``results`` list (normalized, deduplicated, reranked by server),
        ``total``, and ``collections_searched``.
    """
    # Backward compat: map deprecated top_k to final_top_k
    if top_k is not None and final_top_k == 10:
        final_top_k = top_k
    if collections is None:
        collections = ["enriched_gemini", "risala"]
    if len(query) > MAX_QUERY_LEN:
        print(
            f"[search_multi] WARNING: query too long ({len(query)} chars), "
            f"truncating to {MAX_QUERY_LEN}"
        )
        query = query[:MAX_QUERY_LEN]
    with tool_call_tracker(
        ctx,
        "search_multi",
        {"query": query, "collections": collections, "final_top_k": final_top_k},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        payload: dict = {
            "query": query,
            "collections": collections,
            "top_k_per_collection": top_k_per_collection,
            "top_k": final_top_k,
        }
        if filters:
            payload["filters"] = filters
        resp = requests.post(
            f"{ctx.api_url}/search/multi",
            json=payload,
            headers=ctx.headers,
            timeout=ctx.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        results = [normalize_hit(h, ctx.source_registry) for h in hits]
        print(
            f"[search_multi] query={query!r} collections={collections} "
            f"final_top_k={final_top_k} results={len(results)}"
        )
        ctx.search_log.append(
            {
                "type": "search_multi",
                "query": query,
                "collections": collections,
                "top_k_per_collection": top_k_per_collection,
                "final_top_k": final_top_k,
                "num_results": len(results),
            }
        )
        tc.set_summary({
            "num_results": len(results),
            "total": data.get("total", len(results)),
            "query": query,
            "collections": collections,
            "hits": _truncate_hits(results),
        })
        return {
            "results": results,
            "total": data.get("total", len(results)),
            "collections_searched": collections,
        }


def fiqh_lookup(ctx: ToolContext, query: str) -> dict:
    """Look up Islamic jurisprudence terminology for use in your answer.

    Consults a dictionary of 453 canonical terms with 3,783 variants.
    Supports English, Arabic, and transliterated input.

    Args:
        ctx: Per-session tool context.
        query: Term or phrase to look up (any language).

    Returns:
        Dict with ``bridges`` (matched terms with canonical form, arabic,
        english equivalents, expansions) and ``related`` (morphologically
        related terms).
    """
    with tool_call_tracker(
        ctx, "fiqh_lookup", {"query": query}, parent_idx=ctx.current_parent_idx
    ) as tc:
        resp = requests.get(
            f"{ctx.api_url}/bridge",
            params={"q": query},
            headers=ctx.headers,
            timeout=ctx.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        bridges = data.get("bridges", [])
        related = data.get("related", [])
        print(f"[fiqh_lookup] query={query!r} bridges={len(bridges)} related={len(related)}")
        tc.set_summary({
            "num_bridges": len(bridges),
            "num_related": len(related),
            "bridges": [
                {"term": b.get("canonical", b.get("term", "")), "translation": b.get("english", "")}
                for b in bridges[:10]
            ],
            "related": [{"term": r.get("term", "")} for r in related[:10]],
        })
        return {"bridges": bridges, "related": related}
