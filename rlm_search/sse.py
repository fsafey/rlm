"""rlm_search/sse.py — push-based SSE streaming with always-replay."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from rlm_search.bus import TERMINAL_EVENTS, EventBus


def _flatten(event: dict) -> dict:
    """Flatten bus envelope into a single-level dict matching JSONL format.

    Bus stores: {"type": "...", "data": {...}, "timestamp": "..."}
    Frontend expects: {"type": "...", "timestamp": "...", ...data fields...}
    """
    return {"type": event["type"], "timestamp": event["timestamp"], **event.get("data", {})}


def create_sse_router(searches: dict[str, EventBus]) -> APIRouter:
    """Create SSE streaming router with push-based event delivery."""
    router = APIRouter()

    @router.get("/api/search/{search_id}/stream")
    async def stream_search(search_id: str, request: Request) -> StreamingResponse:
        if search_id not in searches:
            raise HTTPException(status_code=404, detail="Search not found")

        bus = searches[search_id]

        async def event_generator():
            deadline = time.monotonic() + 600  # 10 min max

            # Atomically bind queue + snapshot history (no gap, no duplicates)
            history = bus.bind_and_replay(asyncio.get_running_loop())

            # Phase 1: replay all historical events
            for event in history:
                yield f"event: {event['type']}\ndata: {json.dumps(_flatten(event))}\n\n"
                if event["type"] in TERMINAL_EVENTS:
                    searches.pop(search_id, None)
                    return

            # Phase 2: live push from async queue
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    bus.cancel()
                    searches.pop(search_id, None)
                    return

                event = await bus.next_event(timeout=15.0)
                if event is None:
                    yield ": keepalive\n\n"
                    continue

                yield f"event: {event['type']}\ndata: {json.dumps(_flatten(event))}\n\n"
                if event["type"] in TERMINAL_EVENTS:
                    searches.pop(search_id, None)
                    return

            searches.pop(search_id, None)
            yield (
                f"event: error\n"
                f"data: {json.dumps({'type': 'error', 'message': 'Search timed out'})}\n\n"
            )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
