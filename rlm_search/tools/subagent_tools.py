"""Sub-agent tools: LLM-dependent evaluation, reformulation, critique, classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.prompts import DOMAIN_PREAMBLE
from rlm_search.tools.constants import MAX_DRAFT_LEN
from rlm_search.tools.tracker import tool_call_tracker

# Domain-aware relevance bridge — shared by batch and fallback evaluation paths
_EVAL_DOMAIN_BRIDGE = (
    "When evaluating relevance, consider that:\n"
    "- Arabic terms and English equivalents are interchangeable "
    "(e.g., 'ghusl' = 'ritual bath', 'riba' = 'interest/usury', "
    "'nikah' = 'marriage contract', 'sawm' = 'fasting')\n"
    "- A result addressing the underlying fiqhi principle is RELEVANT "
    "even if the specific scenario or terminology differs\n"
    "- Results from the same school of thought (Ja'fari) addressing "
    "related conditions or exceptions are at minimum PARTIAL\n\n"
)

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
            DOMAIN_PREAMBLE
            + _EVAL_DOMAIN_BRIDGE
            + f"Evaluate these search results for relevance to the question:\n"
            f'"{question}"\n\n' + "\n\n".join(result_blocks) + "\n\n"
            f"For each result, respond with exactly one line:\n"
            f"[<id>] RELEVANT|PARTIAL|OFF-TOPIC CONFIDENCE:<1-5>\n\n"
            f"RELEVANT = the ruling or evidence applies to the question — even if using "
            f"different terminology, the same concept framed differently, or the underlying "
            f"fiqhi principle rather than the exact scenario asked\n"
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
                    DOMAIN_PREAMBLE
                    + _EVAL_DOMAIN_BRIDGE
                    + f"Evaluate this search result for the question:\n"
                    f'"{question}"\n\n'
                    f"Result [{rid}] score={score:.2f}\n"
                    f"Q: {q}\nA: {a}\n\n"
                    f"Respond with exactly one line: RELEVANT|PARTIAL|OFF-TOPIC followed by CONFIDENCE:<1-5>\n"
                    f"RELEVANT = the ruling or evidence applies to the question — even if using "
                    f"different terminology, the same concept framed differently, or the underlying "
                    f"fiqhi principle rather than the exact scenario asked\n"
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
            DOMAIN_PREAMBLE + "The corpus is Islamic Q&A following Ja'fari fiqh. "
            "Key terminology by domain:\n"
            "- Prayer & Purification: salah, wudhu, ghusl, najis, tahir, tayammum, qibla\n"
            "- Worship: sawm, zakat, khums, hajj, kaffara, nadhr, itikaf\n"
            "- Marriage & Family: nikah, mutah, talaq, mahr, nafaqa, iddah, mehrieh\n"
            "- Finance: riba, bay', halal earnings, haram income, gharar, khums, tawbah mal\n"
            "- Beliefs & Ethics: shirk, tawbah, wajib, haram, makruh, mustahab, mubah\n\n"
            f'The search query "{failed_query}" returned poor results '
            f"(best score: {top_score:.2f}) for the question:\n"
            f'"{question}"\n\n'
            f"Generate exactly 3 alternative search queries, each from a different angle:\n"
            f"1. Use the Arabic or Ja'fari fiqh terminology for the concept\n"
            f"2. Name the underlying Islamic ruling or principle being asked about\n"
            f"3. Rephrase as a different scenario that would have the same Islamic answer\n\n"
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


# Critique dimension keys — used for structured parsing
_CRITIQUE_DIMENSIONS = [
    "CITATION_ACCURACY",
    "ATTRIBUTION_FIDELITY",
    "UNSUPPORTED_CLAIMS",
    "COMPLETENESS",
    "SCHOLARLY_VOICE",
    "STRUCTURE",
]

# Dimensions that can be fixed without a full LLM revision
COSMETIC_DIMENSIONS = {"SCHOLARLY_VOICE", "STRUCTURE"}


def _parse_critique_dimensions(verdict: str) -> dict[str, dict[str, str]]:
    """Parse structured critique output into per-dimension results.

    Expected format from LLM:
        CITATION_ACCURACY: PASS
        ATTRIBUTION_FIDELITY: PASS
        COMPLETENESS: FAIL — [Source: 9253] states condition X
        ...
        VERDICT: FAIL

    Returns:
        Dict mapping dimension name to {"verdict": "PASS"|"FAIL", "detail": "..."}.
        Returns empty dict if parsing fails (LLM didn't follow format).
    """
    dims: dict[str, dict[str, str]] = {}
    for line in verdict.split("\n"):
        line = line.strip().strip("*").strip()
        if not line or line.startswith("VERDICT"):
            continue
        for dim in _CRITIQUE_DIMENSIONS:
            if line.upper().startswith(dim):
                rest = line[len(dim) :].strip().lstrip(":").strip()
                if rest.upper().startswith("PASS"):
                    detail = rest[4:].strip().lstrip("—-").strip()
                    dims[dim] = {"verdict": "PASS", "detail": detail}
                elif rest.upper().startswith("FAIL"):
                    detail = rest[4:].strip().lstrip("—-").strip()
                    dims[dim] = {"verdict": "FAIL", "detail": detail}
                break
    return dims


def critique_answer(
    ctx: ToolContext,
    question: str,
    draft: str,
    evidence: list[str] | None = None,
    model: str | None = None,
    focus: str | None = None,
) -> tuple[str, bool, dict[str, dict[str, str]]]:
    """Evidence-grounded critique: cross-check draft citations against sources.

    When evidence is provided, checks citation accuracy, attribution fidelity,
    unsupported claims, and completeness against actual sources. When evidence
    is omitted but ``ctx.source_registry`` has accumulated results, auto-builds
    evidence from the session state so the critique is still grounded.

    Returns:
        Tuple of (verdict_text, passed, dimensions).
        ``dimensions`` maps dimension name to {"verdict": "PASS"|"FAIL", "detail": "..."}.
        Empty dict if structured parsing failed.
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

        school_context = DOMAIN_PREAMBLE

        if evidence:
            evidence_block = "\n".join(evidence)

            if focus == "voice_attribution":
                # MEDIUM tier: only check criteria that require LLM judgment.
                # Citation accuracy and completeness are handled programmatically.
                prompt = (
                    f"{school_context}"
                    f"Review this draft answer for voice and attribution quality only.\n\n"
                    f"QUESTION:\n{question}\n\n"
                    f"EVIDENCE:\n{evidence_block}\n\n"
                    f"DRAFT:\n{draft}\n\n"
                    f"Check these criteria ONLY:\n\n"
                    f"1. ATTRIBUTION FIDELITY — Claims attributed to specific scholars, "
                    f"texts, or rulings must actually appear in the cited source.\n\n"
                    f"2. SCHOLARLY VOICE — The answer should frame rulings as coming from "
                    f"I.M.A.M. scholars (not as the AI's own opinion). Rulings stated "
                    f"declaratively ('The ruling is...') not tentatively ('It may be...', "
                    f"'It would seem...'). No first-person hedging ('I think', 'I believe', "
                    f"'it seems'). Arabic terms defined on first use.\n\n"
                    f"3. STRUCTURE — The answer leads with the direct ruling or main "
                    f"conclusion. Flag if the ruling is buried or opens with preamble.\n\n"
                    f"Do NOT check citation accuracy or completeness — those are verified "
                    f"programmatically. Focus ONLY on the 3 criteria above.\n\n"
                    f"Respond: PASS or FAIL, then brief feedback (under 100 words).\n"
                    f"If ANY check fails, the overall verdict is FAIL."
                )
            else:
                # Original full prompt (WEAK tier and default)
                prompt = (
                    f"{school_context}"
                    f"Review this draft answer against the provided evidence.\n\n"
                    f"QUESTION:\n{question}\n\n"
                    f"EVIDENCE:\n{evidence_block}\n\n"
                    f"DRAFT:\n{draft}\n\n"
                    f"Evaluate each dimension. For each, output exactly one line:\n"
                    f"DIMENSION_NAME: PASS or FAIL — brief reason (under 25 words)\n\n"
                    f"Dimensions:\n\n"
                    f"CITATION_ACCURACY: Every [Source: N] in the draft maps to a real "
                    f"source in the evidence. Flag fabricated IDs.\n\n"
                    f"ATTRIBUTION_FIDELITY: Claims attributed to scholars, texts, or "
                    f"rulings actually appear in the cited source.\n\n"
                    f"UNSUPPORTED_CLAIMS: No substantive rulings or factual claims "
                    f"lack a [Source: N] citation.\n\n"
                    f"COMPLETENESS: All materially distinct rulings, conditions, and "
                    f"caveats from RELEVANT evidence are represented. Consensus "
                    f"synthesis (single merged paragraph with all citations) is correct "
                    f"— not incomplete. Flag only when a distinct condition, exception, "
                    f"or directly-answering point from RELEVANT evidence is absent. "
                    f"Name the specific source ID(s) omitted.\n\n"
                    f"SCHOLARLY_VOICE: Rulings framed as I.M.A.M. scholars (not AI "
                    f"opinion). Declarative tone ('The ruling is...' not 'It may "
                    f"be...'). No first-person hedging. Arabic terms defined on first "
                    f"use.\n\n"
                    f"STRUCTURE: Answer leads with the direct ruling. No generic "
                    f"preamble delaying the ruling.\n\n"
                    f"After all dimensions, output:\n"
                    f"VERDICT: PASS (if all dimensions pass) or FAIL\n"
                    f"Then one line summarizing the key issue (under 30 words).\n"
                )
        else:
            prompt = (
                f"{school_context}"
                f"Review this draft answer to the question:\n"
                f'"{question}"\n\n'
                f"Draft:\n{draft}\n\n"
                f"Evaluate each dimension. For each, output exactly one line:\n"
                f"DIMENSION_NAME: PASS or FAIL — brief reason (under 25 words)\n\n"
                f"CITATION_ACCURACY: [Source: N] citations present and plausible.\n"
                f"ATTRIBUTION_FIDELITY: Claims match cited sources.\n"
                f"UNSUPPORTED_CLAIMS: No uncited substantive claims.\n"
                f"COMPLETENESS: Question fully addressed, no major gaps.\n"
                f"SCHOLARLY_VOICE: I.M.A.M. framing, declarative tone, no hedging.\n"
                f"STRUCTURE: Leads with ruling, no preamble padding.\n\n"
                f"After all dimensions, output:\n"
                f"VERDICT: PASS (if all dimensions pass) or FAIL\n"
                f"Then one line summarizing the key issue (under 30 words).\n"
            )

        verdict = ctx.llm_query(prompt, model=model)
        dimensions = _parse_critique_dimensions(verdict)

        # Determine pass/fail from structured output if sufficient dimensions parsed,
        # otherwise fall back to scanning for PASS/FAIL at start of verdict text.
        # Require at least 4 of 6 dimensions to trust structured output.
        if len(dimensions) >= 4:
            passed = all(d["verdict"] == "PASS" for d in dimensions.values())
        else:
            passed = verdict.strip().strip("*").upper().startswith("PASS")

        verdict_str = "PASS" if passed else "FAIL"
        failed_dims = [k for k, v in dimensions.items() if v["verdict"] == "FAIL"]
        failed_str = ""
        if not passed:
            if failed_dims:
                failed_str = f" (failed: {', '.join(failed_dims)})"
            else:
                failed_str = " (failed: evidence-grounded review)"
        print(f"[critique_answer] verdict={verdict_str}{failed_str}")
        feedback = verdict.split("\n", 1)[1].strip() if "\n" in verdict else ""

        # Wire QualityGate — record standalone critique outcome
        quality = getattr(ctx, "quality", None)
        if quality is not None:
            quality.record_critique(passed, verdict)

        tc.set_summary(
            {
                "verdict": verdict_str,
                "has_evidence": bool(evidence),
                "feedback": feedback,
                # Backward compat for frontend CritiqueDetail renderer
                "reason": feedback,
                "failed": failed_dims if failed_dims else ([] if passed else ["evidence_review"]),
                "dimensions": {k: v["verdict"] for k, v in dimensions.items()},
            }
        )
        return verdict, passed, dimensions
