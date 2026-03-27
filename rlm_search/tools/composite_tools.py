"""Composite tools: research(), draft_answer() — orchestrate lower-level tools."""

from __future__ import annotations

import contextlib
import re
import time
from collections import Counter
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from rlm_search.prompt_constants import (
    EVAL_CHECKPOINT_SEARCH,
    EXPLORE_EXTRA_BUDGET,
    MEDIUM_EXTRA_BUDGET,
    SATURATION_CONSECUTIVE_MAX,
    SATURATION_LOW_YIELD,
)
from rlm_search.prompts import DOMAIN_PREAMBLE
from rlm_search.tools.api_tools import search, search_multi
from rlm_search.tools.format_tools import build_must_cite_brief, format_evidence
from rlm_search.tools.subagent_tools import (
    COSMETIC_DIMENSIONS,
    critique_answer,
    evaluate_results,
)
from rlm_search.tools.tracker import _emit, tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


def _verify_citations(draft: str, evidence_ids: set[str]) -> dict:
    """Programmatic citation audit — instant, deterministic.

    Checks [Source: N] markers against known evidence IDs.

    Returns:
        Dict with cited (set), fabricated (set), uncited (set),
        valid (bool — no fabricated IDs), coverage (float 0-1).
    """
    cited = set(re.findall(r"\[Source:\s*(\d+)\]", draft))
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
    _offset: int = 0,
) -> dict:
    """Register new hits, evaluate unrated results, persist ratings. Called at checkpoints.

    Only processes ``all_results[_offset:]`` for registration — previous items
    were handled by an earlier checkpoint. Dedup for the return value still
    covers the full list (needed for final OFF-TOPIC filtering).

    Returns:
        Dict with ``deduped`` (list), ``new_count`` (int), ``eval_summary`` (str),
        ``processed_to`` (int — pass as ``_offset`` to next call).
        Updates ``ctx.evaluated_ratings`` and ``ctx.evidence`` as side effects.
    """
    # Register only NEW hits since last checkpoint (idempotent — higher score wins)
    for r in all_results[_offset:]:
        ctx.evidence.register_hit(r)

    # Full dedup for return value (needed by post-loop filtering)
    seen: dict = {}
    for r in all_results:
        rid = str(r["id"])
        if rid not in seen or r["score"] > seen[rid]["score"]:
            seen[rid] = r
    deduped = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    # Evaluate only unrated (or previously OFF-TOPIC) results
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
        "processed_to": len(all_results),
    }


def _extract_classification(results: list[dict]) -> dict:
    """Compute classification from search result metadata via majority vote.

    Pure function — no LLM calls, no side effects (~5ms).

    Args:
        results: Search results, each with ``result["metadata"]["parent_code"]``
                 and ``result["metadata"]["cluster_label"]``.

    Returns:
        Classification dict with category, confidence, clusters, filters,
        strategy, query_variants, and also_category.
    """
    if not results:
        return {
            "category": "",
            "confidence": "LOW",
            "clusters": "",
            "filters": {},
            "strategy": "No results to classify.",
            "query_variants": [],
            "also_category": "",
        }

    # 1. Count parent_code distribution
    parent_counts: Counter[str] = Counter()
    for r in results:
        pc = r.get("metadata", {}).get("parent_code", "")
        if pc:
            parent_counts[pc] += 1

    if not parent_counts:
        return {
            "category": "",
            "confidence": "LOW",
            "clusters": "",
            "filters": {},
            "strategy": "No parent_code metadata found.",
            "query_variants": [],
            "also_category": "",
        }

    # 2. Majority vote
    category, dominant_count = parent_counts.most_common(1)[0]
    total = sum(parent_counts.values())
    concentration = dominant_count / total if total > 0 else 0.0
    max_score = max((r.get("score", 0.0) for r in results), default=0.0)

    # 3. Confidence level
    if concentration >= 0.70 and max_score > 0.5:
        confidence = "HIGH"
    elif concentration >= 0.50 or max_score > 0.3:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # 4. Top 3 cluster_label values from dominant category
    cluster_counts: Counter[str] = Counter()
    for r in results:
        md = r.get("metadata", {})
        if md.get("parent_code") == category:
            cl = md.get("cluster_label", "")
            if cl:
                cluster_counts[cl] += 1
    top_clusters = [label for label, _ in cluster_counts.most_common(3)]
    clusters_str = ", ".join(top_clusters)
    top_cluster = top_clusters[0] if top_clusters else category

    # 5. Runner-up
    runner_up = ""
    if len(parent_counts) >= 2:
        runner_up = parent_counts.most_common(2)[1][0]

    also_category = runner_up if confidence == "LOW" else ""

    # 6. Filters
    filters = {"parent_code": category} if confidence != "LOW" else {}

    # 7. Strategy string
    if confidence == "HIGH":
        strategy = f"Strong match — {top_cluster} in {category}. Filter by category."
    elif confidence == "MEDIUM":
        strategy = (
            f"Moderate match — {top_cluster} in {category}. "
            f"Use category filter, skip cluster filter."
        )
    else:
        strategy = (
            f"Weak match — mixed results across {category} and {runner_up}. "
            f"Search broadly without filters."
        )

    return {
        "category": category,
        "confidence": confidence,
        "clusters": clusters_str,
        "filters": filters,
        "strategy": strategy,
        "query_variants": [],
        "also_category": also_category,
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
            _gate_stopped = False  # track if we exited early

            # Global gate state (shared across all specs)
            seen_ids: set[str] = set()
            consecutive_low = 0
            tier = "weak"  # default; updated by gate checks when not exploring
            medium_budget = MEDIUM_EXTRA_BUDGET
            _eval_offset = 0  # tracks how far _incremental_evaluate has processed

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
            is_exploring = bool(ctx.quality and ctx.quality.phase == "explore")
            if is_exploring:
                medium_budget = MEDIUM_EXTRA_BUDGET + EXPLORE_EXTRA_BUDGET

            for spec in specs:
                if _gate_stopped:
                    break

                q = spec["query"]
                f = spec.get("filters")
                k = spec.get("top_k", top_k)

                # ── Main query (always runs) ──
                try:
                    if is_w3:
                        r = search_multi(ctx, q, final_top_k=k)
                    else:
                        r = search(ctx, q, filters=f, top_k=k)
                    batch_ids = {str(h["id"]) for h in r["results"]}
                    new_unique_main = len(batch_ids - seen_ids)
                    seen_ids.update(batch_ids)
                    all_results.extend(r["results"])
                    search_count += 1
                    # Record yield for explore phase velocity tracking
                    if ctx.quality:
                        ctx.quality.record_search_yield(new_unique_main)

                    # ── Script-based classification (runs once, ~5ms) ──
                    if ctx.classification is None and r["results"]:
                        ctx.classification = _extract_classification(r["results"])
                        _emit(ctx, "research", "classified", {
                            "category": ctx.classification["category"],
                            "confidence": ctx.classification["confidence"],
                        })
                except Exception as e:
                    errors.append(str(e))
                    print(f"[research] WARNING: search failed: {e}")

                # ── Checkpoint 1: evaluate after main query ──
                eval_result = _incremental_evaluate(
                    ctx, all_results, eval_question, eval_model, _eval_offset
                )
                _eval_offset = eval_result["processed_to"]

                # Check tier after first evaluation
                if not is_exploring:
                    tier = ctx.quality.critique_tier if ctx.quality else "weak"
                    if tier == "strong":
                        print(
                            f"[research] GATE: strong tier after {search_count} searches, "
                            f"stopping extra queries"
                        )
                        _gate_stopped = True
                        _emit(
                            ctx,
                            "research",
                            "gate_stopped",
                            {
                                "reason": "strong",
                                "search_count": search_count,
                                "tier": tier,
                            },
                        )
                        break

                for eq in spec.get("extra_queries") or []:
                    # Gate check BEFORE issuing search
                    if not is_exploring:
                        tier = ctx.quality.critique_tier if ctx.quality else "weak"

                        if tier == "strong":
                            print("[research] GATE: strong tier reached, skipping remaining extras")
                            _gate_stopped = True
                            _emit(
                                ctx,
                                "research",
                                "gate_stopped",
                                {
                                    "reason": "strong",
                                    "search_count": search_count,
                                    "tier": tier,
                                },
                            )
                            break

                        if tier == "medium":
                            if medium_budget <= 0:
                                print(
                                    f"[research] GATE: medium tier, budget exhausted "
                                    f"after {search_count} searches"
                                )
                                _gate_stopped = True
                                _emit(
                                    ctx,
                                    "research",
                                    "gate_stopped",
                                    {
                                        "reason": "medium_budget",
                                        "search_count": search_count,
                                        "tier": tier,
                                    },
                                )
                                break
                            medium_budget -= 1

                    if consecutive_low >= SATURATION_CONSECUTIVE_MAX:
                        print(
                            f"[research] GATE: {consecutive_low} consecutive low-yield "
                            f"searches, stopping"
                        )
                        _gate_stopped = True
                        _emit(
                            ctx,
                            "research",
                            "gate_stopped",
                            {
                                "reason": "saturation",
                                "search_count": search_count,
                                "tier": tier,
                            },
                        )
                        break

                    # Execute search
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
                        batch_ids = {str(h["id"]) for h in r["results"]}
                        new_unique = len(batch_ids - seen_ids)
                        seen_ids.update(batch_ids)

                        all_results.extend(r["results"])
                        search_count += 1

                        # Novelty tracking
                        if new_unique <= SATURATION_LOW_YIELD:
                            consecutive_low += 1
                        else:
                            consecutive_low = 0

                        # Record yield for explore phase velocity tracking
                        if ctx.quality:
                            ctx.quality.record_search_yield(new_unique)

                    except Exception as e:
                        errors.append(str(e))
                        print(f"[research] WARNING: search failed: {e}")

                    # ── Checkpoint 2: evaluate at EVAL_CHECKPOINT_SEARCH ──
                    if (
                        search_count == EVAL_CHECKPOINT_SEARCH
                        or consecutive_low >= SATURATION_CONSECUTIVE_MAX
                    ):
                        cp2 = _incremental_evaluate(
                            ctx, all_results, eval_question, eval_model, _eval_offset
                        )
                        _eval_offset = cp2["processed_to"]

            if not all_results:
                print("[research] ERROR: all searches failed")
                tc.set_summary(
                    {
                        "search_count": search_count,
                        "raw": 0,
                        "unique": 0,
                        "filtered": 0,
                        "eval_summary": "no results",
                        "gate_stopped": _gate_stopped,
                    }
                )
                return {
                    "results": [],
                    "ratings": {},
                    "search_count": search_count,
                    "eval_summary": "no results",
                }

            # ── Final evaluation: catch any unevaluated stragglers ──
            final_eval = _incremental_evaluate(
                ctx, all_results, eval_question, eval_model, _eval_offset
            )
            deduped = final_eval["deduped"]

            # Build ratings map from ctx.evaluated_ratings (authoritative)
            # Include ALL prior ratings (matching current behavior — downstream
            # code may expect cross-call ratings for dedup)
            ratings_map: dict = dict(ctx.evaluated_ratings)

            # Filter OFF-TOPIC
            filtered = [
                r for r in deduped if ratings_map.get(str(r["id"]), "UNRATED") != "OFF-TOPIC"
            ]

            seen_map = {str(r["id"]) for r in deduped}
            relevant = sum(
                1 for rid, v in ratings_map.items() if rid in seen_map and v == "RELEVANT"
            )
            partial = sum(1 for rid, v in ratings_map.items() if rid in seen_map and v == "PARTIAL")
            off_topic = sum(
                1 for rid, v in ratings_map.items() if rid in seen_map and v == "OFF-TOPIC"
            )
            summary = f"{relevant} relevant, {partial} partial, {off_topic} off-topic"
            if _gate_stopped:
                tier = ctx.quality.critique_tier if ctx.quality else "weak"
                summary += f" (gate: {tier})"

            print(
                f"[research] {search_count} searches | {len(all_results)} raw"
                f" > {len(deduped)} unique > {len(filtered)} filtered"
                f"{' [GATE]' if _gate_stopped else ''}"
            )
            print(f"[research] {summary}")
            for r in filtered[:5]:
                tag = ratings_map.get(str(r["id"]), "-")
                print(
                    f"  [{r['id']}] {r['score']:.2f} {tag:10s} "
                    f"Q: {str(r.get('question', ''))[:100]}"
                )
            if len(filtered) > 5:
                print(f"  ... and {len(filtered) - 5} more")

            tc.set_summary(
                {
                    "search_count": search_count,
                    "raw": len(all_results),
                    "unique": len(deduped),
                    "filtered": len(filtered),
                    "eval_summary": summary,
                    "gate_stopped": _gate_stopped,
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
                "Synthesize a comprehensive, well-structured answer from the evidence below.\n\n",
            ]

            # Inject must-cite brief before evidence
            if must_cite:
                prompt_parts.append(must_cite)

            prompt_parts.extend(
                [
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
                ]
            )
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
                bus.emit(
                    "tool_progress",
                    {
                        "tool": "draft_answer",
                        "phase": "synthesized",
                        "data": {"answer_length": len(answer), "tier": tier},
                        "duration_ms": synth_ms,
                    },
                )

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
                    print(
                        f"[draft_answer] STRONG: citation check PASS "
                        f"({len(citation_result['cited'])} cited, "
                        f"coverage={citation_result['coverage']})"
                    )

            if tier == "medium":
                # Focused LLM critique — voice + attribution only, no revision loop
                critique_text, passed, dimensions = critique_answer(
                    ctx,
                    question,
                    answer,
                    evidence=evidence,
                    model=model,
                    focus="voice_attribution",
                )
                print(f"[draft_answer] MEDIUM: focused critique {'PASS' if passed else 'FAIL'}")

            elif tier == "weak":
                # Full critique + revision loop (original behavior)
                critique_text, passed, dimensions = critique_answer(
                    ctx,
                    question,
                    answer,
                    evidence=evidence,
                    model=model,
                )

                if not passed:
                    # Determine failed dimensions for targeted revision
                    failed_dims = {k: v for k, v in dimensions.items() if v["verdict"] == "FAIL"}
                    cosmetic_only = bool(failed_dims) and all(
                        k in COSMETIC_DIMENSIONS for k in failed_dims
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
                bus.emit(
                    "tool_progress",
                    {
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
                    },
                )

            # Wire QualityGate — record draft + final critique outcome
            if quality is not None:
                quality.record_draft(len(answer))
                quality.record_critique(passed, critique_text, dimensions)

            failed_dims_list = [k for k, v in dimensions.items() if v["verdict"] == "FAIL"]
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
