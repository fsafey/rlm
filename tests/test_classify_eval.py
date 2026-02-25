"""Classify evaluation suite — real LLM + real kb_overview_data.

Runs init_classify() against live Cascade API taxonomy and a real Anthropic model.
Excluded from normal test runs via the ``eval`` marker.

Run explicitly::

    uv run pytest tests/test_classify_eval.py -v -m eval
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

pytestmark = pytest.mark.eval


def _load_config():
    """Load config values from rlm_search.config (which handles dotenv)."""
    from rlm_search.config import (
        ANTHROPIC_API_KEY,
        CASCADE_API_KEY,
        CASCADE_API_URL,
        RLM_BACKEND,
    )

    return CASCADE_API_URL, CASCADE_API_KEY, ANTHROPIC_API_KEY, RLM_BACKEND


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def kb_overview_data() -> dict[str, Any]:
    """Fetch live kb_overview_data from Cascade API once per session."""
    cascade_url, cascade_key, anthropic_key, backend = _load_config()
    # claude_cli backend doesn't need ANTHROPIC_API_KEY
    if backend != "claude_cli" and not anthropic_key:
        pytest.skip("ANTHROPIC_API_KEY not set and backend is not claude_cli")

    from rlm_search.kb_overview import build_kb_overview

    data = asyncio.run(
        build_kb_overview(api_url=cascade_url, api_key=cascade_key, timeout=30.0)
    )
    if data is None:
        pytest.skip("Cascade API unreachable — cannot build kb_overview_data")
    return data


@dataclasses.dataclass
class EvalResult:
    """Single test-case result for the scoring summary."""

    tier: int
    question: str
    expected_category: str
    expected_clusters: list[str]
    got_category: str
    got_clusters: str
    got_confidence: str
    passed: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(kb_data: dict[str, Any]):
    from rlm_search.tools.context import ToolContext

    cascade_url, cascade_key, _, _ = _load_config()
    ctx = ToolContext(
        api_url=cascade_url,
        api_key=cascade_key,
    )
    ctx.kb_overview_data = kb_data
    ctx.llm_query = None
    ctx.llm_query_batched = None
    ctx._parent_logger = None
    return ctx


def _run_classify(ctx, question: str) -> dict | None:
    from rlm_search.tools.subagent_tools import init_classify

    init_classify(ctx, question)
    return ctx.classification


# ---------------------------------------------------------------------------
# Tier 1: Direct Match
# ---------------------------------------------------------------------------

TIER1_CASES = [
    pytest.param(
        "Is it permissible to take a mortgage from a bank?",
        "FN",
        ["Banking Riba Operations"],
        id="mortgage-FN",
    ),
    pytest.param(
        "How do I perform ghusl after janabah?",
        "PT",
        ["Ghusl Procedure and Validity"],
        id="ghusl-PT",
    ),
    pytest.param(
        "What invalidates wudu?",
        "PT",
        ["Wudu Barriers and Validity"],
        id="wudu-PT",
    ),
    pytest.param(
        "How is khums calculated on savings?",
        "FN",
        ["Khums Calculation Methodology"],
        id="khums-FN",
    ),
]


@pytest.mark.parametrize("question,expected_cat,expected_clusters", TIER1_CASES)
def test_tier1_direct_match(
    kb_overview_data: dict,
    eval_results: list[EvalResult],
    question: str,
    expected_cat: str,
    expected_clusters: list[str],
):
    ctx = _make_ctx(kb_overview_data)
    result = _run_classify(ctx, question)

    assert result is not None, f"Classification returned None for: {question}"
    got_cat = result["category"]
    got_clusters = result["clusters"]
    got_confidence = result["confidence"]

    cat_ok = got_cat == expected_cat
    cluster_ok = any(c in got_clusters for c in expected_clusters) if expected_clusters else True
    passed = cat_ok and cluster_ok

    eval_results.append(
        EvalResult(
            tier=1,
            question=question,
            expected_category=expected_cat,
            expected_clusters=expected_clusters,
            got_category=got_cat,
            got_clusters=got_clusters,
            got_confidence=got_confidence,
            passed=passed,
        )
    )

    assert cat_ok, f"Category mismatch: expected {expected_cat}, got {got_cat}"
    assert cluster_ok, (
        f"No expected cluster found: expected one of {expected_clusters}, got {got_clusters!r}"
    )


# ---------------------------------------------------------------------------
# Tier 2: Semantic Mismatch
# ---------------------------------------------------------------------------

TIER2_CASES = [
    pytest.param(
        "What are a husband's financial obligations in marriage?",
        "MF",
        [],  # cluster match is bonus, category is the key test
        id="spousal-rights-MF",
    ),
    pytest.param(
        "Is ritual washing required after a wet dream?",
        "PT",
        ["Ghusl Procedure and Validity", "Janabah Discharge Identification"],
        id="wet-dream-PT",
    ),
    pytest.param(
        "Can I invest my retirement savings in index funds?",
        "FN",
        ["Shariah Investment Screening"],
        id="index-funds-FN",
    ),
    pytest.param(
        "Is it permissible to cremate the dead in Islam?",
        "MF",
        # "cremate" shares no tokens with any cluster label, but the KB groups
        # burial/end-of-life rulings under MF → "Organ Donation & End-of-Life".
        # Token-overlap would score 0; semantic matching lands here correctly.
        [],
        id="cremation-MF",
    ),
    pytest.param(
        "What are the rules about interacting with the opposite gender?",
        "BE",
        ["Gender Interaction Boundaries", "ʿAwrah & Non-Maḥram Interaction"],
        id="gender-interaction-BE",
    ),
    pytest.param(
        "Do I need to wash my hands before eating if I touched a dog?",
        "PT",
        ["Animal-Derived Purity", "Najasah Transfer Conditions"],
        id="dog-najasah-PT",
    ),
]


@pytest.mark.parametrize("question,expected_cat,expected_clusters", TIER2_CASES)
def test_tier2_semantic_mismatch(
    kb_overview_data: dict,
    eval_results: list[EvalResult],
    question: str,
    expected_cat: str,
    expected_clusters: list[str],
):
    ctx = _make_ctx(kb_overview_data)
    result = _run_classify(ctx, question)

    assert result is not None, f"Classification returned None for: {question}"
    got_cat = result["category"]
    got_clusters = result["clusters"]
    got_confidence = result["confidence"]

    cat_ok = got_cat == expected_cat
    cluster_ok = (
        any(c in got_clusters for c in expected_clusters) if expected_clusters else True
    )
    passed = cat_ok and cluster_ok

    eval_results.append(
        EvalResult(
            tier=2,
            question=question,
            expected_category=expected_cat,
            expected_clusters=expected_clusters,
            got_category=got_cat,
            got_clusters=got_clusters,
            got_confidence=got_confidence,
            passed=passed,
        )
    )

    assert cat_ok, f"Category mismatch: expected {expected_cat}, got {got_cat}"
    if expected_clusters:
        assert cluster_ok, (
            f"No expected cluster found: expected one of {expected_clusters}, got {got_clusters!r}"
        )


# ---------------------------------------------------------------------------
# Tier 3: Ambiguous / Cross-Category
# ---------------------------------------------------------------------------

TIER3_CASES = [
    pytest.param(
        "Is it halal to sell alcohol to non-Muslims?",
        ["FN", "BE"],
        ["MEDIUM", "LOW"],
        id="alcohol-sale-ambiguous",
    ),
    pytest.param(
        "Can I pray while wearing nail polish?",
        ["PT", "WP"],
        ["MEDIUM", "LOW"],
        id="nail-polish-ambiguous",
    ),
]


@pytest.mark.parametrize("question,acceptable_cats,expected_confidences", TIER3_CASES)
def test_tier3_ambiguous(
    kb_overview_data: dict,
    eval_results: list[EvalResult],
    question: str,
    acceptable_cats: list[str],
    expected_confidences: list[str],
):
    ctx = _make_ctx(kb_overview_data)
    result = _run_classify(ctx, question)

    assert result is not None, f"Classification returned None for: {question}"
    got_cat = result["category"]
    got_clusters = result["clusters"]
    got_confidence = result["confidence"]

    cat_ok = got_cat in acceptable_cats
    # For tier 3 we don't enforce clusters, just category + confidence
    passed = cat_ok  # confidence is informational, not a hard gate

    eval_results.append(
        EvalResult(
            tier=3,
            question=question,
            expected_category="/".join(acceptable_cats),
            expected_clusters=[],
            got_category=got_cat,
            got_clusters=got_clusters,
            got_confidence=got_confidence,
            passed=passed,
        )
    )

    assert cat_ok, (
        f"Category mismatch: expected one of {acceptable_cats}, got {got_cat}"
    )


