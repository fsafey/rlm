"""rlm_search/sse.py"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from rlm_search.bus import EventBus


def create_sse_router(searches: dict[str, EventBus]) -> APIRouter:
    """Create SSE streaming router.

    Reads from EventBus instead of StreamingLogger.drain().
    Supports replay for reconnection.
    """
    router = APIRouter()

    @router.get("/api/search/{search_id}/stream")
    async def stream_search(
        search_id: str,
        request: Request,
        replay: bool = Query(default=False),
    ) -> StreamingResponse:
        if search_id not in searches:
            raise HTTPException(status_code=404, detail="Search not found")

        bus = searches[search_id]

        async def event_generator():
            deadline = time.monotonic() + 600  # 10 min max
            last_sent = time.monotonic()

            # Replay: send all historical events first
            if replay:
                for event in bus.replay():
                    yield f"data: {json.dumps(event)}\n\n"
                    last_sent = time.monotonic()
                    if event.get("type") in ("done", "error", "cancelled"):
                        searches.pop(search_id, None)
                        return
                # Discard queued events already covered by replay
                bus.drain()

            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    bus.cancel()
                    searches.pop(search_id, None)
                    return

                events = bus.drain()
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                    last_sent = time.monotonic()
                    if event.get("type") in ("done", "error", "cancelled"):
                        searches.pop(search_id, None)
                        return

                if time.monotonic() - last_sent >= 15:
                    yield ": keepalive\n\n"
                    last_sent = time.monotonic()

                await asyncio.sleep(0.1)  # 100ms poll (down from 200ms)

            searches.pop(search_id, None)
            yield (
                f"data: {json.dumps({'type': 'error', 'data': {'message': 'Search timed out'}})}"
                "\n\n"
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
