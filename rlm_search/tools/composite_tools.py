"""Composite tools: research(), draft_answer() — orchestrate lower-level tools."""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from rlm_search.prompts import DOMAIN_PREAMBLE
from rlm_search.tools.api_tools import search, search_multi
from rlm_search.tools.format_tools import build_must_cite_brief, format_evidence
from rlm_search.tools.subagent_tools import (
    COSMETIC_DIMENSIONS,
    critique_answer,
    evaluate_results,
)
from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def _verify_citations(draft: str, evidence_ids: set[str]) -> dict:
    """Programmatic citation audit — instant, deterministic.

    Checks [Source: N] markers against known evidence IDs.

    Returns:
        Dict with cited (set), fabricated (set), uncited (set),
        valid (bool — no fabricated IDs), coverage (float 0-1).
    """
    cited = set(re.findall(r'\[Source:\s*(\d+)\]', draft))
    fabricated = cited - evidence_ids
    uncited = evidence_ids - cited
    coverage = len(cited & evidence_ids) / len(evidence_ids) if evidence_ids else 1.0
    return {
        "cited": cited,
        "fabricated": fabricated,
        "uncited": uncited,
        "valid": len(fabricated) == 0,
        "coverage": round(coverage, 3),
    }


@contextlib.contextmanager
def _child_scope(ctx: Any, parent_idx: int | None) -> Generator:
    """Exception-safe parent index scoping — replaces manual save/restore."""
    saved = ctx.current_parent_idx
    ctx.current_parent_idx = parent_idx
    try:
        yield
    finally:
        ctx.current_parent_idx = saved


def _incremental_evaluate(
    ctx: ToolContext,
    all_results: list,
    eval_question: str,
    eval_model: str | None,
) -> dict:
    """Dedup, register hits, evaluate new results, persist ratings. Called at checkpoints.

    Registers results in EvidenceStore so QualityGate.confidence sees them
    (top_score for quality factor, registry for top_rated()). This is needed
    because mocked search() bypasses normalize_hit() which normally does this.

    Returns:
        Dict with ``deduped`` (list), ``new_count`` (int), ``eval_summary`` (str).
        Updates ``ctx.evaluated_ratings`` and ``ctx.evidence`` as side effects.
    """
    # Dedup by ID, keep highest score
    seen: dict = {}
    for r in all_results:
        rid = str(r["id"])
        if rid not in seen or r["score"] > seen[rid]["score"]:
            seen[rid] = r
    deduped = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    # Register hits in EvidenceStore (idempotent — higher score wins)
    for r in deduped:
        ctx.evidence.register_hit(r)

    # Separate new vs already-rated
    new_results = [
        r
        for r in deduped
        if str(r["id"]) not in ctx.evaluated_ratings
        or ctx.evaluated_ratings[str(r["id"])] == "OFF-TOPIC"
    ]

    eval_summary = ""
    if new_results:
        try:
            eval_out = evaluate_results(
                ctx, eval_question, new_results[:15], top_n=15, model=eval_model
            )
            for rt in eval_out["ratings"]:
                ctx.evaluated_ratings[rt["id"]] = rt["rating"]
            eval_summary = eval_out.get("suggestion", "")
        except Exception as e:
            print(f"[research] WARNING: checkpoint evaluation failed: {e}")

    return {
        "deduped": deduped,
        "new_count": len(new_results),
        "eval_summary": eval_summary,
    }


def research(
    ctx: ToolContext,
    query: str | list,
    filters: dict | None = None,
    top_k: int = 10,
    extra_queries: list | None = None,
    eval_model: str | None = None,
) -> dict:
    """Search, evaluate relevance, and deduplicate — all in one call.

    Args:
        ctx: Per-session tool context.
        query: Natural language string OR a list of search specs.
        filters: Optional filter dict (string-query mode only).
        top_k: Results per search call (default 10).
        extra_queries: Optional list of extra search specs (string-query mode only).
        eval_model: Model for the relevance evaluation sub-call.

    Returns:
        Dict with ``results``, ``ratings``, ``search_count``, ``eval_summary``.
    """
    # Normalize: list-of-specs OR single query -> unified search task list
    if isinstance(query, list):
        if not query:
            print("[research] WARNING: empty query list")
            return {
                "results": [],
                "ratings": {},
                "search_count": 0,
                "eval_summary": "no queries provided",
            }

    with tool_call_tracker(
        ctx,
        "research",
        {
            "query": query if isinstance(query, str) else f"{len(query)} specs",
            "top_k": top_k,
        },
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        with _child_scope(ctx, tc.idx):
            all_results: list = []
            search_count = 0
            errors: list[str] = []

            if isinstance(query, list):
                specs = query
                eval_question = " ; ".join(s["query"] for s in specs)
            else:
                specs = [
                    {
                        "query": query,
                        "filters": filters,
                        "top_k": top_k,
                        "extra_queries": extra_queries,
                    }
                ]
                eval_question = query

            is_w3 = ctx.pipeline_mode == "w3"

            for spec in specs:
                q = spec["query"]
                f = spec.get("filters")
                k = spec.get("top_k", top_k)
                try:
                    if is_w3:
                        r = search_multi(ctx, q, final_top_k=k)
                    else:
                        r = search(ctx, q, filters=f, top_k=k)
                    all_results.extend(r["results"])
                    search_count += 1
                except Exception as e:
                    errors.append(str(e))
                    print(f"[research] WARNING: search failed: {e}")
                for eq in spec.get("extra_queries") or []:
                    try:
                        if is_w3:
                            r = search_multi(ctx, eq["query"], final_top_k=eq.get("top_k", k))
                        else:
                            r = search(
                                ctx,
                                eq["query"],
                                filters=eq.get("filters"),
                                top_k=eq.get("top_k", k),
                            )
                        all_results.extend(r["results"])
                        search_count += 1
                    except Exception as e:
                        errors.append(str(e))
                        print(f"[research] WARNING: search failed: {e}")

            if not all_results:
                print("[research] ERROR: all searches failed")
                tc.set_summary(
                    {
                        "search_count": search_count,
                        "raw": 0,
                        "unique": 0,
                        "filtered": 0,
                        "eval_summary": "no results",
                    }
                )
                return {
                    "results": [],
                    "ratings": {},
                    "search_count": search_count,
                    "eval_summary": "no results",
                }

            # Deduplicate by ID, keep highest score
            seen: dict = {}
            for r in all_results:
                rid = r["id"]
                if rid not in seen or r["score"] > seen[rid]["score"]:
                    seen[rid] = r
            deduped = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

            # Separate new vs already-rated results (cross-call dedup)
            # Re-evaluate prior OFF-TOPIC results — may be relevant under a different query
            new_results = [
                r
                for r in deduped
                if r["id"] not in ctx.evaluated_ratings
                or ctx.evaluated_ratings[r["id"]] == "OFF-TOPIC"
            ]
            prior_rated = {rid for rid in ctx.evaluated_ratings if rid in seen}

            # Evaluate ONLY new results — carry forward prior ratings
            ratings_map: dict = dict(ctx.evaluated_ratings)  # start with prior ratings
            if new_results:
                try:
                    eval_out = evaluate_results(
                        ctx, eval_question, new_results[:15], top_n=15, model=eval_model
                    )
                    for rt in eval_out["ratings"]:
                        ratings_map[rt["id"]] = rt["rating"]
                        ctx.evaluated_ratings[rt["id"]] = rt["rating"]  # persist
                except Exception as e:
                    print(f"[research] WARNING: evaluation failed, returning unrated: {e}")
            elif prior_rated:
                print(f"[research] all {len(deduped)} results already rated — skipping evaluation")

            # Filter OFF-TOPIC
            filtered = [r for r in deduped if ratings_map.get(r["id"], "UNRATED") != "OFF-TOPIC"]

            relevant = sum(1 for rid, v in ratings_map.items() if rid in seen and v == "RELEVANT")
            partial = sum(1 for rid, v in ratings_map.items() if rid in seen and v == "PARTIAL")
            off_topic = sum(1 for rid, v in ratings_map.items() if rid in seen and v == "OFF-TOPIC")
            summary = f"{relevant} relevant, {partial} partial, {off_topic} off-topic"
            if new_results and prior_rated:
                summary += f" ({len(new_results)} new, {len(prior_rated)} prior)"

            print(
                f"[research] {search_count} searches | {len(all_results)} raw"
                f" > {len(deduped)} unique > {len(filtered)} filtered"
            )
            print(f"[research] {summary}")
            for r in filtered[:5]:
                tag = ratings_map.get(r["id"], "-")
                print(f"  [{r['id']}] {r['score']:.2f} {tag:10s} Q: {r['question'][:100]}")
            if len(filtered) > 5:
                print(f"  ... and {len(filtered) - 5} more")

            tc.set_summary(
                {
                    "search_count": search_count,
                    "raw": len(all_results),
                    "unique": len(deduped),
                    "new_evaluated": len(new_results),
                    "prior_rated": len(prior_rated),
                    "filtered": len(filtered),
                    "eval_summary": summary,
                }
            )

            result: dict = {
                "results": filtered,
                "ratings": ratings_map,
                "search_count": search_count,
                "eval_summary": summary,
            }
            if errors:
                result["errors"] = errors
            return result


def draft_answer(
    ctx: ToolContext,
    question: str,
    results: list,
    instructions: str | None = None,
    model: str | None = None,
) -> dict:
    """Synthesize an answer from results, with tiered critique based on evidence quality.

    QualityGate determines critique depth:
      strong (6+ RELEVANT, conf >= 75%): programmatic citation check only
      medium (3+ RELEVANT): focused LLM critique (voice + attribution), no revision
      weak  (<3 RELEVANT): full critique + revision loop (original behavior)

    Uses top_rated() evidence when QualityGate is available — RELEVANT sources first,
    OFF-TOPIC excluded. Falls back to results[:20] when QualityGate is absent.
    """
    if len(ctx.evidence.search_log) == 0:
        print("[draft_answer] WARNING: No research() calls made. Results may be ungrounded.")

    # ── Evidence selection: prefer top_rated (RELEVANT first, no OFF-TOPIC) ──
    quality = getattr(ctx, "quality", None)
    if quality is not None and ctx.evidence.count > 0:
        best = ctx.evidence.top_rated(20)
        if best:
            results_for_evidence = best
        else:
            results_for_evidence = results[:20]
    else:
        results_for_evidence = results[:20]

    # Use rating-aware evidence ordering when ratings are available
    ratings = ctx.evidence.ratings or None
    evidence = format_evidence(results_for_evidence, ratings=ratings)
    if not evidence:
        print("[draft_answer] ERROR: no evidence to synthesize from")
        return {"answer": "", "critique": "", "passed": False, "revised": False}

    # Build must-cite brief from ratings (zero LLM cost)
    must_cite = ""
    if ratings:
        must_cite = build_must_cite_brief(results_for_evidence, ratings)

    with tool_call_tracker(
        ctx,
        "draft_answer",
        {"question": question[:100], "num_results": len(results)},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        with _child_scope(ctx, tc.idx):
            bus = getattr(ctx, "bus", None)

            # ── Determine critique tier ──
            tier = "weak"  # default
            if quality is not None:
                tier = quality.critique_tier
            print(f"[draft_answer] critique_tier={tier}")

            # ── Phase 1: Synthesis (all tiers) ──
            t0 = time.time()

            prompt_parts = [
                DOMAIN_PREAMBLE,
                "Synthesize a comprehensive, well-structured answer from the "
                "evidence below.\n\n",
            ]

            # Inject must-cite brief before evidence
            if must_cite:
                prompt_parts.append(must_cite)

            prompt_parts.extend([
                "VOICE & TONE:\n"
                "- Write as the voice of the I.M.A.M. scholarly corpus — presenting "
                "the assembled guidance of qualified Ja'fari scholars. Frame answers "
                "as 'I.M.A.M. scholars have addressed this:' or 'According to the "
                "I.M.A.M. corpus...' — not as your own analysis.\n"
                "- State rulings declaratively: 'The ruling is...' not 'It would seem "
                "that...' or 'It may be that...'. Confidence uncertainty belongs in "
                "## Confidence Assessment — keep the answer body authoritative.\n"
                "- Use clear language accessible to English-speaking Muslims. "
                "Define Arabic/fiqhi terms parenthetically on first use "
                "(e.g., 'riba (usury/interest)'). Do not define terms the user "
                "already used correctly in their question.\n"
                "- Present rulings as stated in the sources — do not add external "
                "positions or comparative fiqh unless the sources themselves "
                "raise them.\n"
                "- Do not open with preamble ('This is an important question', "
                "'Islam addresses...'). Start directly with the ruling.\n\n"
                "LENGTH:\n"
                "- Single ruling question: 150-250 words.\n"
                "- Ruling with conditions or exceptions: 300-450 words.\n"
                "- Multi-part or complex fiqhi question: up to 600 words. Extend "
                "beyond 600 only when distinct conditions from different sources "
                "would otherwise be omitted — never to add summaries.\n"
                "- Never pad with summary paragraphs that restate the opening ruling.\n\n"
                "STRUCTURE:\n"
                "- Lead with the direct ruling or answer.\n"
                "- Follow with conditions, exceptions, and practical guidance "
                "from the sources.\n"
                "- When multiple sources agree, state the consensus once with "
                "all citations.\n"
                "- When sources present different conditions or caveats, organize "
                "by condition.\n\n",
                f"QUESTION:\n{question}\n\n",
                "EVIDENCE:\n" + "\n".join(evidence) + "\n\n",
            ])
            if instructions:
                prompt_parts.append(f"INSTRUCTIONS:\n{instructions}\n\n")
            prompt_parts.append(
                "FORMAT:\n"
                "## Answer\n"
                "Grounded answer with [Source: <id>] citations after each claim.\n\n"
                "## Sources Consulted\n"
                "One line per source cited: [Source: id] — [original question topic "
                "in 5-8 words]. No paraphrase of rulings — the ruling is already in "
                "## Answer.\n\n"
                "## Confidence Assessment\n"
                "- **High**: 3+ scholar answers consistently agree on the ruling.\n"
                "- **Medium**: 1-2 sources directly address the question.\n"
                "- **Low**: No direct match found; answer extrapolated from "
                "related rulings.\n"
                "Note which aspects of the question have direct corpus coverage "
                "vs. which required extrapolation from related rulings.\n\n"
                "Only cite IDs from the evidence. Flag gaps explicitly — say "
                "'the I.M.A.M. corpus does not directly address this specific "
                "aspect' rather than guessing.\n"
            )

            answer = ctx.llm_query("".join(prompt_parts), model=model)
            synth_ms = int((time.time() - t0) * 1000)

            # Emit: synthesis complete
            if bus is not None:
                bus.emit("tool_progress", {
                    "tool": "draft_answer",
                    "phase": "synthesized",
                    "data": {"answer_length": len(answer), "tier": tier},
                    "duration_ms": synth_ms,
                })

            # ── Phase 2: Critique (tier-dependent) ──
            t1 = time.time()
            evidence_ids = {str(r.get("id", "")) for r in results_for_evidence}
            citation_result = _verify_citations(answer, evidence_ids)
            critique_text = ""
            passed = True
            revised = False
            dimensions: dict[str, dict[str, str]] = {}

            if tier == "strong":
                # Programmatic citation check only
                passed = citation_result["valid"]
                if not passed:
                    critique_text = (
                        f"Fabricated citations: {citation_result['fabricated']}. "
                        f"Fall through to focused critique."
                    )
                    # Fall through to medium-tier critique
                    tier = "medium"
                else:
                    critique_text = (
                        f"Citations valid ({len(citation_result['cited'])} cited, "
                        f"coverage={citation_result['coverage']}). "
                        f"Programmatic check passed — LLM critique skipped."
                    )
                    print(f"[draft_answer] STRONG: citation check PASS "
                          f"({len(citation_result['cited'])} cited, "
                          f"coverage={citation_result['coverage']})")

            if tier == "medium":
                # Focused LLM critique — voice + attribution only, no revision loop
                critique_text, passed, dimensions = critique_answer(
                    ctx, question, answer, evidence=evidence, model=model,
                    focus="voice_attribution",
                )
                print(f"[draft_answer] MEDIUM: focused critique "
                      f"{'PASS' if passed else 'FAIL'}")

            elif tier == "weak":
                # Full critique + revision loop (original behavior)
                critique_text, passed, dimensions = critique_answer(
                    ctx, question, answer, evidence=evidence, model=model,
                )

                if not passed:
                    # Determine failed dimensions for targeted revision
                    failed_dims = {
                        k: v for k, v in dimensions.items() if v["verdict"] == "FAIL"
                    }
                    cosmetic_only = (
                        bool(failed_dims)
                        and all(k in COSMETIC_DIMENSIONS for k in failed_dims)
                    )

                    if cosmetic_only:
                        # Voice/structure issues only — targeted fix, no full re-synthesis
                        fix_details = "; ".join(
                            f"{k}: {v['detail']}" for k, v in failed_dims.items() if v["detail"]
                        )
                        rev_parts = [
                            DOMAIN_PREAMBLE,
                            "Fix ONLY the following voice/structure issues in this answer. "
                            "Do not change the substance, citations, or content.\n\n",
                            f"ISSUES:\n{fix_details}\n\n" if fix_details else "",
                            f"CRITIQUE:\n{critique_text}\n\n",
                            f"ORIGINAL:\n{answer}\n\n",
                            "Return ONLY the fixed answer. Start directly with ## Answer.\n",
                        ]
                    else:
                        # Substantive issues — build targeted revision prompt
                        completeness_detail = ""
                        if "COMPLETENESS" in failed_dims:
                            detail = failed_dims["COMPLETENESS"].get("detail", "")
                            if detail:
                                completeness_detail = (
                                    f"\nCRITICAL OMISSION:\n{detail}\n"
                                    "You MUST incorporate the above missing source(s) into "
                                    "the revised answer.\n\n"
                                )

                        rev_parts = [
                            DOMAIN_PREAMBLE,
                            "Revise this answer based on the critique.\n\n",
                            f"CRITIQUE:\n{critique_text}\n\n",
                            completeness_detail,
                            f"ORIGINAL:\n{answer}\n\n",
                            "EVIDENCE:\n" + "\n".join(evidence) + "\n\n",
                            "Fix flagged issues. Keep valid citations. Same format.\n"
                            "Maintain synthesis structure: lead with the ruling, keep consensus "
                            "sources merged (do not expand a unified statement into per-source "
                            "paragraphs).\n"
                            "VOICE (preserve throughout): state rulings declaratively "
                            "('The ruling is...' not 'It may be...'); frame as I.M.A.M. "
                            "scholarly corpus ('According to the I.M.A.M. corpus...'); "
                            "no first-person hedging ('I think', 'it seems'); "
                            "define Arabic/fiqhi terms parenthetically on first use "
                            "(e.g., 'riba (usury/interest)') if not already defined; "
                            "no introductory padding before the ruling.\n"
                            "Return ONLY the revised answer — no preamble, no explanation of"
                            " changes.\n"
                            "Do NOT say 'Here is the revised answer' or describe what you "
                            "changed.\n"
                            "Do NOT include revision notes, commentary, or meta-text.\n"
                            "Start directly with ## Answer.\n",
                        ]

                    answer = ctx.llm_query("".join(rev_parts), model=model)
                    critique_text, passed, dimensions = critique_answer(
                        ctx, question, answer, evidence=evidence, model=model
                    )
                    revised = True

            crit_ms = int((time.time() - t1) * 1000)

            # Emit: critique complete
            if bus is not None:
                bus.emit("tool_progress", {
                    "tool": "draft_answer",
                    "phase": "critiqued",
                    "data": {
                        "tier": tier,
                        "passed": passed,
                        "revised": revised,
                        "citation_check": {
                            "valid": citation_result["valid"],
                            "cited_count": len(citation_result["cited"]),
                            "coverage": citation_result["coverage"],
                        },
                    },
                    "duration_ms": crit_ms,
                })

            # Wire QualityGate — record draft + final critique outcome
            if quality is not None:
                quality.record_draft(len(answer))
                quality.record_critique(passed, critique_text)

            failed_dims_list = [
                k for k, v in dimensions.items() if v["verdict"] == "FAIL"
            ]
            total_ms = synth_ms + crit_ms
            print(
                f"[draft_answer] {'PASS' if passed else 'FAIL'}"
                f" tier={tier}"
                f"{' (revised)' if revised else ''}"
                f" | {len(answer)} chars | {len(evidence)} evidence entries"
                f" | {total_ms}ms"
            )
            if failed_dims_list:
                print(f"[draft_answer] failed dimensions: {', '.join(failed_dims_list)}")
            tc.set_summary(
                {
                    "passed": passed,
                    "revised": revised,
                    "tier": tier,
                    "answer_length": len(answer),
                    "answer_preview": answer,
                    "critique_verdict": "PASS" if passed else "FAIL",
                    "critique_reason": critique_text or "",
                    "citation_check": {
                        "valid": citation_result["valid"],
                        "cited_count": len(citation_result["cited"]),
                        "fabricated_count": len(citation_result["fabricated"]),
                        "coverage": citation_result["coverage"],
                    },
                    "dimensions": {k: v["verdict"] for k, v in dimensions.items()},
                }
            )
            return {
                "answer": answer,
                "critique": critique_text,
                "passed": passed,
                "revised": revised,
                "tier": tier,
                "dimensions": {k: v["verdict"] for k, v in dimensions.items()},
            }
