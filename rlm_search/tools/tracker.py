"""Tool call tracking context manager."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from rlm_search.tools.context import ToolContext


def _compact_args(args: dict) -> dict:
    """Compact tool args for SSE — strip large payloads."""
    compact: dict = {}
    for k, v in args.items():
        if isinstance(v, str):
            compact[k] = v[:100] if len(v) > 100 else v
        elif isinstance(v, list):
            compact[k] = len(v)
        elif isinstance(v, dict):
            compact[k] = "..."
        else:
            compact[k] = v
    return compact


def _emit(ctx: ToolContext, tool: str, phase: str, data: dict, duration_ms: int = 0) -> None:
    """Safely call the progress callback if available."""
    cb = ctx.progress_callback
    if cb is None:
        return
    try:
        cb(tool, phase, data, duration_ms=duration_ms)
    except Exception:
        logging.getLogger("rlm_search").debug(
            "progress callback failed for %s:%s", tool, phase, exc_info=True
        )


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

    _emit(ctx, tool_name, "start", _compact_args(args))

    start = time.time()
    try:
        yield tc
    except BaseException as exc:
        entry["duration_ms"] = int((time.time() - start) * 1000)
        entry["error"] = str(exc)
        _emit(ctx, tool_name, "error", {"error": str(exc)}, duration_ms=entry["duration_ms"])
        raise
    else:
        entry["duration_ms"] = int((time.time() - start) * 1000)
        _emit(ctx, tool_name, "end", entry["result_summary"], duration_ms=entry["duration_ms"])
