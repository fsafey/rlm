"""Composite tools: research(), draft_answer() — orchestrate lower-level tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.tools.api_tools import search, search_multi
from rlm_search.tools.format_tools import format_evidence
from rlm_search.tools.subagent_tools import batched_critique, evaluate_results
from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm_search.tools.context import ToolContext


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
        saved_parent = ctx.current_parent_idx
        ctx.current_parent_idx = tc.idx

        all_results: list = []
        search_count = 0
        errors: list[str] = []

        if isinstance(query, list):
            specs = query
            eval_question = " ; ".join(s["query"] for s in specs)
        else:
            specs = [
                {"query": query, "filters": filters, "top_k": top_k, "extra_queries": extra_queries}
            ]
            eval_question = query

        use_multi = ctx.pipeline_mode == "w3"

        for spec in specs:
            q = spec["query"]
            f = spec.get("filters")
            k = spec.get("top_k", top_k)
            try:
                if use_multi:
                    r = search_multi(ctx, q, final_top_k=k)
                else:
                    r = search_multi(ctx, q, filters=f, top_k=k)
                all_results.extend(r["results"])
                search_count += 1
            except Exception as e:
                if not use_multi:
                    try:
                        r = search(ctx, q, filters=f, top_k=k)
                        all_results.extend(r["results"])
                        search_count += 1
                    except Exception as e2:
                        errors.append(str(e2))
                        print(f"[research] WARNING: search failed: {e2}")
                else:
                    errors.append(str(e))
                    print(f"[research] WARNING: search failed: {e}")
            for eq in spec.get("extra_queries") or []:
                try:
                    if use_multi:
                        r = search_multi(ctx, eq["query"], final_top_k=eq.get("top_k", k))
                    else:
                        r = search_multi(
                            ctx, eq["query"], filters=eq.get("filters"), top_k=eq.get("top_k", k)
                        )
                    all_results.extend(r["results"])
                    search_count += 1
                except Exception as e:
                    if not use_multi:
                        try:
                            r = search(
                                ctx,
                                eq["query"],
                                filters=eq.get("filters"),
                                top_k=eq.get("top_k", k),
                            )
                            all_results.extend(r["results"])
                            search_count += 1
                        except Exception as e2:
                            errors.append(str(e2))
                            print(f"[research] WARNING: search failed: {e2}")
                    else:
                        errors.append(str(e))
                        print(f"[research] WARNING: search failed: {e}")

        if not all_results:
            print("[research] ERROR: all searches failed")
            ctx.current_parent_idx = saved_parent
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

        # Evaluate top results
        ratings_map: dict = {}
        try:
            eval_out = evaluate_results(
                ctx, eval_question, deduped[:15], top_n=15, model=eval_model
            )
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

        print(
            f"[research] {search_count} searches | {len(all_results)} raw > {len(deduped)} unique > {len(filtered)} filtered"
        )
        print(f"[research] {summary}")
        for r in filtered[:5]:
            tag = ratings_map.get(r["id"], "-")
            print(f"  [{r['id']}] {r['score']:.2f} {tag:10s} Q: {r['question'][:100]}")
        if len(filtered) > 5:
            print(f"  ... and {len(filtered) - 5} more")

        ctx.current_parent_idx = saved_parent
        tc.set_summary(
            {
                "search_count": search_count,
                "raw": len(all_results),
                "unique": len(deduped),
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
        saved_parent = ctx.current_parent_idx
        ctx.current_parent_idx = tc.idx

        prompt_parts = [
            "You are an Islamic Q&A scholar synthesizing from verified sources.\n\n",
            f"QUESTION:\n{question}\n\n",
            "EVIDENCE:\n" + "\n".join(evidence) + "\n\n",
        ]
        if instructions:
            prompt_parts.append(f"INSTRUCTIONS:\n{instructions}\n\n")
        prompt_parts.append(
            "FORMAT: ## Answer (with [Source: <id>] citations), "
            "## Evidence (source summaries), ## Confidence (High/Medium/Low).\n"
            "Only cite IDs from the evidence. Flag gaps explicitly.\n"
        )

        answer = ctx.llm_query("".join(prompt_parts), model=model)

        critique_text, passed = batched_critique(ctx, question, answer, model=model)
        revised = False

        if not passed:
            rev_parts = [
                "Revise this answer based on the critique.\n\n",
                f"CRITIQUE:\n{critique_text}\n\n",
                f"ORIGINAL:\n{answer}\n\n",
                "EVIDENCE:\n" + "\n".join(evidence) + "\n\n",
                "Fix flagged issues. Keep valid citations. Same format.\n",
            ]
            answer = ctx.llm_query("".join(rev_parts), model=model)
            critique_text, passed = batched_critique(ctx, question, answer, model=model)
            revised = True

        print(
            f"[draft_answer] {'PASS' if passed else 'FAIL'}"
            f"{' (revised)' if revised else ''}"
            f" | {len(answer)} chars | {len(evidence)} evidence entries"
        )
        ctx.current_parent_idx = saved_parent
        tc.set_summary({
            "passed": passed,
            "revised": revised,
            "answer_length": len(answer),
            "answer_preview": answer[:300],
            "critique_verdict": "PASS" if passed else "FAIL",
            "critique_reason": critique_text[:150] if critique_text else "",
        })
        return {"answer": answer, "critique": critique_text, "passed": passed, "revised": revised}
