"""rlm_search/evidence.py"""

from __future__ import annotations

import dataclasses
from typing import Any

RATING_ORDER = {"RELEVANT": 0, "PARTIAL": 1, "OFF-TOPIC": 2, "UNKNOWN": 3}


@dataclasses.dataclass
class EvidenceStore:
    """Owns source_registry, search_log, and evaluated_ratings.

    Single writer protocol: all mutations go through methods.
    Replaces the scattered writes across normalize_hit, delegation merge,
    and StreamingLogger snapshot polling.
    """

    _registry: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    _ratings: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    _search_log: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    # --- Registration ---

    def register_hit(self, hit: dict[str, Any]) -> str:
        """Register a search hit. Deduplicates by id, keeps higher score."""
        hit_id = str(hit["id"])
        existing = self._registry.get(hit_id)
        if existing is None or hit.get("score", 0) > existing.get("score", 0):
            self._registry[hit_id] = {
                "id": hit_id,
                "question": hit.get("question", ""),
                "answer": hit.get("answer", ""),
                "score": hit.get("score", 0),
                "metadata": hit.get("metadata", {}),
            }
        return hit_id

    def get(self, hit_id: str) -> dict[str, Any] | None:
        return self._registry.get(str(hit_id))

    @property
    def count(self) -> int:
        return len(self._registry)

    # --- Search log ---

    def log_search(
        self,
        query: str,
        num_results: int,
        filters: dict[str, Any] | None = None,
        search_type: str = "search",
    ) -> None:
        self._search_log.append(
            {
                "type": search_type,
                "query": query,
                "num_results": num_results,
                "filters": filters or {},
            }
        )

    @property
    def search_log(self) -> list[dict[str, Any]]:
        return self._search_log

    # --- Ratings ---

    def set_rating(self, hit_id: str, rating: str, confidence: int = 0) -> None:
        self._ratings[str(hit_id)] = {"rating": rating, "confidence": confidence}

    def get_rating(self, hit_id: str) -> dict[str, Any] | None:
        return self._ratings.get(str(hit_id))

    def rating_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._ratings.values():
            rating = r["rating"]
            counts[rating] = counts.get(rating, 0) + 1
        return counts

    # --- Evidence retrieval ---

    def get_evidence(self, hit_ids: list[str]) -> list[dict[str, Any]]:
        """Get registry entries for specific IDs, preserving order."""
        return [self._registry[str(hid)] for hid in hit_ids if str(hid) in self._registry]

    def top_rated(self, n: int = 10) -> list[dict[str, Any]]:
        """Return top N hits sorted by rating tier then confidence."""
        rated = []
        for hit_id, rating_info in self._ratings.items():
            hit = self._registry.get(hit_id)
            if hit is None:
                continue
            rated.append(
                {
                    **hit,
                    "_rating": rating_info["rating"],
                    "_confidence": rating_info["confidence"],
                }
            )
        rated.sort(key=lambda h: (RATING_ORDER.get(h["_rating"], 99), -h["_confidence"]))
        return [{k: v for k, v in h.items() if not k.startswith("_")} for h in rated[:n]]

    # --- Merge (for child delegation) ---

    def merge(self, child: EvidenceStore) -> None:
        """Merge a child store into this one. Higher scores win on conflict."""
        for _hit_id, hit in child._registry.items():
            self.register_hit(hit)
        for hit_id, rating in child._ratings.items():
            if hit_id not in self._ratings:
                self._ratings[hit_id] = rating

    # --- REPL compatibility ---

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """Snapshot copy for serialization or logging."""
        return dict(self._registry)

    @property
    def live_dict(self) -> dict[str, dict[str, Any]]:
        """Live reference for REPL locals -- LM sees tool writes immediately.

        IMPORTANT: The current source_registry = _ctx.source_registry is a live
        dict reference. Tools write via normalize_hit(), LM reads via
        print(source_registry). Using as_dict() here would break this contract
        because it returns a copy. Expose _registry directly so mutations from
        register_hit() are visible to the LM without re-assignment.

        The LM should NOT write to this dict directly -- use register_hit().
        """
        return self._registry
