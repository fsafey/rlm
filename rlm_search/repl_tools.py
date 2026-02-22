"""REPL setup code that injects search tools into the LocalREPL namespace."""

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
) -> str:
    """Return Python code string executed in LocalREPL via setup_code parameter.

    Imports tool implementations from ``rlm_search.tools.*``, creates a
    per-session ``ToolContext``, and defines thin wrapper functions that
    bind the context — preserving the existing REPL-facing API
    (``search(query)`` not ``search(ctx, query)``).

    Mutable state aliases (``search_log``, ``source_registry``, ``tool_calls``)
    are references to the same objects on ``_ctx``, so mutations are visible
    to ``StreamingLogger`` via ``repl.locals``.
    """
    code = f"""\
import os as _os
from rlm_search.tools.context import ToolContext as _ToolContext
from rlm_search.tools import api_tools as _api
from rlm_search.tools import subagent_tools as _sub
from rlm_search.tools import composite_tools as _comp
from rlm_search.tools import format_tools as _fmt
from rlm_search.tools import kb as _kb_mod
from rlm_search.tools import progress_tools as _prog

_ctx = _ToolContext(
    api_url={api_url!r},
    api_key=_os.environ.get("_RLM_CASCADE_API_KEY", ""),
    timeout={timeout!r},
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
"""

    # Embed kb_overview data as JSON (avoids nested brace escaping issues)
    if kb_overview_data is not None:
        kb_json_str = json.dumps(kb_overview_data)
        code += f"\nimport json as _json\n_ctx.kb_overview_data = _json.loads({kb_json_str!r})\n"

    # Run init_classify at setup_code time (zero iteration cost)
    if query:
        code += f"\n_sub.init_classify(_ctx, {query!r}, model={classify_model!r})\n"
    code += "\nclassification = _ctx.classification\n"

    code += """
# ── Wrapper functions (bind _ctx, preserve REPL-facing signatures) ──────

def search(query, filters=None, top_k=10):
    return _api.search(_ctx, query, filters=filters, top_k=top_k)

def search_multi(query, collections=None, filters=None, top_k=10):
    return _api.search_multi(_ctx, query, collections=collections, filters=filters, top_k=top_k)

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

def critique_answer(question, draft, model=None):
    return _sub.critique_answer(_ctx, question, draft, model=model)

def check_progress():
    return _prog.check_progress(_ctx)

def research(query, filters=None, top_k=10, extra_queries=None, eval_model=None):
    return _comp.research(_ctx, query, filters=filters, top_k=top_k, extra_queries=extra_queries, eval_model=eval_model)

def draft_answer(question, results, instructions=None, model=None):
    return _comp.draft_answer(_ctx, question, results, instructions=instructions, model=model)

# ── Mutable state aliases (same objects as _ctx.*) ──────────────────────
# StreamingLogger reads these from repl.locals
search_log = _ctx.search_log
source_registry = _ctx.source_registry
tool_calls = _ctx.tool_calls
"""

    # Conditionally emit rlm_query wrapper when depth allows further delegation
    if depth < max_delegation_depth:
        code += """
from rlm_search.tools import delegation_tools as _deleg

def rlm_query(sub_question, instructions=""):
    return _deleg.rlm_query(_ctx, sub_question, instructions=instructions)
"""

    return code
