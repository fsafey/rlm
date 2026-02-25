"""Composite tools: research(), draft_answer() — orchestrate lower-level tools."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from rlm_search.prompts import DOMAIN_PREAMBLE
from rlm_search.tools.api_tools import search, search_multi
from rlm_search.tools.format_tools import format_evidence
from rlm_search.tools.subagent_tools import critique_answer, evaluate_results
from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


@contextlib.contextmanager
def _child_scope(ctx: Any, parent_idx: int | None) -> Generator:
    """Exception-safe parent index scoping — replaces manual save/restore."""
    saved = ctx.current_parent_idx
    ctx.current_parent_idx = parent_idx
    try:
        yield
    finally:
        ctx.current_parent_idx = saved


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
    """Synthesize an answer from results, critique it, and revise if needed.

    Handles: format_evidence -> llm_query synthesis -> critique ->
    conditional revision (one retry on FAIL).

    Args:
        ctx: Per-session tool context.
        question: The user's question.
        results: List of result dicts (use ``research()["results"]``).
        instructions: Optional guidance for the synthesis LLM call.
        model: Optional model override for synthesis / revision.

    Returns:
        Dict with ``answer``, ``critique``, ``passed``, ``revised``.
    """
    evidence = format_evidence(results[:20])
    if not evidence:
        print("[draft_answer] ERROR: no evidence to synthesize from")
        return {"answer": "", "critique": "", "passed": False, "revised": False}

    with tool_call_tracker(
        ctx,
        "draft_answer",
        {"question": question[:100], "num_results": len(results)},
        parent_idx=ctx.current_parent_idx,
    ) as tc:
        with _child_scope(ctx, tc.idx):
            prompt_parts = [
                DOMAIN_PREAMBLE,
                "Synthesize a comprehensive, well-structured answer from the "
                "evidence below.\n\n"
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

            critique_text, passed = critique_answer(
                ctx, question, answer, evidence=evidence, model=model
            )
            revised = False

            if not passed:
                rev_parts = [
                    DOMAIN_PREAMBLE,
                    "Revise this answer based on the critique.\n\n",
                    f"CRITIQUE:\n{critique_text}\n\n",
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
                    "Do NOT say 'Here is the revised answer' or describe what you changed.\n"
                    "Do NOT include revision notes, commentary, or meta-text.\n"
                    "Start directly with ## Answer.\n",
                ]
                answer = ctx.llm_query("".join(rev_parts), model=model)
                critique_text, passed = critique_answer(
                    ctx, question, answer, evidence=evidence, model=model
                )
                revised = True

            # Wire QualityGate — record draft + final critique outcome
            quality = getattr(ctx, "quality", None)
            if quality is not None:
                quality.record_draft(len(answer))
                quality.record_critique(passed, critique_text)

            print(
                f"[draft_answer] {'PASS' if passed else 'FAIL'}"
                f"{' (revised)' if revised else ''}"
                f" | {len(answer)} chars | {len(evidence)} evidence entries"
            )
            tc.set_summary(
                {
                    "passed": passed,
                    "revised": revised,
                    "answer_length": len(answer),
                    "answer_preview": answer[:300],
                    "critique_verdict": "PASS" if passed else "FAIL",
                    "critique_reason": critique_text[:150] if critique_text else "",
                }
            )
            return {
                "answer": answer,
                "critique": critique_text,
                "passed": passed,
                "revised": revised,
            }
