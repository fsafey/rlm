"""Hit normalization for Cascade API responses."""

from __future__ import annotations

from rlm_search.tools.constants import META_FIELDS


def normalize_hit(hit: dict, source_registry: dict) -> dict:
    """Normalize a Cascade API hit into ``{id, score, question, answer, metadata}``.

    Preserves ``text`` for risala passages (which use ``text`` instead of
    ``question``/``answer``). Also registers the result in *source_registry*
    (keyed by string ID).
    """
    result: dict = {
        "id": str(hit.get("id", "")),
        "score": hit.get("score", hit.get("relevance_score", 0.0)),
        "question": hit.get("question", ""),
        "answer": hit.get("answer", ""),
    }
    # Risala passages carry content in "text", not "question"/"answer"
    if hit.get("text") and not result["question"]:
        result["text"] = hit["text"]
    metadata: dict = {}
    for k, v in hit.items():
        if k in META_FIELDS and v is not None:
            metadata[k] = v
    if metadata:
        result["metadata"] = metadata
    source_registry[result["id"]] = result
    return result
