"""Sub-agent tools: LLM-dependent evaluation, reformulation, critique, classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.tools.constants import MAX_DRAFT_LEN
from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def evaluate_results(
    ctx: ToolContext,
    question: str,
    results: list | dict,
    top_n: int = 5,
    model: str | None = None,
) -> dict:
    """Sub-agent: evaluate search result relevance with per-result confidence scores.

    Call after ``search()`` to check whether results match the question
    before spending a turn examining them in detail.

    Args:
        ctx: Per-session tool context.
        question: The user's question.
        results: ``search()`` return dict or list of result dicts.
        top_n: Number of top results to evaluate (default 5).
        model: Optional model override for the sub-LLM call.

    Returns:
        Dict with ``ratings``, ``suggestion``, and ``raw``.
    """
    if isinstance(results, dict):
        results = results.get("results", [])
    if not results:
        return {
            "ratings": [],
            "suggestion": "No results to evaluate. Try a different query or remove filters.",
            "raw": "",
        }
    with tool_call_tracker(
        ctx,
        "evaluate_results",
        {"question": question[:100], "top_n": top_n},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        prompts = []
        ids: list[str] = []
        for r in results[:top_n]:
            rid = str(r.get("id", "?"))
            ids.append(rid)
            score = r.get("score", 0)
            q = (r.get("question", "") or "")[:300]
            a = (r.get("answer", "") or "")[:1000]
            prompt = (
                f"Evaluate this search result for the question:\n"
                f'"{question}"\n\n'
                f"Result [{rid}] score={score:.2f}\n"
                f"Q: {q}\n"
                f"A: {a}\n\n"
                f"Respond with exactly one line: RELEVANT|PARTIAL|OFF-TOPIC followed by CONFIDENCE:<1-5>\n"
                f"RELEVANT = directly answers the question\n"
                f"PARTIAL = related but incomplete\n"
                f"OFF-TOPIC = not about this question"
            )
            prompts.append(prompt)

        responses = ctx.llm_query_batched(prompts, model=model)
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

        raw = "\n---\n".join(raw_parts)
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
        tc.set_summary(
            {
                "num_rated": len(ratings),
                "relevant": relevant_count,
                "partial": partial_count,
                "off_topic": off_topic_count,
            }
        )
        return {"ratings": ratings, "suggestion": suggestion, "raw": raw}


def reformulate(
    ctx: ToolContext,
    question: str,
    failed_query: str,
    top_score: float = 0.0,
    model: str | None = None,
) -> list[str]:
    """Sub-agent: generate alternative search queries when results are poor.

    Call when ``search()`` top score is below 0.3.

    Args:
        ctx: Per-session tool context.
        question: The user's original question.
        failed_query: The query that produced poor results.
        top_score: Best relevance score from the failed search.

    Returns:
        List of up to 3 alternative query strings.
    """
    with tool_call_tracker(
        ctx,
        "reformulate",
        {"failed_query": failed_query[:100], "top_score": top_score},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        prompt = (
            f'The search query "{failed_query}" returned poor results '
            f"(best score: {top_score:.2f}) for the question:\n"
            f'"{question}"\n\n'
            f"Generate exactly 3 alternative search queries that might find better results.\n"
            f"One query per line, no numbering, no quotes, no explanation."
        )
        response = ctx.llm_query(prompt, model=model)
        queries = [line.strip() for line in response.strip().split("\n") if line.strip()]
        queries = queries[:3]
        print(f"[reformulate] generated {len(queries)} queries")
        tc.set_summary({"num_queries": len(queries)})
        return queries


def critique_answer(
    ctx: ToolContext,
    question: str,
    draft: str,
    model: str | None = None,
) -> str:
    """Sub-agent: review draft answer before finalizing.

    Call before FINAL/FINAL_VAR to catch citation errors, topic drift,
    and unsupported claims.

    Args:
        ctx: Per-session tool context.
        question: The user's original question.
        draft: The draft answer text to review.

    Returns:
        String: PASS or FAIL verdict with specific feedback.
    """
    with tool_call_tracker(
        ctx,
        "critique_answer",
        {"question": question[:100]},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        if len(draft) > MAX_DRAFT_LEN:
            print(
                f"[critique_answer] WARNING: draft truncated from {len(draft)} to {MAX_DRAFT_LEN} chars"
            )
        prompt = (
            f"Review this draft answer to the question:\n"
            f'"{question}"\n\n'
            f"Draft:\n{draft[:MAX_DRAFT_LEN]}\n\n"
            f"Check:\n"
            f"1. Does it answer the actual question asked?\n"
            f"2. Are [Source: <id>] citations present for factual claims?\n"
            f"3. Are there unsupported claims or fabricated rulings?\n"
            f"4. Is anything important missing?\n\n"
            f"Respond: PASS or FAIL, then brief feedback (under 150 words)."
        )
        verdict = ctx.llm_query(prompt, model=model)
        status = "PASS" if verdict.strip().strip("*").upper().startswith("PASS") else "FAIL"
        print(f"[critique_answer] verdict={status}")
        tc.set_summary({"verdict": status})
        return verdict


def batched_critique(
    ctx: ToolContext,
    question: str,
    draft: str,
    model: str | None = None,
) -> tuple[str, bool]:
    """Dual-reviewer critique via ``llm_query_batched``.

    Returns:
        Tuple of (combined_verdict, passed).
    """
    if len(draft) > MAX_DRAFT_LEN:
        draft = draft[:MAX_DRAFT_LEN]
    content_prompt = (
        f"You are a content expert. Review this draft answer to the question:\n"
        f'"{question}"\n\n'
        f"Draft:\n{draft}\n\n"
        f"Check:\n"
        f"1. Does it answer the actual question asked?\n"
        f"2. Are there unsupported claims or fabricated rulings?\n"
        f"3. Is anything important missing?\n\n"
        f"Respond: PASS or FAIL, then brief feedback (under 100 words)."
    )
    citation_prompt = (
        f"You are a citation auditor. Review this draft answer to the question:\n"
        f'"{question}"\n\n'
        f"Draft:\n{draft}\n\n"
        f"Check:\n"
        f"1. Are [Source: <id>] citations present for factual claims?\n"
        f"2. Are any cited IDs missing or fabricated?\n"
        f"3. Are there key claims without any citation?\n\n"
        f"Respond: PASS or FAIL, then brief feedback (under 100 words)."
    )
    responses = ctx.llm_query_batched([content_prompt, citation_prompt], model=model)
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
    combined = f"CONTENT: {content_verdict}\n\nCITATIONS: {citation_verdict}"
    return combined, passed


def classify_question(
    ctx: ToolContext,
    question: str,
    model: str | None = None,
) -> str:
    """Sub-agent: classify question and recommend search strategy.

    Optional — use if unsure which category fits after reviewing ``kb_overview()``.
    Uses the taxonomy data to pick category, clusters, and search plan.

    Args:
        ctx: Per-session tool context.
        question: The user's question.

    Returns:
        String with CATEGORY code, relevant CLUSTERS, and search STRATEGY.
    """
    with tool_call_tracker(
        ctx,
        "classify_question",
        {"question": question[:100]},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        cat_info = ""
        if ctx.kb_overview_data is not None:
            for cat_code, cat in ctx.kb_overview_data.get("categories", {}).items():
                name = cat.get("name", cat_code)
                clusters = cat.get("clusters", {})
                labels = ", ".join(list(clusters.keys())[:10])
                cat_info += f"{cat_code} — {name}: {labels}\n"
        prompt = (
            f"Classify this Islamic Q&A question and recommend a search strategy.\n\n"
            f'Question: "{question}"\n\n'
            f"Categories and clusters:\n{cat_info}\n"
            f"Respond with exactly:\n"
            f"CATEGORY: <code>\n"
            f"CLUSTERS: <comma-separated relevant cluster labels>\n"
            f"STRATEGY: <1-2 sentence search plan>"
        )
        classification = ctx.llm_query(prompt, model=model)
        print("[classify_question] done")
        tc.set_summary({"raw_length": len(classification)})
        return classification
