"""Sub-agent tools: LLM-dependent evaluation, reformulation, critique, classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.tools.constants import MAX_DRAFT_LEN
from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def _parse_rating_line(line: str) -> tuple[str, str, int] | None:
    """Parse a single rating line like '[1234] RELEVANT CONFIDENCE:4'.

    Returns (id, rating, confidence) or None if unparseable.
    """
    line = line.strip()
    if not line or not line.startswith("["):
        return None
    # Extract ID between brackets
    bracket_end = line.find("]")
    if bracket_end < 0:
        return None
    rid = line[1:bracket_end].strip()
    rest = line[bracket_end + 1:].strip().upper()
    # Parse rating
    if "OFF-TOPIC" in rest or "OFF_TOPIC" in rest:
        rating = "OFF-TOPIC"
    elif "PARTIAL" in rest:
        rating = "PARTIAL"
    elif "RELEVANT" in rest:
        rating = "RELEVANT"
    else:
        return None
    # Parse confidence
    confidence = 3
    if "CONFIDENCE:" in rest:
        try:
            conf_str = rest.split("CONFIDENCE:")[1].strip()[:1]
            confidence = max(1, min(5, int(conf_str)))
        except (ValueError, IndexError):
            confidence = 3
    return rid, rating, confidence


def evaluate_results(
    ctx: ToolContext,
    question: str,
    results: list | dict,
    top_n: int = 5,
    model: str | None = None,
) -> dict:
    """Sub-agent: evaluate search result relevance in a single batched prompt.

    Sends all results in one LLM call for consistent cross-result calibration.
    Falls back to per-result calls if batch parsing fails.

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
        to_eval = results[:top_n]
        ids = [str(r.get("id", "?")) for r in to_eval]

        # Build single batched prompt with all results
        result_blocks = []
        for r in to_eval:
            rid = str(r.get("id", "?"))
            score = r.get("score", 0)
            q = (r.get("question", "") or "")[:300]
            a = (r.get("answer", "") or "")[:1000]
            result_blocks.append(
                f"[{rid}] score={score:.2f}\n"
                f"Q: {q}\n"
                f"A: {a}"
            )

        batch_prompt = (
            f"Evaluate these search results for relevance to the question:\n"
            f'"{question}"\n\n'
            + "\n\n".join(result_blocks)
            + "\n\n"
            f"For each result, respond with exactly one line:\n"
            f"[<id>] RELEVANT|PARTIAL|OFF-TOPIC CONFIDENCE:<1-5>\n\n"
            f"RELEVANT = provides applicable rulings, evidence, or answers for the question (even if framed differently)\n"
            f"PARTIAL = tangentially related but does not address the core issue\n"
            f"OFF-TOPIC = about a completely different subject\n\n"
            f"Respond with {len(to_eval)} lines, one per result, in the same order."
        )

        raw = ctx.llm_query(batch_prompt, model=model)

        # Parse batch response line by line
        ratings = []
        parsed_ids: set[str] = set()
        if not raw.strip().startswith("Error:"):
            for line in raw.strip().split("\n"):
                parsed = _parse_rating_line(line)
                if parsed is not None:
                    rid, rating, confidence = parsed
                    ratings.append({"id": rid, "rating": rating, "confidence": confidence})
                    parsed_ids.add(rid)

        # Check if we got ratings for enough results (>50% threshold)
        if len(ratings) < len(to_eval) * 0.5:
            # Fallback: per-result prompts via batched call
            print(
                f"[evaluate_results] batch parse got {len(ratings)}/{len(to_eval)}, "
                f"falling back to per-result"
            )
            prompts = []
            for r in to_eval:
                rid = str(r.get("id", "?"))
                score = r.get("score", 0)
                q = (r.get("question", "") or "")[:300]
                a = (r.get("answer", "") or "")[:1000]
                prompts.append(
                    f"Evaluate this search result for the question:\n"
                    f'"{question}"\n\n'
                    f"Result [{rid}] score={score:.2f}\n"
                    f"Q: {q}\nA: {a}\n\n"
                    f"Respond with exactly one line: RELEVANT|PARTIAL|OFF-TOPIC followed by CONFIDENCE:<1-5>\n"
                    f"RELEVANT = provides applicable rulings, evidence, or answers for the question (even if framed differently)\n"
                    f"PARTIAL = tangentially related but does not address the core issue\n"
                    f"OFF-TOPIC = about a completely different subject"
                )
            responses = ctx.llm_query_batched(prompts, model=model)
            ratings = []
            raw_parts = [raw, "---FALLBACK---"]
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
                        confidence = max(1, min(5, int(conf_str)))
                    except (ValueError, IndexError):
                        confidence = 3
                ratings.append({"id": rid, "rating": rating, "confidence": confidence})
            raw = "\n---\n".join(raw_parts)
        else:
            # Fill in any missing IDs from the batch parse as UNKNOWN
            for rid in ids:
                if rid not in parsed_ids:
                    ratings.append({"id": rid, "rating": "UNKNOWN", "confidence": 0})

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
    """Unified single-pass critique (content + citations in one LLM call).

    Returns:
        Tuple of (verdict_text, passed).
    """
    with tool_call_tracker(
        ctx,
        "batched_critique",
        {"question": question[:100]},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        if len(draft) > MAX_DRAFT_LEN:
            draft = draft[:MAX_DRAFT_LEN]
        prompt = (
            f"Review this draft answer to the question:\n"
            f'"{question}"\n\n'
            f"Draft:\n{draft}\n\n"
            f"Check BOTH content and citations:\n\n"
            f"CONTENT:\n"
            f"1. Does it answer the actual question asked?\n"
            f"2. Are there unsupported claims or fabricated rulings?\n"
            f"3. Is anything important missing?\n\n"
            f"CITATIONS:\n"
            f"1. Are [Source: <id>] citations present for factual claims?\n"
            f"2. Are any cited IDs missing or fabricated?\n"
            f"3. Are there key claims without any citation?\n\n"
            f"Respond: PASS or FAIL, then brief feedback (under 150 words).\n"
            f"If ANY check fails, the overall verdict is FAIL."
        )
        verdict = ctx.llm_query(prompt, model=model)
        passed = verdict.strip().strip("*").upper().startswith("PASS")
        verdict_str = "PASS" if passed else "FAIL"
        failed_str = "" if passed else " (failed: unified review)"
        print(f"[critique_answer] dual-review verdict={verdict_str}{failed_str}")
        feedback = verdict.split("\n", 1)[1].strip() if "\n" in verdict else ""
        tc.set_summary({
            "verdict": verdict_str,
            "content_passed": passed,
            "citation_passed": passed,
            "feedback": feedback[:200],
            # Backward compat for frontend CritiqueDetail renderer
            "reason": feedback[:200],
            "content_feedback": feedback[:150],
            "citation_feedback": feedback[:150],
            "failed": [] if passed else ["unified"],
        })
        return verdict, passed


# Stop words excluded from query token matching
_CLASSIFY_STOP_WORDS = frozenset(
    "is it a the to can i do how what in of for and or but from with this that are was were"
    " be been have has had my your his her its on at by an".split()
)


def _match_clusters(question: str, grouped_results: list) -> list[str]:
    """Rank clusters by token overlap with question against sample hits + labels.

    Returns up to 5 cluster labels, ordered by relevance score.
    Falls back to top 2 by document count when no tokens match.
    """
    if not grouped_results:
        return []

    query_tokens = set(question.lower().split()) - _CLASSIFY_STOP_WORDS

    scores: list[tuple[str, int, int]] = []
    for group in grouped_results:
        label = group.get("label", "")
        label_tokens = set(label.lower().split()) - _CLASSIFY_STOP_WORDS
        # Label matches weighted 3x (cluster name is high-signal)
        score = len(query_tokens & label_tokens) * 3
        # Sample hit question matches weighted 1x each
        for hit in group.get("hits", []):
            q = hit.get("question", "").lower()
            hit_tokens = set(q.split()) - _CLASSIFY_STOP_WORDS
            score += len(query_tokens & hit_tokens)
        scores.append((label, score, group.get("total_count", 0)))

    # Sort by match score desc, break ties by doc count desc
    scores.sort(key=lambda x: (-x[1], -x[2]))

    matched = [s[0] for s in scores if s[1] > 0]
    if matched:
        return matched[:5]
    # Fallback: top 2 by document count
    return [s[0] for s in scores[:2]]


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

    # Build category + cluster summary with doc counts and sample questions
    cat_lines = []
    for code, cat in ctx.kb_overview_data.get("categories", {}).items():
        name = cat.get("name", code)
        doc_count = cat.get("document_count", 0)
        # Get cluster counts from facets (richer than just names)
        facet_clusters = {
            c["value"]: c["count"]
            for c in cat.get("facets", {}).get("clusters", [])
        }
        # Merge with cluster sample questions
        cluster_samples = cat.get("clusters", {})
        cluster_parts = []
        # Show largest clusters first (most representative of category)
        sorted_labels = sorted(
            cluster_samples.keys(),
            key=lambda l: facet_clusters.get(l, 0),
            reverse=True,
        )
        for label in sorted_labels[:20]:
            count = facet_clusters.get(label, "")
            sample = (cluster_samples.get(label) or "")[:80]
            entry = label
            if count:
                entry += f" ({count})"
            if sample:
                entry += f' — "{sample}"'
            cluster_parts.append(entry)
        cat_lines.append(
            f"{code} — {name} [{doc_count} docs]\n"
            + "\n".join(f"  · {c}" for c in cluster_parts)
        )
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
                'Q: "Is it permissible for a wife to refuse intimacy?"\n'
                "CATEGORY: MF\n"
                "CLUSTERS: Marital Rights and Duties, Intimacy in Marriage\n"
                'FILTERS: {"parent_code": "MF"}\n'
                "STRATEGY: Search marital rights, refusal, and intimate relations rulings\n\n"
                'Q: "What are the different types of shirk?"\n'
                "CATEGORY: BE\n"
                "CLUSTERS: Shirk and Polytheism, Tawhid Fundamentals\n"
                'FILTERS: {"parent_code": "BE"}\n'
                "STRATEGY: Broad topic — search shirk types, major vs minor shirk\n\n"
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
