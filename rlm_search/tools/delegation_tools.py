"""Delegation tools: rlm_query() — spawn child RLM for sub-question research."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rlm_search.tools.tracker import tool_call_tracker

if TYPE_CHECKING:
    from rlm.core.types import RLMChatCompletion
    from rlm_search.tools.context import ToolContext

SUB_AGENT_PROMPT = """You are a focused research sub-agent with access to a specialized knowledge base.

Your job: Research ONE specific sub-question and provide a grounded answer.

## Tools Available
- research(query, filters, top_k, extra_queries) -- search + evaluate
- draft_answer(question, results) -- synthesize answer
- check_progress() -- assess progress
- kb_overview() -- taxonomy overview

## Workflow
1. research() with 1-2 targeted queries
2. check_progress() -- if ready, draft
3. draft_answer() and FINAL_VAR(answer)

Keep it focused. You have a limited iteration budget.
Aim for 2-3 code blocks maximum.

FINAL_VAR(answer) when done."""


def rlm_query(
    ctx: ToolContext,
    sub_question: str,
    instructions: str = "",
) -> dict:
    """Delegate a sub-question to a child RLM with its own isolated context.

    Args:
        ctx: Per-session tool context (must be below max delegation depth).
        sub_question: The specific question for the child to research.
        instructions: Optional guidance for the child agent.

    Returns:
        Dict with ``answer``, ``sub_question``, ``searches_run``, ``sources_merged``.
    """
    with tool_call_tracker(
        ctx,
        "rlm_query",
        {"sub_question": sub_question, "instructions": instructions},
    ) as tc:
        # Depth guard: prevent delegation beyond configured max depth
        if ctx._depth >= ctx._max_delegation_depth:
            error_result = {"error": "Cannot delegate from a child agent"}
            tc.set_summary({"sub_question": sub_question, "error": "depth_guard"})
            print(f"[rlm_query] ERROR: depth={ctx._depth}, cannot delegate")
            return error_result

        print(f'[rlm_query] Delegating: "{sub_question}"')

        try:
            result, child_sources, searches_run = _run_child_rlm(ctx, sub_question, instructions)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            print(f"[rlm_query] FAILED: {error_msg}")
            tc.set_summary({"sub_question": sub_question, "error": error_msg})
            return {
                "error": error_msg,
                "sub_question": sub_question,
                "searches_run": 0,
                "sources_merged": 0,
            }

        # Merge child sources into parent registry
        n_merged = 0
        for sid, entry in child_sources.items():
            if sid not in ctx.source_registry:
                ctx.source_registry[sid] = entry
                n_merged += 1

        answer = result.response or ""

        print(f"[rlm_query] Complete: {searches_run} searches, {n_merged} sources merged")

        tc.set_summary(
            {
                "sub_question": sub_question,
                "searches_run": searches_run,
                "answer_length": len(answer),
                "sources_merged": n_merged,
            }
        )

        return {
            "answer": answer,
            "sub_question": sub_question,
            "searches_run": searches_run,
            "sources_merged": n_merged,
        }


def _run_child_rlm(
    ctx: ToolContext,
    sub_question: str,
    instructions: str,
) -> tuple[RLMChatCompletion, dict, int]:
    """Spawn a child RLM with isolated REPL and reduced iteration budget.

    Returns:
        Tuple of (completion_result, child_source_registry, searches_run).
    """
    from rlm.core.rlm import RLM
    from rlm_search.config import (
        ANTHROPIC_API_KEY,
        CASCADE_API_KEY,
        CASCADE_API_URL,
        RLM_BACKEND,
        RLM_MODEL,
        RLM_SUB_ITERATIONS,
        RLM_SUB_MODEL,
    )
    from rlm_search.repl_tools import build_search_setup_code
    from rlm_search.streaming_logger import ChildStreamingLogger

    backend = ctx._rlm_backend or RLM_BACKEND
    child_model = RLM_SUB_MODEL or ctx._rlm_model or RLM_MODEL
    child_depth = ctx._depth + 1
    # Reduce iteration budget at deeper delegation levels
    sub_iters = ctx._sub_iterations if ctx._sub_iterations is not None else RLM_SUB_ITERATIONS
    child_iterations = sub_iters if child_depth <= 1 else max(2, sub_iters - 1)

    # Build backend kwargs (same pattern as api._build_rlm_kwargs)
    if backend == "claude_cli":
        backend_kwargs: dict = {"model": child_model}
    else:
        backend_kwargs = {"model_name": child_model}
        if ANTHROPIC_API_KEY:
            backend_kwargs["api_key"] = ANTHROPIC_API_KEY

    setup_code = build_search_setup_code(
        api_url=CASCADE_API_URL,
        api_key=CASCADE_API_KEY,
        kb_overview_data=ctx.kb_overview_data,
        rlm_model=child_model,
        rlm_backend=backend,
        depth=child_depth,
        max_delegation_depth=ctx._max_delegation_depth,
        sub_iterations=sub_iters,
    )

    prompt = sub_question
    if instructions:
        prompt += f"\n\nInstructions: {instructions}"

    # Build child logger that streams sub-iterations to parent SSE queue
    child_logger = (
        ChildStreamingLogger(ctx._parent_logger, sub_question) if ctx._parent_logger else None
    )

    # persistent=True so we can extract source_registry after completion
    child_rlm = RLM(
        backend=backend,
        backend_kwargs=backend_kwargs,
        environment="local",
        environment_kwargs={"setup_code": setup_code},
        max_iterations=child_iterations,
        max_depth=1,
        custom_system_prompt=SUB_AGENT_PROMPT,
        logger=child_logger,
        persistent=True,
    )

    try:
        result = child_rlm.completion(prompt, root_prompt=sub_question)

        # Extract state from child REPL locals
        # "source_registry" / "search_log" have no underscore prefix -> pass LocalREPL filter
        child_sources: dict = {}
        searches_run = 0
        if child_rlm._persistent_env is not None:
            sr = child_rlm._persistent_env.locals.get("source_registry")
            if isinstance(sr, dict):
                child_sources = sr.copy()
            sl = child_rlm._persistent_env.locals.get("search_log")
            if isinstance(sl, list):
                searches_run = len(sl)

        return result, child_sources, searches_run
    finally:
        child_rlm.close()
