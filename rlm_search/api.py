"""FastAPI backend for RLM agentic search."""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
    _PROJECT_ROOT,
    ANTHROPIC_API_KEY,
    CASCADE_API_KEY,
    CASCADE_API_URL,
    RLM_BACKEND,
    RLM_MAX_DEPTH,
    RLM_MAX_ITERATIONS,
    RLM_MODEL,
)
from rlm_search.kb_overview import build_kb_overview
from rlm_search.models import HealthResponse, SearchRequest, SearchResponse
from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT
from rlm_search.repl_tools import build_search_setup_code
from rlm_search.streaming_logger import SearchCancelled, StreamingLogger

_log = logging.getLogger("rlm_search")

# Cached KB overview — built once at startup, shared across searches
_kb_overview_cache: dict | None = None


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

    global _kb_overview_cache

    # Cascade API health check at startup
    status, url = await _check_cascade_health()
    _app.state.cascade_url = url if status == "connected" else None
    if status == "connected":
        _log.info("Cascade API at %s is reachable.", url)
        # Build KB overview from Cascade facets
        _kb_overview_cache = await build_kb_overview(url, CASCADE_API_KEY)
        if _kb_overview_cache:
            n_cats = len(_kb_overview_cache.get("categories", {}))
            n_docs = _kb_overview_cache.get("total_documents", 0)
            _log.info("KB overview built: %d categories, %d total docs", n_cats, n_docs)
        else:
            _log.warning("KB overview build returned None — searches will proceed without it.")
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

_SOURCE_PATTERN = re.compile(r"\[Source:\s*(\d+)\]")


def _extract_sources(answer: str, registry: dict[str, dict] | None = None) -> list[dict]:
    """Extract unique source IDs from [Source: XXXX] references and enrich with metadata."""
    ids = list(dict.fromkeys(_SOURCE_PATTERN.findall(answer)))
    sources = []
    for sid in ids:
        entry = (registry or {}).get(sid)
        if entry and isinstance(entry, dict):
            sources.append(entry)
        else:
            sources.append({"id": sid})
    return sources


def _backfill_tool_calls(iterations: list[dict]) -> None:
    """Backfill top-level ``tool_calls`` for old log iterations that lack it.

    Old log files wrote ``iteration.to_dict()`` which stores tool_calls inside
    ``code_blocks[-1].result.locals.tool_calls``.  We extract delta tool_calls
    per iteration (matching the live SSE logic) and inject them at the top level.
    Mutates *iterations* in-place.
    """
    last_count = 0
    for iteration in iterations:
        if "tool_calls" in iteration:
            # Already has top-level tool_calls — fast-forward the counter so
            # subsequent old iterations (unlikely but safe) compute correct deltas.
            last_count += len(iteration["tool_calls"])
            continue

        # Find the cumulative tool_calls list from any code block's locals.
        # All blocks share the same list reference, so grab the last one found.
        cumulative: list[dict] | None = None
        code_blocks = iteration.get("code_blocks", [])
        for block in code_blocks:
            tc = block.get("result", {}).get("locals", {}).get("tool_calls")
            if isinstance(tc, list):
                cumulative = tc

        # Compute delta once (not per-block) then advance the counter
        if cumulative is not None:
            iteration["tool_calls"] = cumulative[last_count:]
            last_count = len(cumulative)
        else:
            iteration["tool_calls"] = []


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
            kb_overview_data=_kb_overview_cache,
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

        result = rlm.completion(query, root_prompt=query)
        print(
            f"[SEARCH:{search_id}] Completed | answer_len={len(result.response or '')} time={result.execution_time:.2f}s"
        )

        sources = _extract_sources(result.response or "", logger.source_registry)
        usage = result.usage_summary.to_dict() if result.usage_summary else {}

        logger.mark_done(
            answer=result.response,
            sources=sources,
            execution_time=result.execution_time,
            usage=usage,
        )

    except SearchCancelled:
        print(f"[SEARCH:{search_id}] Cancelled by client")
        logger.mark_done(answer=None, sources=[], execution_time=0.0, usage={})

    except Exception as e:
        print(f"[SEARCH:{search_id}] ERROR | {type(e).__name__}: {e}")
        logger.mark_error(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


@app.post("/api/search", response_model=SearchResponse)
async def start_search(req: SearchRequest) -> SearchResponse:
    search_id = str(uuid.uuid4())[:12]
    print(f"[API] POST /api/search | id={search_id} query={req.query!r}")
    logger = StreamingLogger(
        log_dir=str(_PROJECT_ROOT / "rlm_logs"),
        file_name=f"search_{search_id}",
        search_id=search_id,
        query=req.query,
    )
    _searches[search_id] = logger

    settings = req.settings.model_dump() if req.settings else {}
    _executor.submit(_run_search, search_id, req.query, settings)

    return SearchResponse(search_id=search_id)


@app.post("/api/search/{search_id}/cancel")
async def cancel_search(search_id: str) -> dict:
    print(f"[API] POST /api/search/{search_id}/cancel | found={search_id in _searches}")
    logger = _searches.get(search_id)
    if not logger:
        raise HTTPException(status_code=404, detail="Search not found")
    logger.cancel()
    return {"status": "cancelled"}


@app.get("/api/search/{search_id}/stream")
async def stream_search(search_id: str) -> StreamingResponse:
    print(f"[API] GET /api/search/{search_id}/stream | found={search_id in _searches}")
    if search_id not in _searches:
        raise HTTPException(status_code=404, detail="Search not found")

    logger = _searches[search_id]

    async def event_generator():
        deadline = time.monotonic() + 600  # 10 minute max
        last_sent = time.monotonic()
        while time.monotonic() < deadline:
            events = logger.drain()
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                last_sent = time.monotonic()
                if event.get("type") in ("done", "error"):
                    _searches.pop(search_id, None)
                    return
            if time.monotonic() - last_sent >= 15:
                yield ": keepalive\n\n"
                last_sent = time.monotonic()
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


@app.get("/api/logs/recent")
async def list_recent_logs(limit: int = 20) -> list[dict]:
    """List recent search logs with metadata (query, timestamp, search_id)."""
    log_dir = _PROJECT_ROOT / "rlm_logs"
    if not log_dir.exists():
        return []
    files = sorted(log_dir.glob("search_*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    results = []
    for f in files[:limit]:
        try:
            with open(f) as fh:
                first_line = fh.readline().strip()
            if not first_line:
                continue
            meta = json.loads(first_line)
            results.append(
                {
                    "filename": f.name,
                    "search_id": meta.get("search_id", ""),
                    "query": meta.get("query", ""),
                    "timestamp": meta.get("timestamp", ""),
                    "root_model": meta.get("root_model", ""),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return results


@app.get("/api/logs/{search_id}")
async def get_log(search_id: str) -> dict:
    """Load a completed search log by search_id prefix match."""
    log_dir = _PROJECT_ROOT / "rlm_logs"
    if not log_dir.exists():
        raise HTTPException(status_code=404, detail="No logs directory")
    # Match by search_id prefix in filename
    matches = list(log_dir.glob(f"search_{search_id}*.jsonl"))
    if not matches:
        raise HTTPException(status_code=404, detail="Log not found")
    log_file = max(matches, key=lambda f: f.stat().st_mtime)
    events: list[dict] = []
    with open(log_file) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not events:
        raise HTTPException(status_code=404, detail="Empty log file")
    # Separate by type
    metadata = next((e for e in events if e.get("type") == "metadata"), None)
    iterations = [e for e in events if e.get("type") == "iteration"]
    done = next((e for e in events if e.get("type") == "done"), None)
    error = next((e for e in events if e.get("type") == "error"), None)

    # Backfill tool_calls for old log files that lack top-level tool_calls
    _backfill_tool_calls(iterations)

    return {
        "metadata": metadata,
        "iterations": iterations,
        "done": done,
        "error": error,
        "filename": log_file.name,
    }


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
