"""Per-session tool context — holds all mutable state and config."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class ToolContext:
    """Isolated per-session state for REPL tools.

    Each ``exec()`` creates its own ``ToolContext``, so concurrent sessions
    never share mutable state.  Every tool implementation receives ``ctx``
    as its first argument.
    """

    api_url: str
    api_key: str = dataclasses.field(default="", repr=False)
    timeout: int = 30
    headers: dict[str, str] = dataclasses.field(default_factory=dict, repr=False)
    kb_overview_data: dict | None = None
    classification: dict | None = None
    w3_state: dict = dataclasses.field(default_factory=dict)
    pipeline_mode: str = ""  # "w3" when running W3 enrichment, "" for generic RLM
    existing_answer: str | None = None  # Scholar's answer for sanitize mode

    # Mutable per-session state
    search_log: list = dataclasses.field(default_factory=list)
    source_registry: dict = dataclasses.field(default_factory=dict)
    evaluated_ratings: dict = dataclasses.field(default_factory=dict)  # id -> rating from prior research() calls
    tool_calls: list = dataclasses.field(default_factory=list)
    current_parent_idx: int | None = None

    # Callables injected from LocalREPL globals
    llm_query: Any = None
    llm_query_batched: Any = None
    progress_callback: Any = None

    # Delegation support (set via build_search_setup_code params)
    _rlm_model: str = ""
    _rlm_backend: str = ""
    _depth: int = 0
    _max_delegation_depth: int = 1
    _sub_iterations: int | None = None
    _parent_logger: Any = None

    def __post_init__(self) -> None:
        if not self.headers:
            self.headers = {"Content-Type": "application/json"}
            if self.api_key:
                self.headers["x-api-key"] = self.api_key
