"""Build a knowledge base overview at startup by querying Cascade API facets."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

_log = logging.getLogger("rlm_search")

CATEGORIES = {
    "PT": "Prayer & Tahara (Purification)",
    "WP": "Worship Practices",
    "MF": "Marriage & Family",
    "FN": "Finance & Transactions",
    "BE": "Beliefs & Ethics",
    "OT": "Other Topics",
}

COLLECTION = "enriched_gemini"


async def build_kb_overview(
    api_url: str,
    api_key: str = "",
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Query Cascade /browse to build a taxonomy overview of the knowledge base.

    Makes 7 concurrent API calls:
    - 1 global facets call (total doc count + facet distribution)
    - 6 per-category calls (clusters + subtopic facets per category)

    Returns None if the API is unreachable.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            global_coro = client.post(
                f"{api_url}/browse",
                json={
                    "collection": COLLECTION,
                    "include_facets": True,
                    "limit": 1,
                },
            )

            category_coros = {
                code: client.post(
                    f"{api_url}/browse",
                    json={
                        "collection": COLLECTION,
                        "filters": {"parent_code": code},
                        "group_by": "cluster_label",
                        "group_limit": 1,
                        "include_facets": True,
                    },
                )
                for code in CATEGORIES
            }

            # 7 concurrent calls
            codes = list(CATEGORIES.keys())
            all_coros = [global_coro] + [category_coros[c] for c in codes]
            responses = await asyncio.gather(*all_coros, return_exceptions=True)

    except (httpx.HTTPError, httpx.ConnectError, OSError) as e:
        _log.warning("KB overview build failed (connection): %s", e)
        return None

    # Process global response
    global_resp = responses[0]
    if isinstance(global_resp, BaseException):
        _log.warning("Global facets call failed: %s", global_resp)
        return None

    global_data = global_resp.json()
    total_documents = global_data.get("total", 0)
    global_facets = global_data.get("facets", {})

    # Process per-category responses
    categories: dict[str, Any] = {}
    for i, code in enumerate(codes):
        resp = responses[i + 1]
        if isinstance(resp, BaseException):
            _log.warning("Category %s call failed: %s", code, resp)
            categories[code] = {
                "name": CATEGORIES[code],
                "document_count": 0,
                "facets": {},
                "clusters": {},
            }
            continue

        data = resp.json()
        clusters: dict[str, Any] = {}
        raw_groups = data.get("grouped_results", {})
        # Cascade returns {"clusters": [{"label": ..., "hits": [...]}, ...]}
        group_list = raw_groups.get("clusters", []) if isinstance(raw_groups, dict) else raw_groups
        for group in group_list:
            label = group.get("label", group.get("group_key", "Unknown"))
            hits = group.get("hits", [])
            sample_question = ""
            if hits:
                sample_question = hits[0].get("question", "")
            clusters[label] = sample_question

        categories[code] = {
            "name": CATEGORIES[code],
            "document_count": data.get("total", 0),
            "facets": data.get("facets", {}),
            "clusters": clusters,
        }

    return {
        "collection": COLLECTION,
        "total_documents": total_documents,
        "categories": categories,
        "global_facets": global_facets,
    }
