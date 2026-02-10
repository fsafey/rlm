"""REPL setup code that injects search tools into the LocalREPL namespace."""

from __future__ import annotations


def build_search_setup_code(
    api_url: str,
    api_key: str = "",
    timeout: int = 30,
) -> str:
    """Return Python code string executed in LocalREPL via setup_code parameter.

    Defines search(), browse(), and a search_log list in the REPL namespace.

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
    "subtopics", "source_collection", "chapter", "heading", "section",
    "islamic_terms", "layers_executed",
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
    """Search the Islamic jurisprudence knowledge base.

    Args:
        query: Natural language search query.
        filters: Optional filter dict, e.g. {{"parent_code": "PT"}}.
        top_k: Number of results to return (default: 10).

    Returns:
        Dict with 'results' list, each containing 'id', 'score', 'question',
        'answer', 'metadata' (parent_code, cluster_label, etc.).
    """
    payload = {{"query": query, "top_k": top_k}}
    if filters:
        payload["filters"] = filters
    resp = _requests.post(f"{{_API_URL}}/search", json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("hits", [])
    results = [_normalize_hit(h) for h in hits]
    print(f"[REPL:search] query={{query!r}} top_k={{top_k}} results={{len(results)}}")
    search_log.append({{"type": "search", "query": query, "filters": filters, "top_k": top_k, "num_results": len(results)}})
    return {{"results": results, "total": data.get("total", len(results))}}


def browse(filters: dict | None = None, offset: int = 0, limit: int = 20) -> dict:
    """Browse documents by filter criteria without a search query.

    Args:
        filters: Filter dict, e.g. {{"parent_code": "PT"}} for Prayer/Tahara.
        offset: Pagination offset.
        limit: Number of documents to return.

    Returns:
        Dict with 'results' list of matching documents.
    """
    payload = {{"offset": offset, "limit": limit}}
    if filters:
        payload["filters"] = filters
    resp = _requests.post(f"{{_API_URL}}/browse", json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("hits", [])
    results = [_normalize_hit(h) for h in hits]
    print(f"[REPL:browse] filters={{filters}} offset={{offset}} results={{len(results)}}")
    search_log.append({{"type": "browse", "filters": filters, "offset": offset, "limit": limit, "num_results": len(results)}})
    return {{"results": results, "total": data.get("total", len(results)), "has_more": data.get("has_more", False)}}
'''
