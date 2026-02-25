"""Sub-agent tools: LLM-dependent evaluation, reformulation, critique, classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm.clients import get_client
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
    rest = line[bracket_end + 1 :].strip().upper()
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
            result_blocks.append(f"[{rid}] score={score:.2f}\nQ: {q}\nA: {a}")

        batch_prompt = (
            f"Evaluate these search results for relevance to the question:\n"
            f'"{question}"\n\n' + "\n\n".join(result_blocks) + "\n\n"
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
        tc.set_summary(
            {
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
        tc.set_summary(
            {
                "num_queries": len(queries),
                "queries": queries,
            }
        )
        return queries


def critique_answer(
    ctx: ToolContext,
    question: str,
    draft: str,
    evidence: list[str] | None = None,
    model: str | None = None,
) -> tuple[str, bool]:
    """Evidence-grounded critique: cross-check draft citations against sources.

    When evidence is provided, checks citation accuracy, attribution fidelity,
    unsupported claims, and completeness against actual sources. When evidence
    is omitted but ``ctx.source_registry`` has accumulated results, auto-builds
    evidence from the session state so the critique is still grounded.

    Returns:
        Tuple of (verdict_text, passed).
    """
    # Option B: auto-pull evidence from session state when caller omits it
    if evidence is None and ctx.source_registry:
        from rlm_search.tools.format_tools import format_evidence

        evidence = format_evidence(list(ctx.source_registry.values()), max_per_source=3)
        if not evidence:
            evidence = None  # format_evidence returned [] — fall back to generic

    with tool_call_tracker(
        ctx,
        "critique_answer",
        {"question": question[:100], "has_evidence": bool(evidence)},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        if len(draft) > MAX_DRAFT_LEN:
            draft = draft[:MAX_DRAFT_LEN]

        school_context = (
            "Sources are scholar-answered Q&A. Do not flag positions as incorrect "
            "based on other schools of thought. Judge only against the provided evidence.\n\n"
        )

        if evidence:
            evidence_block = "\n".join(evidence)
            prompt = (
                f"{school_context}"
                f"Review this draft answer against the provided evidence.\n\n"
                f"QUESTION:\n{question}\n\n"
                f"EVIDENCE:\n{evidence_block}\n\n"
                f"DRAFT:\n{draft}\n\n"
                f"Check these four criteria:\n\n"
                f"1. CITATION ACCURACY — Every [Source: N] in the draft must map to "
                f"a real source in the evidence above. Flag any fabricated IDs.\n\n"
                f"2. ATTRIBUTION FIDELITY — Claims attributed to specific scholars, "
                f"texts, or rulings must actually appear in the cited source.\n\n"
                f"3. UNSUPPORTED CLAIMS — Flag substantive rulings or factual "
                f"claims that have no [Source: N] citation.\n\n"
                f"4. COMPLETENESS — Key points from high-relevance evidence should "
                f"not be omitted if they directly answer the question.\n\n"
                f"Respond: PASS or FAIL, then brief feedback (under 150 words).\n"
                f"If ANY check fails, the overall verdict is FAIL."
            )
        else:
            prompt = (
                f"{school_context}"
                f"Review this draft answer to the question:\n"
                f'"{question}"\n\n'
                f"Draft:\n{draft}\n\n"
                f"Check:\n"
                f"1. Does it answer the actual question asked?\n"
                f"2. Are there unsupported claims or fabricated rulings?\n"
                f"3. Is anything important missing?\n"
                f"4. Are [Source: N] citations present for factual claims?\n\n"
                f"Respond: PASS or FAIL, then brief feedback (under 150 words).\n"
                f"If ANY check fails, the overall verdict is FAIL."
            )

        verdict = ctx.llm_query(prompt, model=model)
        passed = verdict.strip().strip("*").upper().startswith("PASS")
        verdict_str = "PASS" if passed else "FAIL"
        failed_str = "" if passed else " (failed: evidence-grounded review)"
        print(f"[critique_answer] verdict={verdict_str}{failed_str}")
        feedback = verdict.split("\n", 1)[1].strip() if "\n" in verdict else ""
        tc.set_summary(
            {
                "verdict": verdict_str,
                "has_evidence": bool(evidence),
                "feedback": feedback[:200],
                # Backward compat for frontend CritiqueDetail renderer
                "reason": feedback[:200],
                "failed": [] if passed else ["evidence_review"],
            }
        )
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


def _build_category_prompt(question: str, kb_overview_data: dict) -> str:
    """Build Phase 1 prompt: 6-way category classification (no clusters).

    Returns the user-role content string for the classification LLM call.
    Deliberately excludes cluster labels — Phase 3 handles cluster selection
    via browse() + deterministic matching.
    """
    cat_lines = []
    for code, cat in kb_overview_data.get("categories", {}).items():
        name = cat.get("name", code)
        doc_count = cat.get("document_count", 0)
        cat_lines.append(f"{code} — {name} [{doc_count} docs]")
    cat_info = "\n".join(cat_lines)

    return (
        "Classify this Islamic Q&A question into one category.\n\n"
        f'Question: "{question}"\n\n'
        f"Categories:\n{cat_info}\n\n"
        "Examples:\n"
        '"Is it permissible to take a mortgage?" → FN\n'
        '"How do I perform ghusl?" → PT\n'
        '"Is it permissible for a wife to refuse intimacy?" → MF\n'
        '"What are the types of shirk?" → BE\n'
        '"Can I pray Eid salah at home?" → WP\n'
        '"Is it permissible to cremate the dead?" → OT\n\n'
        "Respond with exactly one line:\n"
        "CATEGORY: <code>"
    )


def init_classify(
    ctx: ToolContext,
    question: str,
    model: str = "",
) -> None:
    """Pre-classify query via two-phase approach (zero iteration cost).

    Phase 1: LLM picks parent_code from 6 categories (simple, reliable).
    Phase 2: browse() gets live cluster landscape for that category.
    Phase 3: Deterministic token matching ranks clusters by relevance.

    On any failure, sets ``ctx.classification = None`` and logs a warning.
    """
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
    bus = getattr(ctx, "bus", None)
    if bus is not None:
        bus.emit(
            "tool_progress",
            {"phase": "classifying", "message": f"Pre-classifying with {model}"},
        )
    elif ctx._parent_logger is not None:
        ctx._parent_logger.emit_progress("classifying", f"Pre-classifying with {model}")

    t0 = time.monotonic()

    with tool_call_tracker(
        ctx,
        "init_classify",
        {"question": question[:100], "model": model},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        try:
            # ── Phase 1: Category classification (LLM) ──────────────────
            from rlm_search.config import ANTHROPIC_API_KEY, RLM_BACKEND

            if RLM_BACKEND == "claude_cli":
                client_kwargs: dict = {"model": model}
            else:
                client_kwargs = {"model_name": model}
                if ANTHROPIC_API_KEY:
                    client_kwargs["api_key"] = ANTHROPIC_API_KEY

            client = get_client(RLM_BACKEND, client_kwargs)
            prompt_text = _build_category_prompt(question, ctx.kb_overview_data)
            raw = client.completion([{"role": "user", "content": prompt_text}])

            # Parse category code from response
            category = ""
            for line in raw.strip().split("\n"):
                line_s = line.strip()
                if line_s.upper().startswith("CATEGORY:"):
                    category = line_s.split(":", 1)[1].strip().upper()
                    break

            if not category:
                _log.warning("Phase 1 returned no category, raw=%r", raw[:200])
                ctx.classification = None
                classify_ms = int((time.monotonic() - t0) * 1000)
                tc.set_summary({"error": "no category parsed", "duration_ms": classify_ms})
                return

            # ── Phase 2: Browse category clusters (API call) ────────────
            clusters_str = ""
            strategy = ""
            try:
                from rlm_search.tools.api_tools import browse as _browse

                browse_result = _browse(
                    ctx,
                    filters={"parent_code": category},
                    group_by="cluster_label",
                    group_limit=3,
                    limit=1,
                )

                # ── Phase 3: Deterministic cluster matching ─────────────
                grouped = browse_result.get("grouped_results", [])
                matched = _match_clusters(question, grouped)
                clusters_str = ", ".join(matched)

                # Build strategy from subtopic facets
                facets = browse_result.get("facets", {})
                subtopic_facets = facets.get("subtopics", [])
                if subtopic_facets:
                    top_subs = [f["value"] for f in subtopic_facets[:5]]
                    strategy = f"Browse-matched clusters. Top subtopics: {', '.join(top_subs)}"
                else:
                    strategy = f"Browse-matched {len(matched)} clusters in {category}"

            except Exception as e:
                _log.warning("Phase 2 browse failed, using category-only: %s", e)
                print(f"[classify] browse failed: {e}")
                strategy = "Browse unavailable — search broadly within category"

            # ── Assemble classification ─────────────────────────────────
            parsed: dict = {
                "raw": raw,
                "category": category,
                "clusters": clusters_str,
                "filters": {"parent_code": category},
                "strategy": strategy,
            }

            ctx.classification = parsed
            classify_ms = int((time.monotonic() - t0) * 1000)
            print(f"[classify] category={category} clusters={clusters_str!r} time={classify_ms}ms")
            tc.set_summary(
                {
                    "category": category,
                    "clusters": clusters_str,
                    "duration_ms": classify_ms,
                }
            )

            # Emit progress: classified
            if bus is not None:
                bus.emit(
                    "tool_progress",
                    {
                        "phase": "classified",
                        "message": f"Pre-classified in {classify_ms}ms",
                        "duration_ms": classify_ms,
                        "classification": parsed,
                    },
                )
            elif ctx._parent_logger is not None:
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
            if bus is not None:
                bus.emit(
                    "tool_progress",
                    {
                        "phase": "classified",
                        "message": f"Classification skipped ({classify_ms}ms)",
                        "duration_ms": classify_ms,
                    },
                )
            elif ctx._parent_logger is not None:
                ctx._parent_logger.emit_progress(
                    "classified",
                    f"Classification skipped ({classify_ms}ms)",
                    duration_ms=classify_ms,
                )
