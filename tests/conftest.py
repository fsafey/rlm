"""Shared pytest fixtures and hooks."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(scope="session")
def eval_results(request) -> list[Any]:
    """Mutable accumulator for classify eval results.

    Session-scoped so all eval tests share one list. Stored on config so the
    pytest_terminal_summary hook can read it without fixture injection.
    """
    results: list[Any] = []
    request.config._eval_results = results
    return results


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Print classify eval scoring table after the test run, if any eval tests ran."""
    results: list[Any] = getattr(config, "_eval_results", [])
    if not results:
        return

    tier_names = {1: "Direct", 2: "Semantic", 3: "Ambiguous"}
    tw = terminalreporter

    tw.write_sep("=", "Classify Eval Results")
    for tier in (1, 2, 3):
        tier_results = [r for r in results if r.tier == tier]
        if not tier_results:
            continue
        n_passed = sum(1 for r in tier_results if r.passed)
        total = len(tier_results)
        pct = int(n_passed / total * 100)
        tw.write_line(f"TIER {tier} ({tier_names[tier]:>8s}):  {n_passed}/{total}  ({pct}%)")

    all_passed = sum(1 for r in results if r.passed)
    all_total = len(results)
    all_pct = int(all_passed / all_total * 100) if all_total else 0
    tw.write_line(f"{'TOTAL':>18s}:  {all_passed}/{all_total}  ({all_pct}%)")

    failures = [r for r in results if not r.passed]
    if failures:
        tw.write_line("")
        tw.write_line("FAILURES:")
        for r in failures:
            tw.write_line(
                f"  [{r.tier}] {r.question[:60]}"
                f"\n      expected={r.expected_category}  got={r.got_category}"
                f"  confidence={r.got_confidence}  clusters={r.got_clusters!r}"
            )
