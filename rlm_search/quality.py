"""rlm_search/quality.py"""

from __future__ import annotations

import dataclasses
from typing import Any

from rlm_search.evidence import EvidenceStore
from rlm_search.prompt_constants import (
    EXPLORE_MIN_SEARCHES as _EXPLORE_MIN_SEARCHES,
)
from rlm_search.prompt_constants import (
    EXPLORE_SATURATION_THRESHOLD as _EXPLORE_SATURATION_THRESHOLD,
)
from rlm_search.prompt_constants import (
    MEDIUM_RELEVANT_MIN as _MEDIUM_RELEVANT_MIN,
)
from rlm_search.prompt_constants import (
    READY_THRESHOLD as _READY_THRESHOLD,
)
from rlm_search.prompt_constants import (
    STALL_SEARCH_COUNT as _STALL_SEARCH_COUNT,
)
from rlm_search.prompt_constants import (
    STRONG_CONFIDENCE_MIN as _STRONG_CONFIDENCE_MIN,
)
from rlm_search.prompt_constants import (
    STRONG_RELEVANT_MIN as _STRONG_RELEVANT_MIN,
)
from rlm_search.prompt_constants import (
    VELOCITY_DECAY as _VELOCITY_DECAY,
)
from rlm_search.prompt_constants import (
    VELOCITY_SATURATE as _VELOCITY_SATURATE,
)
from rlm_search.prompt_constants import (
    WEIGHT_BREADTH,
    WEIGHT_CRITIQUE,
    WEIGHT_DRAFT,
    WEIGHT_QUALITY,
    WEIGHT_RELEVANCE,
)


@dataclasses.dataclass
class QualityGate:
    """Owns confidence scoring, critique verdicts, and progress phase.

    Single source of truth for quality thresholds. The system prompt
    references these by name, not by numeric value.

    Replaces: progress_tools._compute_confidence(), scattered critique
    state, duplicated threshold constants in prompts.py.
    """

    evidence: EvidenceStore

    # --- Thresholds (defaulted from prompt_constants) ---
    READY_THRESHOLD: int = _READY_THRESHOLD
    STALL_SEARCH_COUNT: int = _STALL_SEARCH_COUNT

    # --- Mutable state ---
    _has_draft: bool = dataclasses.field(default=False, init=False)
    _draft_length: int = dataclasses.field(default=0, init=False)
    _last_critique: dict[str, Any] | None = dataclasses.field(default=None, init=False)

    # --- Explore phase tracking ---
    _search_yields: list[float] = dataclasses.field(default_factory=list, init=False)
    _explore_graduated: bool = dataclasses.field(default=False, init=False)

    def record_search_yield(self, new_unique: int) -> None:
        """Record how many new unique IDs a search batch produced."""
        self._search_yields.append(float(new_unique))

    @property
    def _info_velocity(self) -> float:
        """Exponentially-weighted new-ID rate. 0.0 = depleted, 1.0 = max novelty."""
        if not self._search_yields:
            return 1.0  # no data → assume high velocity
        n = len(self._search_yields)
        weights = [_VELOCITY_DECAY ** (n - 1 - i) for i in range(n)]
        weighted_sum = sum(y * w for y, w in zip(self._search_yields, weights, strict=True))
        weight_total = sum(weights)
        avg_yield = weighted_sum / weight_total
        return min(avg_yield / _VELOCITY_SATURATE, 1.0)

    @property
    def saturation_score(self) -> int:
        """Exploration saturation (0-100). High = territory well-mapped, time to converge.

        Three factors:
        - Velocity decay (45): inverted info velocity
        - Confidence (40): evidence quality
        - Search floor (15): minimum searches before explore can graduate.
        """
        n_searches = len(self.evidence.search_log)
        if n_searches == 0:
            return 0

        velocity_component = int(45 * (1.0 - self._info_velocity))
        confidence_component = int(40 * min(self.confidence / 100.0, 1.0))
        floor_component = int(15 * min(n_searches / _EXPLORE_MIN_SEARCHES, 1.0))

        return min(100, velocity_component + confidence_component + floor_component)

    # --- Draft tracking ---

    def record_draft(self, length: int) -> None:
        self._has_draft = True
        self._draft_length = length

    @property
    def has_draft(self) -> bool:
        return self._has_draft

    @property
    def draft_length(self) -> int:
        return self._draft_length

    # --- Critique tracking ---

    def record_critique(self, passed: bool, verdict: str) -> None:
        self._last_critique = {"passed": passed, "verdict": verdict}

    @property
    def last_critique(self) -> dict[str, Any] | None:
        return self._last_critique

    # --- Confidence (5-factor + critique bonus) ---

    @property
    def confidence(self) -> int:
        """Compute confidence score (0-100). Deterministic, from evidence state."""
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)
        partial = counts.get("PARTIAL", 0)
        total_rated = sum(counts.values())

        # Factor 1: Relevance
        if total_rated == 0:
            relevance_score = 0
        else:
            relevance_score = min(
                WEIGHT_RELEVANCE,
                int(WEIGHT_RELEVANCE * (relevant + 0.3 * partial) / max(total_rated, 1)),
            )

        # Factor 2: Top score quality
        top_score = 0.0
        for entry in self.evidence._registry.values():
            if entry.get("score", 0) > top_score:
                top_score = entry["score"]
        quality_score = min(WEIGHT_QUALITY, int(WEIGHT_QUALITY * top_score))

        # Factor 3: Breadth
        n_searches = len(self.evidence.search_log)
        breadth_score = min(WEIGHT_BREADTH, n_searches * 3)

        # Factor 4: Draft exists
        draft_score = WEIGHT_DRAFT if self._has_draft else 0

        # Factor 5: Critique outcome
        critique_score = 0
        if self._last_critique is not None:
            critique_score = WEIGHT_CRITIQUE if self._last_critique["passed"] else 5

        return min(
            100, relevance_score + quality_score + breadth_score + draft_score + critique_score
        )

    @property
    def critique_tier(self) -> str:
        """Advise draft_answer on critique depth based on evidence quality.

        Returns:
            'strong' — programmatic citation check only (skip LLM critique)
            'medium' — focused LLM critique (voice + attribution), no revision loop
            'weak'   — full critique + revision (status quo)
        """
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)

        if relevant >= _STRONG_RELEVANT_MIN and self.confidence >= _STRONG_CONFIDENCE_MIN:
            return "strong"
        if relevant >= _MEDIUM_RELEVANT_MIN:
            return "medium"
        return "weak"

    # --- Phase ---

    @property
    def phase(self) -> str:
        """Determine current search phase from evidence state.

        Phase progression: explore → continue → ready → finalize
        Stalled overrides explore (don't explore a desert).
        """
        n_searches = len(self.evidence.search_log)
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)

        if n_searches >= self.STALL_SEARCH_COUNT and relevant < 2:
            return "stalled"

        # Explore phase: at least 1 search, not yet graduated, below saturation
        if not self._explore_graduated and n_searches > 0:
            if self.saturation_score >= _EXPLORE_SATURATION_THRESHOLD:
                self._explore_graduated = True
                # Fall through to continue/ready/finalize
            else:
                return "explore"

        conf = self.confidence
        if conf >= self.READY_THRESHOLD:
            if self._has_draft and self._last_critique and self._last_critique["passed"]:
                return "finalize"
            return "ready"

        return "continue"

    # --- Guidance (copy-paste-ready next steps for LM) ---

    def guidance(self) -> str:
        """Return guidance string for the LM based on current phase."""
        p = self.phase
        if p == "explore":
            sat = self.saturation_score
            return (
                f"Explore phase (saturation {sat}%). "
                "Run broad research() with diverse query angles and varied filters. "
                "Do NOT draft yet — map the territory first."
            )
        if p == "stalled":
            return (
                "Evidence insufficient after multiple searches."
                " Try reformulate() or broaden filters."
            )
        if p == "ready":
            return "Evidence sufficient. Call draft_answer() to synthesize."
        if p == "finalize":
            return "Draft passed critique. Call FINAL_VAR(answer) to deliver."
        # continue
        counts = self.evidence.rating_counts()
        relevant = counts.get("RELEVANT", 0)
        if relevant == 0:
            return "No relevant results yet. Try different query angles or broader filters."
        return (
            f"{relevant} relevant sources found."
            " Continue searching for more evidence or draft if confident."
        )
