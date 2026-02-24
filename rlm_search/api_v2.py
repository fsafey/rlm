"""FastAPI backend v2 — department-model architecture with EventBus."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import threading
import time
import traceback
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from rlm.core.rlm import RLM
from rlm.core.types import RLMMetadata
from rlm.utils.rlm_utils import filter_sensitive_keys
from rlm_search.bus import EventBus, SearchCancelled
from rlm_search.config import (
    _PROJECT_ROOT,
    ANTHROPIC_API_KEY,
    CASCADE_API_KEY,
    CASCADE_API_URL,
    RLM_BACKEND,
    RLM_CLASSIFY_MODEL,
    RLM_MAX_DELEGATION_DEPTH,
    RLM_MAX_DEPTH,
    RLM_MAX_ITERATIONS,
    RLM_MODEL,
    RLM_SUB_ITERATIONS,
    RLM_SUB_MODEL,
    SEARCH_API_KEY,
    SESSION_TIMEOUT,
)
from rlm_search.kb_overview import build_kb_overview
from rlm_search.models import HealthResponse, SearchRequest, SearchResponse
from rlm_search.prompts import build_system_prompt
from rlm_search.repl_tools_v2 import build_search_setup_code_v2
from rlm_search.sessions import SessionManager
from rlm_search.sse import create_sse_router
from rlm_search.streaming_v2 import StreamingLoggerV2

_log = logging.getLogger("rlm_search")

# Cached KB overview — built once at startup, shared across searches
_kb_overview_cache: dict | None = None

# Active searches: search_id -> EventBus
_searches: dict[str, EventBus] = {}
_session_manager = SessionManager(session_timeout=SESSION_TIMEOUT)
_executor = ThreadPoolExecutor(max_workers=4)
_MAX_CONCURRENT_SEARCHES = 8

_SOURCE_PATTERN = re.compile(r"\[Source:\s*(\d+)\]")
_SEARCH_ID_RE = re.compile(r"^[a-f0-9-]{1,36}$")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


async def _check_cascade_health(
    cascade_url: str | None = None,
) -> tuple[str, str | None]:
    """Probe the Cascade API and return (status, url)."""
    url = cascade_url or CASCADE_API_URL
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{url}/health")
            resp.raise_for_status()
    except (httpx.HTTPError, httpx.ConnectError, OSError):
        return "unreachable", url
    return "connected", url


def _check_api_key(request: Request) -> None:
    """Validate x-api-key header when SEARCH_API_KEY is configured."""
    if not SEARCH_API_KEY:
        return
    key = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(key, SEARCH_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _extract_sources(answer: str, registry: dict[str, dict] | None = None) -> list[dict]:
    """Extract unique source IDs from [Source: XXXX] references."""
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
    """Backfill top-level tool_calls for old log iterations that lack it."""
    last_count = 0
    for iteration in iterations:
        if "tool_calls" in iteration:
            last_count += len(iteration["tool_calls"])
            continue
        cumulative: list[dict] | None = None
        code_blocks = iteration.get("code_blocks", [])
        for block in code_blocks:
            tc = block.get("result", {}).get("locals", {}).get("tool_calls")
            if isinstance(tc, list):
                cumulative = tc
        if cumulative is not None:
            iteration["tool_calls"] = cumulative[last_count:]
            last_count = len(cumulative)
        else:
            iteration["tool_calls"] = []


def _build_rlm_kwargs(
    settings: dict[str, Any],
    query: str = "",
) -> dict[str, Any]:
    """Build RLM constructor kwargs from search settings + config defaults."""
    backend = settings.get("backend") or RLM_BACKEND
    model = settings.get("model") or RLM_MODEL
    sub_model = settings["sub_model"] if "sub_model" in settings else RLM_SUB_MODEL
    max_iterations = settings.get("max_iterations")
    if max_iterations is None:
        max_iterations = RLM_MAX_ITERATIONS
    max_depth = settings.get("max_depth")
    if max_depth is None:
        max_depth = RLM_MAX_DEPTH
    sub_iterations = settings.get("sub_iterations")
    if sub_iterations is None:
        sub_iterations = RLM_SUB_ITERATIONS
    max_delegation_depth = settings.get("max_delegation_depth")
    if max_delegation_depth is None:
        max_delegation_depth = RLM_MAX_DELEGATION_DEPTH

    if backend == "claude_cli":
        backend_kwargs: dict[str, Any] = {"model": model}
    else:
        backend_kwargs = {"model_name": model}
        if ANTHROPIC_API_KEY:
            backend_kwargs["api_key"] = ANTHROPIC_API_KEY

    other_backends_arg: list[str] | None = None
    other_backend_kwargs_arg: list[dict[str, Any]] | None = None
    if sub_model and sub_model not in ("", "same") and sub_model != model:
        if backend == "claude_cli":
            sub_kwargs: dict[str, Any] = {"model": sub_model}
        else:
            sub_kwargs = {"model_name": sub_model}
            if ANTHROPIC_API_KEY:
                sub_kwargs["api_key"] = ANTHROPIC_API_KEY
        other_backends_arg = [backend]
        other_backend_kwargs_arg = [sub_kwargs]

    setup_code = build_search_setup_code_v2(
        api_url=CASCADE_API_URL,
        kb_overview_data=_kb_overview_cache,
        rlm_model=model,
        rlm_backend=backend,
        depth=0,
        max_delegation_depth=max_delegation_depth,
        sub_iterations=sub_iterations,
        query=query,
        classify_model=RLM_CLASSIFY_MODEL,
    )

    return {
        "backend": backend,
        "model": model,
        "sub_model": sub_model,
        "max_iterations": max_iterations,
        "max_depth": max_depth,
        "backend_kwargs": backend_kwargs,
        "other_backends": other_backends_arg,
        "other_backend_kwargs": other_backend_kwargs_arg,
        "setup_code": setup_code,
    }


def _emit_metadata(logger: StreamingLoggerV2, rlm: RLM) -> None:
    """Emit RLM metadata to a logger (used for follow-up searches)."""
    bk = rlm.backend_kwargs or {}
    metadata = RLMMetadata(
        root_model=bk.get("model_name") or bk.get("model", "unknown"),
        max_depth=rlm.max_depth,
        max_iterations=rlm.max_iterations,
        backend=rlm.backend,
        backend_kwargs=filter_sensitive_keys(bk),
        environment_type=rlm.environment_type,
        environment_kwargs=filter_sensitive_keys(rlm.environment_kwargs),
        other_backends=rlm.other_backends,
    )
    logger.log_metadata(metadata)


def _get_evidence_store(rlm: RLM) -> Any:
    """Walk persistent_env to find the EvidenceStore from SearchContext."""
    if rlm._persistent_env is None:
        return None
    search_fn = rlm._persistent_env.locals.get("search")
    if search_fn and hasattr(search_fn, "__globals__"):
        ctx = search_fn.__globals__.get("_ctx")
        if ctx is not None and hasattr(ctx, "evidence"):
            return ctx.evidence
    return None


# ---------------------------------------------------------------------------
# Core search orchestration
# ---------------------------------------------------------------------------


def _run_search_v2(
    search_id: str,
    query: str,
    settings: dict[str, Any],
    session_id: str,
) -> None:
    """Run an RLM completion in a thread. Events flow through EventBus."""
    bus = _searches[search_id]
    session = _session_manager.get(session_id)

    try:
        if session is not None:
            # ── Follow-up search: reuse persistent RLM ──
            rlm, session = _session_manager.prepare_follow_up(session_id, bus, search_id)

            logger = StreamingLoggerV2(
                log_dir=str(_PROJECT_ROOT / "rlm_logs"),
                file_name=f"search_{search_id}",
                search_id=search_id,
                query=query,
                bus=bus,
            )
            rlm.logger = logger
            _emit_metadata(logger, rlm)

            # Update progress callback + parent_logger in persistent env
            if rlm._persistent_env is not None:
                rlm._persistent_env.globals["_progress_callback"] = logger.bus.emit
                rlm._persistent_env.globals["_parent_logger_ref"] = logger

                _ctx = None
                search_fn = rlm._persistent_env.locals.get("search")
                if search_fn and hasattr(search_fn, "__globals__"):
                    _ctx = search_fn.__globals__.get("_ctx")
                if _ctx is not None:
                    _ctx.progress_callback = logger.bus.emit
                    _ctx._parent_logger = logger

            result = rlm.completion(query, root_prompt=query)

        else:
            # ── New session: create persistent RLM ──
            kw = _build_rlm_kwargs(settings, query=query)

            logger = StreamingLoggerV2(
                log_dir=str(_PROJECT_ROOT / "rlm_logs"),
                file_name=f"search_{search_id}",
                search_id=search_id,
                query=query,
                bus=bus,
            )

            rlm = RLM(
                backend=kw["backend"],
                backend_kwargs=kw["backend_kwargs"],
                other_backends=kw["other_backends"],
                other_backend_kwargs=kw["other_backend_kwargs"],
                environment="local",
                environment_kwargs={
                    "setup_code": kw["setup_code"],
                    "progress_callback": bus.emit,
                    "_parent_logger_ref": logger,
                },
                max_iterations=kw["max_iterations"],
                max_depth=kw["max_depth"],
                custom_system_prompt=build_system_prompt(kw["max_iterations"]),
                logger=logger,
                persistent=True,
            )

            _session_manager.create_session(
                rlm=rlm, bus=bus, session_id=session_id
            )

            result = rlm.completion(query, root_prompt=query)

        # Extract sources from EvidenceStore (replaces _extract_sources from REPL locals)
        evidence = _get_evidence_store(rlm)
        if evidence is not None:
            sources = evidence.top_rated(n=20)
        else:
            sources = _extract_sources(result.response or "")
        usage = result.usage_summary.to_dict() if result.usage_summary else {}

        logger.mark_done(
            answer=result.response,
            sources=sources,
            execution_time=result.execution_time,
            usage=usage,
        )

    except SearchCancelled:
        bus.emit("cancelled", {})

    except Exception as e:
        _log.error("[SEARCH:%s] ERROR | %s: %s", search_id, type(e).__name__, e)
        bus.emit("error", {"message": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"})

    finally:
        _session_manager.clear_active(session_id)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _kb_overview_cache

    if CASCADE_API_KEY:
        os.environ["_RLM_CASCADE_API_KEY"] = CASCADE_API_KEY

    status, url = await _check_cascade_health()
    _app.state.cascade_url = url if status == "connected" else None
    if status == "connected":
        _log.info("Cascade API at %s is reachable.", url)
        _kb_overview_cache = await build_kb_overview(url, CASCADE_API_KEY)
        if _kb_overview_cache:
            n_cats = len(_kb_overview_cache.get("categories", {}))
            n_docs = _kb_overview_cache.get("total_documents", 0)
            _log.info("KB overview built: %d categories, %d total docs", n_cats, n_docs)
    else:
        _log.warning("Cascade API at %s is not reachable.", url)

    async def _cleanup_stale() -> None:
        while True:
            await asyncio.sleep(300)
            stale = [sid for sid, bus in _searches.items() if bus.is_done]
            for sid in stale:
                _searches.pop(sid, None)
            _session_manager.cleanup_expired()

    task = asyncio.create_task(_cleanup_stale())
    yield
    task.cancel()
    os.environ.pop("_RLM_CASCADE_API_KEY", None)


app = FastAPI(
    title="RLM Agentic Search",
    version="0.2.0",
    lifespan=lifespan,
    dependencies=[Depends(_check_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount SSE router (reads from EventBus)
app.include_router(create_sse_router(_searches))


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.post("/api/search", response_model=SearchResponse)
async def start_search(req: SearchRequest) -> SearchResponse:
    session_id = req.session_id

    if session_id:
        session = _session_manager.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if _session_manager.is_busy(session_id):
            raise HTTPException(status_code=409, detail="Session has an active search")
    else:
        session_id = str(uuid.uuid4())[:12]

    active_count = sum(1 for bus in _searches.values() if not bus.is_done)
    if active_count >= _MAX_CONCURRENT_SEARCHES:
        raise HTTPException(status_code=503, detail="Service busy, retry later")

    search_id = str(uuid.uuid4())[:12]

    bus = EventBus()
    _searches[search_id] = bus

    settings = req.settings.model_dump() if req.settings else {}
    _executor.submit(_run_search_v2, search_id, req.query, settings, session_id)

    return SearchResponse(search_id=search_id, session_id=session_id)


@app.post("/api/search/{search_id}/cancel")
async def cancel_search(search_id: str) -> dict:
    bus = _searches.get(search_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Search not found")
    bus.cancel()
    return {"status": "cancelled"}


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Explicitly tear down a persistent session and free resources."""
    session = _session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if _session_manager.is_busy(session_id):
        raise HTTPException(status_code=409, detail="Session has an active search")
    _session_manager.delete(session_id)
    return {"status": "deleted"}


@app.get("/api/logs/recent")
async def list_recent_logs(limit: int = 20) -> list[dict]:
    """List recent search logs with metadata."""
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
            results.append({
                "filename": f.name,
                "search_id": meta.get("search_id", ""),
                "query": meta.get("query", ""),
                "timestamp": meta.get("timestamp", ""),
                "root_model": meta.get("root_model", ""),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return results


@app.delete("/api/logs/{search_id}")
async def delete_log(search_id: str) -> dict:
    """Delete a search log by search_id prefix match."""
    if not _SEARCH_ID_RE.match(search_id):
        raise HTTPException(status_code=400, detail="Invalid search_id format")
    log_dir = _PROJECT_ROOT / "rlm_logs"
    matches = list(log_dir.glob(f"search_{search_id}*.jsonl"))
    if not matches:
        raise HTTPException(status_code=404, detail="Log not found")
    for f in matches:
        f.unlink()
    return {"deleted": search_id}


@app.get("/api/logs/{search_id}")
async def get_log(search_id: str) -> dict:
    """Load a completed search log by search_id prefix match."""
    if not _SEARCH_ID_RE.match(search_id):
        raise HTTPException(status_code=400, detail="Invalid search_id format")
    log_dir = _PROJECT_ROOT / "rlm_logs"
    if not log_dir.exists():
        raise HTTPException(status_code=404, detail="No logs directory")
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
    metadata = next((e for e in events if e.get("type") == "metadata"), None)
    iterations = [e for e in events if e.get("type") == "iteration"]
    done = next((e for e in events if e.get("type") == "done"), None)
    error = next((e for e in events if e.get("type") == "error"), None)
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
