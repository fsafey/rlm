"""FastAPI backend for RLM agentic search."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from rlm.core.rlm import RLM
from rlm_search.config import (
    ANTHROPIC_API_KEY,
    CASCADE_API_KEY,
    CASCADE_API_URL,
    RLM_BACKEND,
    RLM_MAX_DEPTH,
    RLM_MAX_ITERATIONS,
    RLM_MODEL,
)
from rlm_search.models import HealthResponse, SearchRequest, SearchResponse
from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT
from rlm_search.repl_tools import build_search_setup_code
from rlm_search.streaming_logger import StreamingLogger

_log = logging.getLogger("rlm_search")


async def _check_cascade_health(
    cascade_url: str | None = None,
) -> tuple[str, str | None]:
    """Probe the Cascade API and return (status, url).

    Returns ("connected", url) on success, ("unreachable", url) on failure.
    """
    url = cascade_url or CASCADE_API_URL
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{url}/health")
            resp.raise_for_status()
    except (httpx.HTTPError, httpx.ConnectError, OSError):
        return "unreachable", url

    return "connected", url


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle — Cascade health check + stale search cleanup."""

    # Cascade API health check at startup
    status, url = await _check_cascade_health()
    _app.state.cascade_url = url if status == "connected" else None
    if status == "connected":
        _log.info("Cascade API at %s is reachable.", url)
    else:
        _log.warning(
            "Cascade API at %s is not reachable. "
            "Search requests will fail until the API is available.",
            url,
        )

    async def _cleanup_stale() -> None:
        while True:
            await asyncio.sleep(300)
            stale = [sid for sid, lg in _searches.items() if lg.is_done]
            for sid in stale:
                _searches.pop(sid, None)

    task = asyncio.create_task(_cleanup_stale())
    yield
    task.cancel()


app = FastAPI(title="RLM Agentic Search", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active searches: search_id -> StreamingLogger
_searches: dict[str, StreamingLogger] = {}
_executor = ThreadPoolExecutor(max_workers=4)


def _run_search(search_id: str, query: str, settings: dict[str, Any]) -> None:
    """Run an RLM completion in a thread. Pushes events to the StreamingLogger."""
    logger = _searches[search_id]
    backend = settings.get("backend") or RLM_BACKEND
    model = settings.get("model") or RLM_MODEL
    max_iterations = settings.get("max_iterations") or RLM_MAX_ITERATIONS
    max_depth = settings.get("max_depth") or RLM_MAX_DEPTH
    print(f"[SEARCH:{search_id}] Starting | query={query!r} backend={backend} model={model}")

    try:
        setup_code = build_search_setup_code(
            api_url=CASCADE_API_URL,
            api_key=CASCADE_API_KEY,
        )

        if backend == "claude_cli":
            backend_kwargs: dict[str, Any] = {"model": model}
        else:
            backend_kwargs: dict[str, Any] = {"model_name": model}
            if ANTHROPIC_API_KEY:
                backend_kwargs["api_key"] = ANTHROPIC_API_KEY

        rlm = RLM(
            backend=backend,
            backend_kwargs=backend_kwargs,
            environment="local",
            environment_kwargs={"setup_code": setup_code},
            max_iterations=max_iterations,
            max_depth=max_depth,
            custom_system_prompt=AGENTIC_SEARCH_SYSTEM_PROMPT,
            logger=logger,
        )
        print(
            f"[SEARCH:{search_id}] RLM initialized | max_iter={max_iterations} max_depth={max_depth}"
        )

        # Single progress event after all setup is done — the real wait is the LLM call next
        model_short = model.rsplit("-", 1)[0] if len(model.split("-")) > 3 else model
        logger.emit_progress("reasoning", f"Analyzing your question with {model_short}")

        result = rlm.completion(query)
        print(
            f"[SEARCH:{search_id}] Completed | answer_len={len(result.response or '')} time={result.execution_time:.2f}s"
        )

        # TODO: REPL environment is cleaned up before we can access search_log.
        # Source info is visible in iteration SSE events via [search] print lines.
        sources: list[dict] = []
        usage = result.usage_summary.to_dict() if result.usage_summary else {}

        logger.mark_done(
            answer=result.response,
            sources=sources,
            execution_time=result.execution_time,
            usage=usage,
        )

    except Exception as e:
        print(f"[SEARCH:{search_id}] ERROR | {type(e).__name__}: {e}")
        logger.mark_error(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


@app.post("/api/search", response_model=SearchResponse)
async def start_search(req: SearchRequest) -> SearchResponse:
    search_id = str(uuid.uuid4())[:12]
    print(f"[API] POST /api/search | id={search_id} query={req.query!r}")
    logger = StreamingLogger(log_dir="/tmp/rlm_search_logs", file_name=f"search_{search_id}")
    _searches[search_id] = logger

    settings = req.settings.model_dump() if req.settings else {}
    _executor.submit(_run_search, search_id, req.query, settings)

    return SearchResponse(search_id=search_id)


@app.get("/api/search/{search_id}/stream")
async def stream_search(search_id: str) -> StreamingResponse:
    print(f"[API] GET /api/search/{search_id}/stream | found={search_id in _searches}")
    if search_id not in _searches:
        raise HTTPException(status_code=404, detail="Search not found")

    logger = _searches[search_id]

    async def event_generator():
        deadline = time.monotonic() + 600  # 10 minute max
        while time.monotonic() < deadline:
            events = logger.drain()
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    _searches.pop(search_id, None)
                    return
            await asyncio.sleep(0.2)
        # Timed out — clean up
        _searches.pop(search_id, None)
        yield f"data: {json.dumps({'type': 'error', 'message': 'Search timed out'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    cached_url: str | None = getattr(request.app.state, "cascade_url", None)
    status, url = await _check_cascade_health(cascade_url=cached_url)
    if status == "connected":
        return HealthResponse(status="ok", cascade_api="connected", cascade_url=url)
    return HealthResponse(
        status="degraded",
        cascade_api="unreachable",
        cascade_url=url or CASCADE_API_URL,
    )
