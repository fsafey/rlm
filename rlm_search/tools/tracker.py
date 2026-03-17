"""Tool call tracking context manager — emits to EventBus or legacy callback."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator


def _compact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Compact tool args for SSE — preserve full query text, summarize large payloads."""
    compact: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str):
            compact[k] = v
        elif isinstance(v, list):
            compact[k] = len(v)
        elif isinstance(v, dict):
            compact[k] = "..."
        else:
            compact[k] = v
    return compact


def _emit(ctx: Any, tool: str, phase: str, data: dict[str, Any], duration_ms: int = 0) -> None:
    """Emit tool progress — via EventBus if available, else legacy callback."""
    bus = getattr(ctx, "bus", None)
    if bus is not None:
        bus.emit("tool_progress", {"tool": tool, "phase": phase, "data": data or {}, "duration_ms": duration_ms})
        return
    # Legacy path: use progress_callback
    cb = getattr(ctx, "progress_callback", None)
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
    ctx: Any,
    tool_name: str,
    args: dict[str, Any],
    parent_idx: int | None = None,
) -> Generator:
    """Record a tool call entry in ``ctx.tool_calls`` and emit events.

    Yields a namespace object with ``entry``, ``idx``, and ``set_summary``.
    """
    entry: dict[str, Any] = {
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

    def set_summary(summary: dict[str, Any]) -> None:
        entry["result_summary"] = summary

    tc = type("_TC", (), {"entry": entry, "idx": idx, "set_summary": staticmethod(set_summary)})()

    start_data = _compact_args(args)
    start_data["idx"] = idx
    if parent_idx is not None:
        start_data["parent_idx"] = parent_idx
    _emit(ctx, tool_name, "start", start_data)

    start = time.time()
    try:
        yield tc
    except BaseException as exc:
        entry["duration_ms"] = int((time.time() - start) * 1000)
        entry["error"] = str(exc)
        error_data: dict[str, Any] = {"error": str(exc), "idx": idx}
        if parent_idx is not None:
            error_data["parent_idx"] = parent_idx
        _emit(ctx, tool_name, "error", error_data, duration_ms=entry["duration_ms"])
        raise
    else:
        entry["duration_ms"] = int((time.time() - start) * 1000)
        end_data = {**entry["result_summary"], "idx": idx}
        if parent_idx is not None:
            end_data["parent_idx"] = parent_idx
        if entry["children"]:
            end_data["children"] = entry["children"]
        _emit(ctx, tool_name, "end", end_data, duration_ms=entry["duration_ms"])
