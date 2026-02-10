"""REPL setup code that injects search tools into the LocalREPL namespace."""

from __future__ import annotations


def build_search_setup_code(
    api_url: str,
    api_key: str = "",
    timeout: int = 30,
) -> str:
    """Return Python code string executed in LocalREPL via setup_code parameter.

    Defines search(), fiqh_lookup(), format_evidence(), and a search_log list
    in the REPL namespace.

    The Cascade API returns hits with flat fields (id, question, answer,
    parent_code, cluster_label, etc.). These functions normalize the response
    into a consistent {results: [...]} format with nested metadata for the LLM.
    """
    return f'''
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


def format_evidence(results: list[dict], max_per_source: int = 3) -> list[str]:
    """Format search results as citation strings for synthesis.

    Args:
        results: List of result dicts from search().
        max_per_source: Max results to include per unique source ID.

    Returns:
        List of formatted strings: "[Source: <id>] Q: ... A: ..."
    """
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
