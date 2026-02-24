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
        tc.set_summary({
            "num_rated": len(ratings),
            "relevant": relevant_count,
            "partial": partial_count,
            "off_topic": off_topic_count,
            "ratings": [
                {
                    "id": r.get("id", ""),
                    "rating": r.get("rating", "UNKNOWN"),
                    "confidence": r.get("confidence", 0),
                }
                for r in ratings
            ],
        })
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
        tc.set_summary({
            "num_queries": len(queries),
            "queries": queries,
        })
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
        reason_text = verdict.split("\n", 1)[1].strip() if "\n" in verdict else ""
        tc.set_summary({
            "verdict": status,
            "reason": reason_text[:150],
        })
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
    with tool_call_tracker(
        ctx,
        "batched_critique",
        {"question": question[:100]},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
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
        content_feedback = content_verdict.split("\n", 1)[1].strip() if "\n" in content_verdict else ""
        citation_feedback = citation_verdict.split("\n", 1)[1].strip() if "\n" in citation_verdict else ""
        tc.set_summary({
            "verdict": verdict_str,
            "content_passed": content_passed,
            "citation_passed": citation_passed,
            "content_feedback": content_feedback[:150],
            "citation_feedback": citation_feedback[:150],
            "failed": [
                *([] if content_passed else ["content"]),
                *([] if citation_passed else ["citations"]),
            ],
        })
        return combined, passed


def init_classify(
    ctx: ToolContext,
    question: str,
    model: str = "",
) -> None:
    """Pre-classify query at setup_code time (zero iteration cost).

    Creates its own LM client for model flexibility, parses the raw LLM
    output into a structured dict, and stores it on ``ctx.classification``.
    Emits ``classifying`` / ``classified`` progress events via
    ``ctx._parent_logger``.

    On any failure, sets ``ctx.classification = None`` and logs a warning.
    """
    import json as _json
    import logging
    import time

    _log = logging.getLogger("rlm_search")

    if not ctx.kb_overview_data:
        ctx.classification = None
        return

    # Resolve model
    if not model:
        from rlm_search.config import RLM_CLASSIFY_MODEL

        model = RLM_CLASSIFY_MODEL

    # Emit progress: classifying
    if ctx._parent_logger is not None:
        ctx._parent_logger.emit_progress("classifying", f"Pre-classifying with {model}")

    # Build category + cluster summary
    cat_lines = []
    for code, cat in ctx.kb_overview_data.get("categories", {}).items():
        name = cat.get("name", code)
        clusters = list(cat.get("clusters", {}).keys())[:10]
        cat_lines.append(f"{code} — {name}: {', '.join(clusters)}")
    cat_info = "\n".join(cat_lines)

    prompt = [
        {
            "role": "user",
            "content": (
                "Classify this Islamic Q&A question into one of these categories"
                " and suggest search filters.\n\n"
                f'Question: "{question}"\n\n'
                f"Categories and their clusters:\n{cat_info}\n\n"
                "Examples:\n"
                'Q: "Is it permissible to take a mortgage from a bank?"\n'
                "CATEGORY: FN\n"
                "CLUSTERS: Banking Riba Operations, Riba in Loan Contracts\n"
                'FILTERS: {"parent_code": "FN"}\n'
                "STRATEGY: Search for riba, mortgage, and bank loan rulings\n\n"
                'Q: "How do I perform ghusl janabah?"\n'
                "CATEGORY: PT\n"
                "CLUSTERS: Ghusl\n"
                'FILTERS: {"parent_code": "PT", "cluster_label": "Ghusl"}\n'
                "STRATEGY: Search for ghusl types and requirements\n\n"
                "Now classify the question above.\n"
                "Respond with exactly (no other text):\n"
                "CATEGORY: <code>\n"
                "CLUSTERS: <comma-separated relevant cluster labels from the list above>\n"
                'FILTERS: <json dict, e.g. {"parent_code": "BE"}>\n'
                "STRATEGY: <1 sentence search plan>"
            ),
        },
    ]

    t0 = time.monotonic()

    with tool_call_tracker(
        ctx,
        "init_classify",
        {"question": question[:100], "model": model},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        try:
            from rlm.clients import get_client
            from rlm_search.config import ANTHROPIC_API_KEY, RLM_BACKEND

            if RLM_BACKEND == "claude_cli":
                client_kwargs: dict = {"model": model}
            else:
                client_kwargs = {"model_name": model}
                if ANTHROPIC_API_KEY:
                    client_kwargs["api_key"] = ANTHROPIC_API_KEY

            client = get_client(RLM_BACKEND, client_kwargs)
            raw = client.completion(prompt)

            # Parse structured fields from raw output
            parsed: dict = {
                "raw": raw,
                "category": "",
                "clusters": "",
                "filters": {},
                "strategy": "",
            }
            for line in raw.strip().split("\n"):
                line_s = line.strip()
                if line_s.upper().startswith("CATEGORY:"):
                    parsed["category"] = line_s.split(":", 1)[1].strip()
                elif line_s.upper().startswith("CLUSTERS:"):
                    parsed["clusters"] = line_s.split(":", 1)[1].strip()
                elif line_s.upper().startswith("FILTERS:"):
                    try:
                        parsed["filters"] = _json.loads(line_s.split(":", 1)[1].strip())
                    except (_json.JSONDecodeError, ValueError):
                        parsed["filters"] = {}
                elif line_s.upper().startswith("STRATEGY:"):
                    parsed["strategy"] = line_s.split(":", 1)[1].strip()

            ctx.classification = parsed
            classify_ms = int((time.monotonic() - t0) * 1000)
            print(f"[classify] category={parsed['category']} time={classify_ms}ms")
            tc.set_summary(
                {
                    "category": parsed["category"],
                    "clusters": parsed["clusters"],
                    "duration_ms": classify_ms,
                }
            )

            # Emit progress: classified
            if ctx._parent_logger is not None:
                ctx._parent_logger.emit_progress(
                    "classified",
                    f"Pre-classified in {classify_ms}ms",
                    duration_ms=classify_ms,
                    classification=parsed,
                )

        except Exception as e:
            _log.warning("Pre-classification failed, proceeding without: %s", e)
            ctx.classification = None
            classify_ms = int((time.monotonic() - t0) * 1000)
            print(f"[classify] FAILED: {e}")
            tc.set_summary({"error": str(e), "duration_ms": classify_ms})

            # Emit classified with no classification on failure
            if ctx._parent_logger is not None:
                ctx._parent_logger.emit_progress(
                    "classified",
                    f"Classification skipped ({classify_ms}ms)",
                    duration_ms=classify_ms,
                )
