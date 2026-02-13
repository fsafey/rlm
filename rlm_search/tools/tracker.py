"""Tool call tracking context manager."""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from rlm_search.tools.context import ToolContext


@contextlib.contextmanager
def tool_call_tracker(
    ctx: ToolContext,
    tool_name: str,
    args: dict,
    parent_idx: int | None = None,
) -> Generator:
    """Record a tool call entry in ``ctx.tool_calls``.

    Yields a namespace object with ``entry``, ``idx``, and ``set_summary``.
    """
    entry: dict = {
        "tool": tool_name,
        "args": args,
        "result_summary": {},
        "duration_ms": 0,
        "children": [],
        "error": None,
    }
    ctx.tool_calls.append(entry)
    idx = len(ctx.tool_calls) - 1
    if parent_idx is not None:
        ctx.tool_calls[parent_idx]["children"].append(idx)

    def set_summary(summary: dict) -> None:
        entry["result_summary"] = summary

    tc = type("_TC", (), {"entry": entry, "idx": idx, "set_summary": staticmethod(set_summary)})()

    start = time.time()
    try:
        yield tc
    except BaseException as exc:
        entry["duration_ms"] = int((time.time() - start) * 1000)
        entry["error"] = str(exc)
        raise
    else:
        entry["duration_ms"] = int((time.time() - start) * 1000)
