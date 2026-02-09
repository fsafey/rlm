"""REPL setup code that injects search tools into the LocalREPL namespace."""

from __future__ import annotations


def build_search_setup_code(
    api_url: str,
    api_key: str = "",
    timeout: int = 30,
) -> str:
    """Return Python code string executed in LocalREPL via setup_code parameter.

    Defines search(), browse(), and a search_log list in the REPL namespace.
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


def search(query: str, collection: str = "enriched_gemini", filters: dict | None = None, top_k: int = 10) -> dict:
    """Search the Islamic jurisprudence knowledge base.

    Args:
        query: Natural language search query.
        collection: Collection to search (default: enriched_gemini).
        filters: Optional Qdrant filter dict, e.g. {{"parent_code": "PT"}}.
        top_k: Number of results to return (default: 10).

    Returns:
        Dict with 'results' list, each containing 'id', 'score', 'question',
        'answer', 'metadata' (parent_code, sub_code, source, etc.).
    """
    payload = {{"query": query, "collection": collection, "top_k": top_k}}
    if filters:
        payload["filters"] = filters
    resp = _requests.post(f"{{_API_URL}}/search", json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    search_log.append({{"type": "search", "query": query, "filters": filters, "top_k": top_k, "num_results": len(data.get("results", []))}})
    return data


def browse(collection: str = "enriched_gemini", filters: dict | None = None, offset: int = 0, limit: int = 20) -> dict:
    """Browse documents by filter criteria without a search query.

    Args:
        collection: Collection to browse (default: enriched_gemini).
        filters: Qdrant filter dict, e.g. {{"parent_code": "PT"}} for Prayer/Tahara.
        offset: Pagination offset.
        limit: Number of documents to return.

    Returns:
        Dict with 'results' list of matching documents.
    """
    payload = {{"collection": collection, "offset": offset, "limit": limit}}
    if filters:
        payload["filters"] = filters
    resp = _requests.post(f"{{_API_URL}}/browse", json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    search_log.append({{"type": "browse", "filters": filters, "offset": offset, "limit": limit, "num_results": len(data.get("results", []))}})
    return data
'''
