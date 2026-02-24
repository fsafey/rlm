"""Tool call tracking context manager — emits to EventBus or legacy callback."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator


def _compact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Compact tool args for SSE — strip large payloads."""
    compact: dict[str, Any] = {}
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


def _emit(ctx: Any, tool: str, phase: str, data: dict[str, Any], duration_ms: int = 0) -> None:
    """Emit tool progress — via EventBus if available, else legacy callback."""
    bus = getattr(ctx, "bus", None)
    if bus is not None:
        event_type = f"tool_{phase}"  # tool_start, tool_end, tool_error
        bus.emit(event_type, {"tool": tool, **(data or {}), "duration_ms": duration_ms})
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
