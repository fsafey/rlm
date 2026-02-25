"""Sub-agent tools: LLM-dependent evaluation, reformulation, critique, classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm.clients import get_client
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

        school_context = DOMAIN_PREAMBLE

        if evidence:
            evidence_block = "\n".join(evidence)
            prompt = (
                f"{school_context}"
                f"Review this draft answer against the provided evidence.\n\n"
                f"QUESTION:\n{question}\n\n"
                f"EVIDENCE:\n{evidence_block}\n\n"
                f"DRAFT:\n{draft}\n\n"
                f"Check these criteria:\n\n"
                f"1. CITATION ACCURACY — Every [Source: N] in the draft must map to "
                f"a real source in the evidence above. Flag any fabricated IDs.\n\n"
                f"2. ATTRIBUTION FIDELITY — Claims attributed to specific scholars, "
                f"texts, or rulings must actually appear in the cited source.\n\n"
                f"3. UNSUPPORTED CLAIMS — Flag substantive rulings or factual "
                f"claims that have no [Source: N] citation.\n\n"
                f"4. COMPLETENESS — All materially distinct rulings, conditions, and "
                f"caveats from high-relevance evidence should be represented. When "
                f"multiple sources agree on the same ruling, a single merged paragraph "
                f"with all citations is the correct synthesis — do not flag this as "
                f"incomplete. Flag only when a distinct condition, exception, or "
                f"directly-answering point from the evidence is absent.\n\n"
                f"5. SCHOLARLY VOICE — The answer should frame rulings as coming from "
                f"I.M.A.M. scholars (not as the AI's own opinion). Rulings stated "
                f"declaratively ('The ruling is...') not tentatively ('It may be...', "
                f"'It would seem...'). No first-person hedging ('I think', 'I believe', "
                f"'it seems'). Arabic terms defined on first use.\n\n"
                f"6. STRUCTURE — The answer leads with the direct ruling or main "
                f"conclusion. Flag if: (a) the ruling is buried after extensive background, "
                f"or (b) the answer opens with generic preamble ('This is an important "
                f"topic', 'Islam addresses...') that delays the ruling.\n\n"
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
                f"3. Is any materially distinct ruling, condition, or caveats missing? "
                f"(When multiple sources agree, a single merged paragraph is correct — "
                f"do not flag consensus synthesis as incomplete.)\n"
                f"4. Are [Source: N] citations present for factual claims?\n"
                f"5. SCHOLARLY VOICE — Does the answer frame rulings as coming from "
                f"I.M.A.M. scholars (not as the AI's own opinion)? Are rulings stated "
                f"declaratively ('The ruling is...') not tentatively ('It may be...', "
                f"'it seems')? No first-person hedging. Arabic terms defined on first use. "
                f"No introductory padding before the ruling.\n\n"
                f"Respond: PASS or FAIL, then brief feedback (under 150 words).\n"
                f"If ANY check fails, the overall verdict is FAIL."
            )

        verdict = ctx.llm_query(prompt, model=model)
        passed = verdict.strip().strip("*").upper().startswith("PASS")
        verdict_str = "PASS" if passed else "FAIL"
        failed_str = "" if passed else " (failed: evidence-grounded review)"
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
                "feedback": feedback[:200],
                # Backward compat for frontend CritiqueDetail renderer
                "reason": feedback[:200],
                "failed": [] if passed else ["evidence_review"],
            }
        )
        return verdict, passed


def _build_category_prompt(question: str, kb_overview_data: dict) -> str:
    """Build classification prompt: category + cluster selection in a single LLM call.

    Includes cluster labels and sample questions from kb_overview_data so the LLM
    can do semantic matching — replaces the old token-overlap approach.
    """
    cat_lines = []
    for code, cat in kb_overview_data.get("categories", {}).items():
        name = cat.get("name", code)
        doc_count = cat.get("document_count", 0)
        clusters = cat.get("clusters", {})  # {label: sample_question}
        line = f"{code} — {name} [{doc_count} docs]"
        if clusters:
            labels = list(clusters.keys())
            line += f"\n  Clusters: {', '.join(labels)}"
            # Include up to 3 sample questions for grounding
            samples = [(lbl, q) for lbl, q in clusters.items() if q][:3]
            for label, sample_q in samples:
                line += f'\n    "{sample_q}" → {label}'
        cat_lines.append(line)
    cat_info = "\n".join(cat_lines)

    return (
        "Classify this Islamic Q&A question into one category and select "
        "the most relevant clusters within that category.\n\n"
        f'Question: "{question}"\n\n'
        f"Categories and their clusters:\n{cat_info}\n\n"
        "Respond with exactly three lines:\n"
        "CATEGORY: <code>\n"
        "CONFIDENCE: HIGH|MEDIUM|LOW\n"
        "CLUSTERS: <comma-separated cluster labels from the chosen category, up to 5>\n\n"
        "CATEGORY guidance:\n"
        "- HIGH: question clearly belongs to one category\n"
        "- MEDIUM: one category fits but another is plausible\n"
        "- LOW: question spans two categories equally or is genuinely ambiguous\n\n"
        "CLUSTERS guidance:\n"
        "- Select clusters whose topic covers the question, even if wording differs\n"
        "- Use NONE if no clusters are relevant\n"
        "- Prefer fewer, more precise clusters over many vague ones\n"
    )


def init_classify(
    ctx: ToolContext,
    question: str,
    model: str = "",
) -> None:
    """Pre-classify query via single LLM call (zero iteration cost).

    One Sonnet call outputs category + clusters using semantic matching.
    Cluster labels are validated against kb_overview_data to reject hallucinations.

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

            # Parse category, confidence, and clusters from response
            category = ""
            confidence = "HIGH"  # default if model omits
            llm_clusters: list[str] = []
            for line in raw.strip().split("\n"):
                line_s = line.strip()
                if line_s.upper().startswith("CATEGORY:"):
                    category = line_s.split(":", 1)[1].strip().upper()
                elif line_s.upper().startswith("CONFIDENCE:"):
                    raw_conf = line_s.split(":", 1)[1].strip().upper()
                    if raw_conf in ("HIGH", "MEDIUM", "LOW"):
                        confidence = raw_conf
                elif line_s.upper().startswith("CLUSTERS:"):
                    raw_clusters = line_s.split(":", 1)[1].strip()
                    if raw_clusters.upper() != "NONE":
                        llm_clusters = [c.strip() for c in raw_clusters.split(",") if c.strip()]

            if not category:
                _log.warning("LLM returned no category, raw=%r", raw[:200])
                ctx.classification = None
                classify_ms = int((time.monotonic() - t0) * 1000)
                tc.set_summary({"error": "no category parsed", "duration_ms": classify_ms})
                return

            # ── Validate clusters against known labels ──────────────────
            cat_data = ctx.kb_overview_data["categories"].get(category, {})
            known_clusters = set(cat_data.get("clusters", {}).keys())
            validated = [c for c in llm_clusters if c in known_clusters]
            cluster_matched = len(validated) > 0
            clusters_str = ", ".join(validated)

            # ── Build confidence-aware strategy ─────────────────────────
            subtopic_facets = cat_data.get("facets", {}).get("subtopics", [])
            top_subs = [f["value"] for f in subtopic_facets[:5]] if subtopic_facets else []

            if confidence == "LOW":
                strategy = (
                    "Low category confidence — start with broad search (no filters). "
                    "Add category filter only if initial results confirm this category."
                )
            elif not cluster_matched:
                sub_hint = f" Top subtopics: {', '.join(top_subs)}." if top_subs else ""
                strategy = (
                    f"Category match confident ({category}), but no cluster match — "
                    f"filter by category only, skip cluster filter.{sub_hint}"
                )
            else:
                sub_hint = f" Top subtopics: {', '.join(top_subs)}." if top_subs else ""
                strategy = (
                    f"Strong match — {clusters_str} in {category}."
                    f" Use category + cluster filters for first search.{sub_hint}"
                )

            # ── Assemble classification ─────────────────────────────────
            parsed: dict = {
                "raw": raw,
                "category": category,
                "confidence": confidence,
                "clusters": clusters_str,
                "filters": {"parent_code": category},
                "strategy": strategy,
            }

            ctx.classification = parsed
            classify_ms = int((time.monotonic() - t0) * 1000)
            print(
                f"[classify] category={category} confidence={confidence} "
                f"clusters={clusters_str!r} time={classify_ms}ms"
            )
            tc.set_summary(
                {
                    "category": category,
                    "confidence": confidence,
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
