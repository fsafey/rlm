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
    search_log list, and sub-agent tools (evaluate_results, reformulate,
    critique_answer, classify_question) in the REPL namespace.

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
source_registry = {{}}

import time as _time
import contextlib as _contextlib

tool_calls = []
_current_parent_idx = None

def _ToolCallTracker(tool_name, args, parent_idx=None):
    """Create a context manager that records a tool call entry in tool_calls.

    Yields a namespace dict with 'entry', 'idx', and 'set_summary' callable.
    """
    entry = {{
        "tool": tool_name,
        "args": args,
        "result_summary": {{}},
        "duration_ms": 0,
        "children": [],
        "error": None,
    }}
    tool_calls.append(entry)
    idx = len(tool_calls) - 1
    if parent_idx is not None:
        tool_calls[parent_idx]["children"].append(idx)

    def set_summary(summary):
        entry["result_summary"] = summary

    # Simple namespace object using a dict with attribute access
    tc = type("_TC", (), {{"entry": entry, "idx": idx, "set_summary": staticmethod(set_summary)}})()

    start = _time.time()
    try:
        yield tc
    except BaseException as exc:
        entry["duration_ms"] = int((_time.time() - start) * 1000)
        entry["error"] = str(exc)
        raise
    else:
        entry["duration_ms"] = int((_time.time() - start) * 1000)

_ToolCallTracker = _contextlib.contextmanager(_ToolCallTracker)

# Metadata fields to nest under 'metadata' key for cleaner LLM consumption
_META_FIELDS = {{
    "parent_code", "parent_category", "cluster_label", "primary_topic",
    "subtopics",
}}


def _normalize_hit(hit: dict) -> dict:
    """Normalize a Cascade API hit into {{id, score, question, answer, metadata}}."""
    result = {{
        "id": str(hit.get("id", "")),
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
    source_registry[result["id"]] = result
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
    _MAX_QUERY_LEN = 500
    if len(query) > _MAX_QUERY_LEN:
        print(f"[search] WARNING: query too long ({{len(query)}} chars), truncating to {{_MAX_QUERY_LEN}}")
        query = query[:_MAX_QUERY_LEN]
    with _ToolCallTracker("search", {{"query": query, "top_k": top_k}}, parent_idx=_current_parent_idx) as tc:
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
        tc.set_summary({{"num_results": len(results), "total": data.get("total", len(results)), "query": query}})
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
    with _ToolCallTracker("browse", {{"filters": filters, "offset": offset, "limit": limit}}, parent_idx=_current_parent_idx) as tc:
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
        tc.set_summary({{"num_results": len(results), "total": data.get("total", 0)}})
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
    with _ToolCallTracker("fiqh_lookup", {{"query": query}}, parent_idx=_current_parent_idx) as tc:
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
        tc.set_summary({{"num_bridges": len(bridges), "num_related": len(related)}})
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
    """Print and return a knowledge base taxonomy overview.

    PRINTS a formatted summary: categories, top clusters (with doc counts
    and sample questions), and top subtopic filter values.

    Returns:
        None if unavailable, otherwise a dict:
        {
            "collection": "enriched_gemini",
            "total_documents": 18835,
            "categories": [
                {
                    "code": "PT",
                    "name": "Prayer & Tahara (Purification)",
                    "document_count": 2836,
                    "cluster_labels": ["Ghusl Procedure and Validity", ...],
                    "top_subtopics": ["wudu validity", "ghusl janaba", ...],
                },
                ...
            ],
        }
    """
    if _KB_OVERVIEW is None:
        print("WARNING: Knowledge base overview unavailable — use search() directly.")
        return None
    with _ToolCallTracker("kb_overview", {"overview": "kb"}, parent_idx=_current_parent_idx) as tc:
        ov = _KB_OVERVIEW
        collection = ov.get("collection", "?")
        total = ov.get("total_documents", 0)
        print(f"=== Knowledge Base: {collection} ({total:,} documents) ===\\n")
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
                    print(f"  · {label}{count_str} — \\"{q_short}\\"")
                else:
                    print(f"  · {label}{count_str}")
                shown += 1
            # Show top subtopic tags
            if subtopic_facets:
                top_subs = [f"{s['value']} ({s['count']})" for s in subtopic_facets[:8]]
                print(f"  Subtopics: {', '.join(top_subs)}")
            print()
            top_subtopics = [s["value"] for s in subtopic_facets[:15]]
            categories.append({
                "code": code,
                "name": name,
                "document_count": count,
                "cluster_labels": list(clusters.keys()),
                "top_subtopics": top_subtopics,
            })
        print("Filter keys: parent_code, cluster_label, subtopics, primary_topic")
        print("Tip: Use cluster_label or subtopics for precise targeting")
        tc.set_summary({"num_categories": len(categories), "total_documents": total})
        return {"collection": collection, "total_documents": total, "categories": categories}
'''

    # Sub-agent tools: wrap llm_query with role-specific prompts.
    # These are defined in a plain triple-quoted string (not f-string).
    # In the exec'd code: \\n → \n (newline in string literals),
    # \\" → \" (escaped double quote).
    code += '''

def evaluate_results(question, results, top_n=5, model=None):
    """Sub-agent: evaluate search result relevance with per-result confidence scores.

    Call after search() to check whether results match the question
    before spending a turn examining them in detail.

    Args:
        question: The user's question (pass the context variable).
        results: search() return dict or list of result dicts.
        top_n: Number of top results to evaluate (default 5).
        model: Optional model override for the sub-LLM call.

    Returns:
        Dict with:
          "ratings": [{"id": str, "rating": "RELEVANT"|"PARTIAL"|"OFF-TOPIC", "confidence": int}, ...]
          "suggestion": str (algorithmically derived next step)
          "raw": str (all sub-LLM responses joined by --- separator)
        Use ratings to filter results before format_evidence().
    """
    if isinstance(results, dict):
        results = results.get("results", [])
    if not results:
        return {"ratings": [], "suggestion": "No results to evaluate. Try a different query or remove filters.", "raw": ""}
    with _ToolCallTracker("evaluate_results", {"question": question[:100], "top_n": top_n}, parent_idx=_current_parent_idx) as tc:
        prompts = []
        ids = []
        for r in results[:top_n]:
            rid = str(r.get("id", "?"))
            ids.append(rid)
            score = r.get("score", 0)
            q = (r.get("question", "") or "")[:300]
            a = (r.get("answer", "") or "")[:1000]
            prompt = (
                f"Evaluate this search result for the question:\\n"
                f"\\"{question}\\"\\n\\n"
                f"Result [{rid}] score={score:.2f}\\n"
                f"Q: {q}\\n"
                f"A: {a}\\n\\n"
                f"Respond with exactly one line: RELEVANT|PARTIAL|OFF-TOPIC followed by CONFIDENCE:<1-5>\\n"
                f"RELEVANT = directly answers the question\\n"
                f"PARTIAL = related but incomplete\\n"
                f"OFF-TOPIC = not about this question"
            )
            prompts.append(prompt)
        responses = llm_query_batched(prompts, model=model)
        ratings = []
        raw_parts = []
        for i, resp in enumerate(responses):
            rid = ids[i] if i < len(ids) else "?"
            raw_parts.append(resp)
            if resp.strip().startswith("Error:"):
                ratings.append({"id": rid, "rating": "UNKNOWN", "confidence": 0})
                continue
            upper = resp.strip().upper()
            if "OFF-TOPIC" in upper or "OFF_TOPIC" in upper:
                rating = "OFF-TOPIC"
            elif "PARTIAL" in upper:
                rating = "PARTIAL"
            elif "RELEVANT" in upper:
                rating = "RELEVANT"
            else:
                rating = "UNKNOWN"
            confidence = 3
            if "CONFIDENCE:" in upper:
                try:
                    conf_str = upper.split("CONFIDENCE:")[1].strip()[:1]
                    confidence = int(conf_str)
                    confidence = max(1, min(5, confidence))
                except (ValueError, IndexError):
                    confidence = 3
            ratings.append({"id": rid, "rating": rating, "confidence": confidence})
        raw = "\\n---\\n".join(raw_parts)
        relevant_count = sum(1 for r in ratings if r["rating"] == "RELEVANT")
        partial_count = sum(1 for r in ratings if r["rating"] == "PARTIAL")
        off_topic_count = sum(1 for r in ratings if r["rating"] == "OFF-TOPIC")
        unknown_count = sum(1 for r in ratings if r["rating"] == "UNKNOWN")
        if relevant_count >= 3:
            suggestion = "Proceed to synthesis"
        elif relevant_count >= 1 or partial_count >= 2:
            suggestion = "Consider examining partial matches or refining"
        else:
            suggestion = "Refine the query"
        summary = f"{relevant_count} relevant, {partial_count} partial, {off_topic_count} off-topic"
        if unknown_count:
            summary += f", {unknown_count} unknown"
        print(f"[evaluate_results] {len(ratings)} rated: {summary}")
        print(f"[evaluate_results] suggestion: {suggestion}")
        tc.set_summary({"num_rated": len(ratings), "relevant": relevant_count, "partial": partial_count, "off_topic": off_topic_count})
        return {"ratings": ratings, "suggestion": suggestion, "raw": raw}


def reformulate(question, failed_query, top_score=0.0, model=None):
    """Sub-agent: generate alternative search queries when results are poor.

    Call when search() top score is below 0.3.

    Args:
        question: The user's original question.
        failed_query: The query that produced poor results.
        top_score: Best relevance score from the failed search.

    Returns:
        List of up to 3 alternative query strings.
    """
    with _ToolCallTracker("reformulate", {"failed_query": failed_query[:100], "top_score": top_score}, parent_idx=_current_parent_idx) as tc:
        prompt = (
            f"The search query \\"{failed_query}\\" returned poor results "
            f"(best score: {top_score:.2f}) for the question:\\n"
            f"\\"{question}\\"\\n\\n"
            f"Generate exactly 3 alternative search queries that might find better results.\\n"
            f"One query per line, no numbering, no quotes, no explanation."
        )
        response = llm_query(prompt, model=model)
        queries = [line.strip() for line in response.strip().split("\\n") if line.strip()]
        queries = queries[:3]
        print(f"[reformulate] generated {len(queries)} queries")
        tc.set_summary({"num_queries": len(queries)})
        return queries


def critique_answer(question, draft, model=None):
    """Sub-agent: review draft answer before finalizing.

    Call before FINAL/FINAL_VAR to catch citation errors, topic drift,
    and unsupported claims.

    Args:
        question: The user's original question.
        draft: The draft answer text to review.

    Returns:
        String: PASS or FAIL verdict with specific feedback.
    """
    with _ToolCallTracker("critique_answer", {"question": question[:100]}, parent_idx=_current_parent_idx) as tc:
        _MAX_DRAFT_LEN = 8000
        if len(draft) > _MAX_DRAFT_LEN:
            print(f"[critique_answer] WARNING: draft truncated from {len(draft)} to {_MAX_DRAFT_LEN} chars")
        prompt = (
            f"Review this draft answer to the question:\\n"
            f"\\"{question}\\"\\n\\n"
            f"Draft:\\n{draft[:_MAX_DRAFT_LEN]}\\n\\n"
            f"Check:\\n"
            f"1. Does it answer the actual question asked?\\n"
            f"2. Are [Source: <id>] citations present for factual claims?\\n"
            f"3. Are there unsupported claims or fabricated rulings?\\n"
            f"4. Is anything important missing?\\n\\n"
            f"Respond: PASS or FAIL, then brief feedback (under 150 words)."
        )
        verdict = llm_query(prompt, model=model)
        status = "PASS" if verdict.strip().strip("*").upper().startswith("PASS") else "FAIL"
        print(f"[critique_answer] verdict={status}")
        tc.set_summary({"verdict": status})
        return verdict


def _batched_critique(question, draft, model=None):
    """Internal: dual-reviewer critique via llm_query_batched.

    Returns (combined_verdict: str, passed: bool).
    """
    _MAX_DRAFT_LEN = 8000
    if len(draft) > _MAX_DRAFT_LEN:
        draft = draft[:_MAX_DRAFT_LEN]
    content_prompt = (
        f"You are a content expert. Review this draft answer to the question:\\n"
        f"\\"{question}\\"\\n\\n"
        f"Draft:\\n{draft}\\n\\n"
        f"Check:\\n"
        f"1. Does it answer the actual question asked?\\n"
        f"2. Are there unsupported claims or fabricated rulings?\\n"
        f"3. Is anything important missing?\\n\\n"
        f"Respond: PASS or FAIL, then brief feedback (under 100 words)."
    )
    citation_prompt = (
        f"You are a citation auditor. Review this draft answer to the question:\\n"
        f"\\"{question}\\"\\n\\n"
        f"Draft:\\n{draft}\\n\\n"
        f"Check:\\n"
        f"1. Are [Source: <id>] citations present for factual claims?\\n"
        f"2. Are any cited IDs missing or fabricated?\\n"
        f"3. Are there key claims without any citation?\\n\\n"
        f"Respond: PASS or FAIL, then brief feedback (under 100 words)."
    )
    responses = llm_query_batched([content_prompt, citation_prompt], model=model)
    content_verdict = responses[0] if len(responses) > 0 else "Error: no response"
    citation_verdict = responses[1] if len(responses) > 1 else "Error: no response"
    content_passed = content_verdict.strip().strip("*").upper().startswith("PASS")
    citation_passed = citation_verdict.strip().strip("*").upper().startswith("PASS")
    passed = content_passed and citation_passed
    failed_parts = []
    if not content_passed:
        failed_parts.append("content")
    if not citation_passed:
        failed_parts.append("citations")
    verdict_str = "PASS" if passed else "FAIL"
    failed_str = f" (failed: {', '.join(failed_parts)})" if failed_parts else ""
    print(f"[critique_answer] dual-review verdict={verdict_str}{failed_str}")
    combined = f"CONTENT: {content_verdict}\\n\\nCITATIONS: {citation_verdict}"
    return combined, passed


def classify_question(question, model=None):
    """Sub-agent: classify question and recommend search strategy.

    Optional — use if unsure which category fits after reviewing kb_overview().
    Uses the taxonomy data to pick category, clusters, and search plan.

    Args:
        question: The user's question.

    Returns:
        String with CATEGORY code, relevant CLUSTERS, and search STRATEGY.
    """
    with _ToolCallTracker("classify_question", {"question": question[:100]}, parent_idx=_current_parent_idx) as tc:
        cat_info = ""
        if _KB_OVERVIEW is not None:
            for cat_code, cat in _KB_OVERVIEW.get("categories", {}).items():
                name = cat.get("name", cat_code)
                clusters = cat.get("clusters", {})
                labels = ", ".join(list(clusters.keys())[:10])
                cat_info += f"{cat_code} — {name}: {labels}\\n"
        prompt = (
            f"Classify this Islamic Q&A question and recommend a search strategy.\\n\\n"
            f"Question: \\"{question}\\"\\n\\n"
            f"Categories and clusters:\\n{cat_info}\\n"
            f"Respond with exactly:\\n"
            f"CATEGORY: <code>\\n"
            f"CLUSTERS: <comma-separated relevant cluster labels>\\n"
            f"STRATEGY: <1-2 sentence search plan>"
        )
        classification = llm_query(prompt, model=model)
        print(f"[classify_question] done")
        tc.set_summary({"raw_length": len(classification)})
        return classification
'''

    # ── Composite tools ──────────────────────────────────────────────────
    # These orchestrate the low-level tools so the L0 agent writes fewer
    # code blocks.  They live at L0 (REPL) and make L2 calls internally.
    code += '''

def research(query, filters=None, top_k=10, extra_queries=None, eval_model=None):
    """Search, evaluate relevance, and deduplicate — all in one call.

    Runs searches, evaluates the top results for relevance,
    deduplicates by ID, and filters OFF-TOPIC hits.

    Args:
        query: Natural language string OR a list of search specs:
               [{"query": str, "filters": dict, "top_k": int,
                 "extra_queries": [...]}].
               List mode merges all results for a single dedup + eval pass.
        filters: Optional filter dict (string-query mode only).
        top_k: Results per search call (default 10).
        extra_queries: Optional list of {"query": str, "filters": dict, "top_k": int}
                       (string-query mode only).
        eval_model: Model for the relevance evaluation sub-call.

    Returns:
        Dict with:
          "results"  — deduplicated, filtered, score-sorted list
          "ratings"  — {id: "RELEVANT"|"PARTIAL"|"OFF-TOPIC"} for evaluated hits
          "search_count" — how many search() calls were made
          "eval_summary" — human-readable rating breakdown
    """
    global _current_parent_idx
    # Normalize: list-of-specs OR single query -> unified search task list
    if isinstance(query, list):
        if not query:
            print("[research] WARNING: empty query list")
            return {
                "results": [], "ratings": {}, "search_count": 0,
                "eval_summary": "no queries provided",
            }

    with _ToolCallTracker("research", {"query": query if isinstance(query, str) else f"{len(query)} specs", "top_k": top_k}, parent_idx=_current_parent_idx) as tc:
        _saved_parent = _current_parent_idx
        _current_parent_idx = tc.idx

        all_results = []
        search_count = 0
        errors = []

        if isinstance(query, list):
            specs = query
            eval_question = " ; ".join(s["query"] for s in specs)
        else:
            specs = [{"query": query, "filters": filters, "top_k": top_k, "extra_queries": extra_queries}]
            eval_question = query

        for spec in specs:
            q = spec["query"]
            f = spec.get("filters")
            k = spec.get("top_k", top_k)
            try:
                r = search(q, filters=f, top_k=k)
                all_results.extend(r["results"])
                search_count += 1
            except Exception as e:
                errors.append(str(e))
                print(f"[research] WARNING: search failed: {e}")
            for eq in (spec.get("extra_queries") or []):
                try:
                    r = search(eq["query"], filters=eq.get("filters"), top_k=eq.get("top_k", k))
                    all_results.extend(r["results"])
                    search_count += 1
                except Exception as e:
                    errors.append(str(e))
                    print(f"[research] WARNING: search failed: {e}")

        if not all_results:
            print("[research] ERROR: all searches failed")
            _current_parent_idx = _saved_parent
            tc.set_summary({
                "search_count": search_count,
                "raw": 0,
                "unique": 0,
                "filtered": 0,
                "eval_summary": "no results",
            })
            return {
                "results": [], "ratings": {}, "search_count": search_count,
                "eval_summary": "no results",
            }

        # Deduplicate by ID, keep highest score
        seen = {}
        for r in all_results:
            rid = r["id"]
            if rid not in seen or r["score"] > seen[rid]["score"]:
                seen[rid] = r
        deduped = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

        # Evaluate top results
        ratings_map = {}
        try:
            eval_out = evaluate_results(eval_question, deduped[:15], top_n=15, model=eval_model)
            for rt in eval_out["ratings"]:
                ratings_map[rt["id"]] = rt["rating"]
        except Exception as e:
            print(f"[research] WARNING: evaluation failed, returning unrated: {e}")

        # Filter OFF-TOPIC
        filtered = [r for r in deduped if ratings_map.get(r["id"], "UNRATED") != "OFF-TOPIC"]

        relevant = sum(1 for v in ratings_map.values() if v == "RELEVANT")
        partial = sum(1 for v in ratings_map.values() if v == "PARTIAL")
        off_topic = sum(1 for v in ratings_map.values() if v == "OFF-TOPIC")
        summary = f"{relevant} relevant, {partial} partial, {off_topic} off-topic"

        print(f"[research] {search_count} searches | {len(all_results)} raw > {len(deduped)} unique > {len(filtered)} filtered")
        print(f"[research] {summary}")
        for r in filtered[:5]:
            tag = ratings_map.get(r["id"], "-")
            print(f"  [{r['id']}] {r['score']:.2f} {tag:10s} Q: {r['question'][:100]}")
        if len(filtered) > 5:
            print(f"  ... and {len(filtered) - 5} more")

        _current_parent_idx = _saved_parent
        tc.set_summary({
            "search_count": search_count,
            "raw": len(all_results),
            "unique": len(deduped),
            "filtered": len(filtered),
            "eval_summary": summary,
        })

        result = {
            "results": filtered, "ratings": ratings_map,
            "search_count": search_count, "eval_summary": summary,
        }
        if errors:
            result["errors"] = errors
        return result


def draft_answer(question, results, instructions=None, model=None):
    """Synthesize an answer from results, critique it, and revise if needed.

    Handles: format_evidence -> llm_query synthesis -> critique ->
    conditional revision (one retry on FAIL).

    Args:
        question: The user's question (pass ``context``).
        results: List of result dicts (use ``research()["results"]``).
        instructions: Optional guidance for the synthesis LLM call
                      (e.g. "address each of the 4 scenarios separately").
        model: Optional model override for synthesis / revision.

    Returns:
        Dict with:
          "answer"   — final answer text
          "critique" — critique feedback string
          "passed"   — True if critique gave PASS verdict
          "revised"  — True if the answer was revised after initial FAIL
    """
    global _current_parent_idx
    evidence = format_evidence(results[:20])
    if not evidence:
        print("[draft_answer] ERROR: no evidence to synthesize from")
        return {"answer": "", "critique": "", "passed": False, "revised": False}

    with _ToolCallTracker("draft_answer", {"question": question[:100], "num_results": len(results)}, parent_idx=_current_parent_idx) as tc:
        _saved_parent = _current_parent_idx
        _current_parent_idx = tc.idx

        prompt_parts = [
            "You are an Islamic Q&A scholar synthesizing from verified sources.\\n\\n",
            f"QUESTION:\\n{question}\\n\\n",
            "EVIDENCE:\\n" + "\\n".join(evidence) + "\\n\\n",
        ]
        if instructions:
            prompt_parts.append(f"INSTRUCTIONS:\\n{instructions}\\n\\n")
        prompt_parts.append(
            "FORMAT: ## Answer (with [Source: <id>] citations), "
            "## Evidence (source summaries), ## Confidence (High/Medium/Low).\\n"
            "Only cite IDs from the evidence. Flag gaps explicitly.\\n"
        )

        answer = llm_query("".join(prompt_parts), model=model)

        critique_text, passed = _batched_critique(question, answer, model=model)
        revised = False

        if not passed:
            rev_parts = [
                "Revise this answer based on the critique.\\n\\n",
                f"CRITIQUE:\\n{critique_text}\\n\\n",
                f"ORIGINAL:\\n{answer}\\n\\n",
                "EVIDENCE:\\n" + "\\n".join(evidence) + "\\n\\n",
                "Fix flagged issues. Keep valid citations. Same format.\\n",
            ]
            answer = llm_query("".join(rev_parts), model=model)
            critique_text, passed = _batched_critique(question, answer, model=model)
            revised = True

        print(
            f"[draft_answer] {'PASS' if passed else 'FAIL'}"
            f"{' (revised)' if revised else ''}"
            f" | {len(answer)} chars | {len(evidence)} evidence entries"
        )
        _current_parent_idx = _saved_parent
        tc.set_summary({
            "passed": passed,
            "revised": revised,
            "answer_length": len(answer),
        })
        return {"answer": answer, "critique": critique_text, "passed": passed, "revised": revised}
'''

    return code
