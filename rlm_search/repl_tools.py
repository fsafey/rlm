"""REPL setup code v2 — injects search tools using SearchContext + departments."""

from __future__ import annotations

import json
from typing import Any


def build_search_setup_code(
    api_url: str,
    timeout: int = 30,
    kb_overview_data: dict[str, Any] | None = None,
    rlm_model: str = "",
    rlm_backend: str = "",
    depth: int = 0,
    max_delegation_depth: int = 1,
    sub_iterations: int = 3,
    query: str = "",
    classify_model: str = "",
    pipeline_mode: str = "",
    existing_answer: str | None = None,
) -> str:
    """Return Python code string executed in LocalREPL via setup_code parameter.

    Like build_search_setup_code() but creates a SearchContext with departments
    (EventBus, EvidenceStore, QualityGate) instead of a ToolContext. LM-facing
    wrapper function signatures are identical.

    The ``source_registry`` alias is a **live reference** to EvidenceStore._registry,
    so mutations from register_hit() are visible to the LM via ``print(source_registry)``
    without re-assignment.
    """
    code = f"""\
import os as _os
from rlm_search.bus import EventBus as _EventBus
from rlm_search.evidence import EvidenceStore as _EvidenceStore
from rlm_search.quality import QualityGate as _QualityGate
from rlm_search.tools.context import SearchContext as _SearchContext
from rlm_search.tools import api_tools as _api
from rlm_search.tools import subagent_tools as _sub
from rlm_search.tools import composite_tools as _comp
from rlm_search.tools import format_tools as _fmt
from rlm_search.tools import kb as _kb_mod
from rlm_search.tools import progress_tools as _prog

# Create departments
_bus = globals().get("_sse_event_bus") or _EventBus()
_evidence = _EvidenceStore()
_quality = _QualityGate(evidence=_evidence)

_ctx = _SearchContext(
    api_url={api_url!r},
    api_key=_os.environ.get("_RLM_CASCADE_API_KEY", ""),
    timeout={timeout!r},
    bus=_bus,
    evidence=_evidence,
    quality=_quality,
)

# Wire LLM callables from LocalREPL globals (None when exec'd standalone in tests)
_ctx.llm_query = globals().get("llm_query")
_ctx.llm_query_batched = globals().get("llm_query_batched")
_ctx.progress_callback = globals().get("_progress_callback")
_ctx._rlm_model = {rlm_model!r}
_ctx._rlm_backend = {rlm_backend!r}
_ctx._depth = {depth!r}
_ctx._max_delegation_depth = {max_delegation_depth!r}
_ctx._sub_iterations = {sub_iterations!r}
_ctx._parent_logger = globals().get("_parent_logger_ref")
_ctx._record_rlm_call = globals().get("_record_rlm_call")
_ctx.pipeline_mode = {pipeline_mode!r}
"""

    # Embed kb_overview data as JSON (avoids nested brace escaping issues)
    if kb_overview_data is not None:
        kb_json_str = json.dumps(kb_overview_data)
        code += f"\nimport json as _json\n_ctx.kb_overview_data = _json.loads({kb_json_str!r})\n"

    if existing_answer is not None:
        code += f"\n_ctx.existing_answer = {existing_answer!r}\n"

    # Run init_classify at setup_code time (zero iteration cost)
    if query:
        code += f"\n_sub.init_classify(_ctx, {query!r}, model={classify_model!r})\n"
    code += "\nclassification = _ctx.classification\n"

    code += """
# ── Wrapper functions (bind _ctx, preserve REPL-facing signatures) ──────

def search(query, filters=None, top_k=10):
    return _api.search(_ctx, query, filters=filters, top_k=top_k)

def browse(filters=None, offset=0, limit=20, sort_by=None, group_by=None, group_limit=4):
    return _api.browse(_ctx, filters=filters, offset=offset, limit=limit, sort_by=sort_by, group_by=group_by, group_limit=group_limit)

def format_evidence(results, max_per_source=3):
    return _fmt.format_evidence(results, max_per_source=max_per_source)

def fiqh_lookup(query):
    return _api.fiqh_lookup(_ctx, query)

def kb_overview():
    return _kb_mod.kb_overview(_ctx)

def evaluate_results(question, results, top_n=5, model=None):
    return _sub.evaluate_results(_ctx, question, results, top_n=top_n, model=model)

def reformulate(question, failed_query, top_score=0.0, model=None):
    return _sub.reformulate(_ctx, question, failed_query, top_score=top_score, model=model)

def critique_answer(question, draft, evidence=None, model=None):
    verdict, passed = _sub.critique_answer(_ctx, question, draft, evidence=evidence, model=model)
    return {"verdict": verdict, "passed": passed}

def check_progress():
    return _prog.check_progress(_ctx)

def research(query, filters=None, top_k=10, extra_queries=None, eval_model=None):
    result = _comp.research(_ctx, query, filters=filters, top_k=top_k, extra_queries=extra_queries, eval_model=eval_model)
    progress = _prog.check_progress(_ctx)
    if progress["phase"] == "ready":
        print(f"\\n>>> PROGRESS: Evidence sufficient (confidence {progress['confidence']}%). Call draft_answer() now.")
    elif progress["phase"] == "finalize":
        print(f"\\n>>> PROGRESS: Draft complete. Call FINAL_VAR(answer) to finish.")
    elif progress["phase"] in ("stalled", "repeating"):
        print(f"\\n>>> PROGRESS: {progress['guidance']}")
    return result

def draft_answer(question, results, instructions=None, model=None):
    return _comp.draft_answer(_ctx, question, results, instructions=instructions, model=model)

# ── Mutable state aliases (delegate to departments) ─────────────────────
# source_registry is a LIVE reference to EvidenceStore._registry
# so register_hit() writes are visible to the LM via print(source_registry)
source_registry = _ctx.evidence.live_dict
search_log = _ctx.evidence.search_log
tool_calls = _ctx.tool_calls

# Public alias for persistence extraction
tool_context = _ctx
"""

    # Conditionally emit rlm_query wrapper when depth allows further delegation
    if depth < max_delegation_depth:
        code += """
from rlm_search.tools import delegation_tools as _deleg

def rlm_query(sub_question, instructions=""):
    return _deleg.rlm_query(_ctx, sub_question, instructions=instructions)
"""

    return code
