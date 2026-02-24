"""REPL tool implementations for rlm_search.

Extracted from the setup_code string in repl_tools.py into proper Python modules
with static analysis, IDE support, and isolated unit testing.
"""

from rlm_search.tools.api_tools import browse, fiqh_lookup, search
from rlm_search.tools.composite_tools import draft_answer, research
from rlm_search.tools.constants import MAX_DRAFT_LEN, MAX_QUERY_LEN, META_FIELDS
from rlm_search.tools.context import ToolContext
from rlm_search.tools.delegation_tools import rlm_query
from rlm_search.tools.format_tools import format_evidence
from rlm_search.tools.kb import kb_overview
from rlm_search.tools.normalize import normalize_hit
from rlm_search.tools.progress_tools import check_progress
from rlm_search.tools.subagent_tools import (
    critique_answer,
    evaluate_results,
    init_classify,
    reformulate,
)
from rlm_search.tools.tracker import tool_call_tracker

__all__ = [
    "ToolContext",
    "META_FIELDS",
    "MAX_QUERY_LEN",
    "MAX_DRAFT_LEN",
    "tool_call_tracker",
    "normalize_hit",
    "format_evidence",
    "search",
    "browse",
    "fiqh_lookup",
    "evaluate_results",
    "reformulate",
    "critique_answer",
    "init_classify",
    "research",
    "draft_answer",
    "kb_overview",
    "check_progress",
    "rlm_query",
]
