"""rlm_search/tools/context_v2.py"""

from __future__ import annotations

import dataclasses
from typing import Any

from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate


@dataclasses.dataclass
class SearchContext:
    """Thin wiring harness connecting departments.

    ~10 fields, down from 22. Departments own their state.
    This just holds API config + department references + LLM callables.
    """

    # --- API config (read-only after init) ---
    api_url: str
    api_key: str
    timeout: int = 30
    headers: dict[str, str] = dataclasses.field(default_factory=dict)

    # --- Department references ---
    bus: EventBus = dataclasses.field(default_factory=EventBus)
    evidence: EvidenceStore = dataclasses.field(default_factory=EvidenceStore)
    quality: QualityGate | None = None  # auto-created in __post_init__ if not provided

    # --- LLM callables (injected from REPL globals) ---
    llm_query: Any = None
    llm_query_batched: Any = None

    # --- REPL compatibility (tracker still appends here for LM visibility) ---
    tool_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    # --- Delegation config ---
    classification: dict | None = None
    kb_overview_data: dict | None = None
    _rlm_model: str = ""
    _rlm_backend: str = ""
    _depth: int = 0
    _max_delegation_depth: int = 1
    _sub_iterations: int | None = None
    pipeline_mode: str = ""

    # --- Backward compat (removed after Task 11 tool migration) ---
    current_parent_idx: int | None = None
    _parent_logger: Any = None
    progress_callback: Any = None
    existing_answer: str | None = None
    w3_state: dict = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.headers and self.api_key:
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        # QualityGate needs evidence reference — auto-create if not provided
        if self.quality is None:
            self.quality = QualityGate(evidence=self.evidence)

    # --- Backward compat properties (delegate to departments) ---

    @property
    def source_registry(self) -> dict[str, dict[str, Any]]:
        """Live reference — tools write via register_hit(), LM reads via print()."""
        return self.evidence.live_dict

    @property
    def search_log(self) -> list[dict[str, Any]]:
        return self.evidence.search_log

    @property
    def evaluated_ratings(self) -> _RatingsFacade:
        """Flat dict[str, str] facade over evidence._ratings for backward compat.

        Old ToolContext stores {id: "RELEVANT"}, but EvidenceStore stores
        {id: {"rating": "RELEVANT", "confidence": 4}}. This facade translates
        reads/writes so research() in composite_tools.py works with both.
        """
        return _RatingsFacade(self.evidence)


class _RatingsFacade:
    """dict-like facade: reads return rating strings, writes call set_rating()."""

    def __init__(self, evidence: EvidenceStore) -> None:
        self._evidence = evidence

    def __getitem__(self, key: str) -> str:
        info = self._evidence._ratings.get(str(key))
        if info is None:
            raise KeyError(key)
        return info["rating"]

    def __setitem__(self, key: str, value: str) -> None:
        self._evidence.set_rating(str(key), value, confidence=3)

    def __contains__(self, key: object) -> bool:
        return str(key) in self._evidence._ratings

    def __iter__(self):  # type: ignore[override]
        return iter(self._evidence._ratings)

    def __len__(self) -> int:
        return len(self._evidence._ratings)

    def get(self, key: str, default: str | None = None) -> str | None:
        info = self._evidence._ratings.get(str(key))
        if info is None:
            return default
        return info["rating"]

    def items(self):  # type: ignore[override]
        for k, v in self._evidence._ratings.items():
            yield k, v["rating"]

    def __repr__(self) -> str:
        return repr(dict(self.items()))
