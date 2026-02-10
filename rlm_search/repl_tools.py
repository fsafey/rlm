"""REPL setup code that injects search tools into the LocalREPL namespace."""

from __future__ import annotations

import json
from typing import Any


def build_search_setup_code(
    api_url: str,
    api_key: str = "",
    timeout: int = 30,
    kb_overview_data: dict[str, Any] | None = None,
) -> str:
    """Return Python code string executed in LocalREPL via setup_code parameter.

    Defines search(), browse(), kb_overview(), fiqh_lookup(), format_evidence(),
    and a search_log list in the REPL namespace.

    The Cascade API returns hits with flat fields (id, question, answer,
    parent_code, cluster_label, etc.). These functions normalize the response
    into a consistent {results: [...]} format with nested metadata for the LLM.
    """
    code = f'''
import requests as _requests
import json as _json

_API_URL = {api_url!r}
_API_KEY = {api_key!r}
_TIMEOUT = {timeout!r}
_HEADERS = {{"Content-Type": "application/json"}}
if _API_KEY:
    _HEADERS["x-api-key"] = _API_KEY

search_log = []

# Metadata fields to nest under 'metadata' key for cleaner LLM consumption
_META_FIELDS = {{
    "parent_code", "parent_category", "cluster_label", "primary_topic",
    "subtopics",
}}


def _normalize_hit(hit: dict) -> dict:
    """Normalize a Cascade API hit into {{id, score, question, answer, metadata}}."""
    result = {{
        "id": hit.get("id", ""),
        "score": hit.get("score", hit.get("relevance_score", 0.0)),
        "question": hit.get("question", ""),
        "answer": hit.get("answer", ""),
    }}
    metadata = {{}}
    for k, v in hit.items():
        if k in _META_FIELDS and v is not None:
            metadata[k] = v
    if metadata:
        result["metadata"] = metadata
    return result


def search(query: str, filters: dict | None = None, top_k: int = 10) -> dict:
    """Search the Islamic Q&A knowledge base (18,835 scholar-answered questions).

    The search engine automatically handles Arabic/English term bridging,
    so you can query in either language without manual translation.

    Args:
        query: Natural language search query.
        filters: Optional filter dict, e.g. {{"parent_code": "PT"}}.
        top_k: Number of results to return (default 10).

    Returns:
        Dict with 'results' list, each containing 'id', 'score', 'question',
        'answer', 'metadata' (parent_code, cluster_label, etc.).
    """
    payload = {{"query": query, "collection": "enriched_gemini", "top_k": top_k}}
    if filters:
        payload["filters"] = filters
    resp = _requests.post(f"{{_API_URL}}/search", json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("hits", [])
    results = [_normalize_hit(h) for h in hits]
    print(f"[search] query={{query!r}} top_k={{top_k}} results={{len(results)}}")
    search_log.append({{"type": "search", "query": query, "filters": filters, "top_k": top_k, "num_results": len(results)}})
    return {{"results": results, "total": data.get("total", len(results))}}


def browse(filters=None, offset=0, limit=20, sort_by=None, group_by=None, group_limit=4):
    """Browse the knowledge base by filter — no search query needed.

    Use for: exploring categories, discovering clusters, paginated access.

    Args:
        filters: e.g. {{"parent_code": "PT", "cluster_label": "Ghusl"}}.
        offset: Pagination offset (default 0).
        limit: Results per page, 1-100 (default 20).
        sort_by: Sort field, e.g. "quality_score", "id".
        group_by: Group by field, e.g. "cluster_label" for clustered view.
        group_limit: Max hits per group (default 4).

    Returns:
        Dict with results, total, has_more, facets, grouped_results.
    """
    payload = {{"collection": "enriched_gemini", "include_facets": True}}
    if filters:
        payload["filters"] = filters
    payload["offset"] = offset
    payload["limit"] = limit
    if sort_by:
        payload["sort_by"] = sort_by
    if group_by:
        payload["group_by"] = group_by
        payload["group_limit"] = group_limit
    resp = _requests.post(
        f"{{_API_URL}}/browse", json=payload, headers=_HEADERS, timeout=_TIMEOUT
    )
    resp.raise_for_status()
    data = resp.json()
    results = [_normalize_hit(h) for h in data.get("hits", [])]
    raw_grouped = data.get("grouped_results", {{}})
    # Cascade returns {{"clusters": [...], ...}} — normalize to list
    group_list = (
        raw_grouped.get("clusters", []) if isinstance(raw_grouped, dict) else raw_grouped
    )
    for group in group_list:
        group["hits"] = [_normalize_hit(h) for h in group.get("hits", [])]
    log_entry = {{"type": "browse", "filters": filters, "offset": offset, "limit": limit}}
    if group_by:
        log_entry["group_by"] = group_by
    search_log.append(log_entry)
    print(f"[browse] filters={{filters}} results={{len(results)}} total={{data.get('total', 0)}}")
    return {{
        "results": results,
        "total": data.get("total", 0),
        "has_more": data.get("has_more", False),
        "facets": data.get("facets", {{}}),
        "grouped_results": group_list,
    }}


def format_evidence(results, max_per_source: int = 3) -> list[str]:
    """Format search results as citation strings for synthesis.

    Accepts either a list of result dicts or a dict with a 'results' key
    (i.e. the return value of search() can be passed directly).

    Args:
        results: List of result dicts, or a dict with a 'results' key.
        max_per_source: Max results to include per unique source ID.

    Returns:
        List of formatted strings: "[Source: <id>] Q: ... A: ..."
    """
    if isinstance(results, dict):
        results = results.get("results", [])
    seen = {{}}
    lines = []
    for r in results[:50]:
        rid = r.get("id", "unknown")
        seen.setdefault(rid, 0)
        if seen[rid] >= max_per_source:
            continue
        seen[rid] += 1
        q = (r.get("question", "") or "")[:200]
        a = (r.get("answer", "") or "")[:1500]
        lines.append(f"[Source: {{rid}}] Q: {{q}} A: {{a}}")
    return lines


def fiqh_lookup(query: str) -> dict:
    """Look up Islamic jurisprudence terminology for use in your answer.

    Consults a dictionary of 453 canonical terms with 3,783 variants.
    Supports English, Arabic, and transliterated input.

    Use this to find the proper Arabic/English term pairs so your written
    answer uses correct scholarly terminology. You do NOT need to use
    these terms in search queries -- the search engine bridges terms
    automatically.

    Args:
        query: Term or phrase to look up (any language).

    Returns:
        Dict with 'bridges' (matched terms with canonical form, arabic,
        english equivalents, expansions) and 'related' (morphologically
        related terms).
    """
    resp = _requests.get(
        f"{{_API_URL}}/bridge",
        params={{"q": query}},
        headers=_HEADERS,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    bridges = data.get("bridges", [])
    related = data.get("related", [])
    print(f"[fiqh_lookup] query={{query!r}} bridges={{len(bridges)}} related={{len(related)}}")
    return {{"bridges": bridges, "related": related}}
'''

    # Append kb_overview data and function outside the f-string to avoid
    # nested brace escaping issues with the JSON blob
    if kb_overview_data is not None:
        kb_json_str = json.dumps(kb_overview_data)
        code += f"\n_KB_OVERVIEW = _json.loads({kb_json_str!r})\n"
    else:
        code += "\n_KB_OVERVIEW = None\n"

    code += '''

def kb_overview():
    """Get a pre-computed overview of the knowledge base taxonomy.

    Returns a dict with collection info, categories (with clusters and
    sample questions), and global facets. Use this to orient before searching.

    Returns:
        Dict with taxonomy overview, or None if unavailable.
    """
    if _KB_OVERVIEW is None:
        print("WARNING: Knowledge base overview unavailable — use search() directly.")
        return None
    ov = _KB_OVERVIEW
    total = ov.get("total_documents", 0)
    print(f"=== Knowledge Base: {ov.get(\'collection\', \'?\')} ({total:,} documents) ===\\n")
    for code, cat in ov.get("categories", {}).items():
        name = cat.get("name", code)
        count = cat.get("document_count", 0)
        clusters = cat.get("clusters", {})
        print(f"{code} — {name} [{count:,} docs]")
        shown = 0
        for label, sample_q in clusters.items():
            if shown >= 5:
                remaining = len(clusters) - shown
                if remaining > 0:
                    print(f"  ... and {remaining} more clusters")
                break
            if sample_q:
                q_short = sample_q[:80] + "..." if len(sample_q) > 80 else sample_q
                print(f"  · {label} — \\"{q_short}\\"")
            else:
                print(f"  · {label}")
            shown += 1
        print()
    print("Filter keys: parent_code, cluster_label, subtopics, primary_topic")
    print("Tip: Use cluster_label for precise targeting after identifying relevant clusters")
    return ov
'''

    return code
