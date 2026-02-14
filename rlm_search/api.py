"""FastAPI backend for RLM agentic search."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from rlm.core.rlm import RLM
from rlm.core.types import RLMMetadata
from rlm.utils.rlm_utils import filter_sensitive_keys
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
    SESSION_TIMEOUT,
)
from rlm_search.kb_overview import build_kb_overview
from rlm_search.models import HealthResponse, SearchRequest, SearchResponse
from rlm_search.prompts import build_system_prompt
from rlm_search.repl_tools import build_search_setup_code
from rlm_search.streaming_logger import SearchCancelled, StreamingLogger

_log = logging.getLogger("rlm_search")

# Cached KB overview — built once at startup, shared across searches
_kb_overview_cache: dict | None = None


# ---------------------------------------------------------------------------
# Session state for persistent multi-turn RLM
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SessionState:
    """Persistent RLM session for multi-turn conversations."""

    session_id: str
    rlm: RLM
    lock: threading.Lock
    search_count: int = 0
    last_active: float = dataclasses.field(default_factory=time.monotonic)
    active_search_id: str | None = None


_sessions: dict[str, SessionState] = {}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


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
    """Startup/shutdown lifecycle — Cascade health check + stale cleanup."""

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
            # Clean completed searches
            stale = [sid for sid, lg in _searches.items() if lg.is_done]
            for sid in stale:
                _searches.pop(sid, None)
            # Clean expired sessions
            now = time.monotonic()
            expired = [
                sid
                for sid, ses in list(_sessions.items())
                if now - ses.last_active > SESSION_TIMEOUT and ses.active_search_id is None
            ]
            for sid in expired:
                ses = _sessions.pop(sid, None)
                if ses:
                    ses.rlm.close()
                    print(f"[SESSION:{sid}] Expired after {SESSION_TIMEOUT}s idle")

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
_SEARCH_ID_RE = re.compile(r"^[a-f0-9-]{1,36}$")


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


def _build_rlm_kwargs(
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Build RLM constructor kwargs from search settings + config defaults."""
    backend = settings.get("backend") or RLM_BACKEND
    model = settings.get("model") or RLM_MODEL
    sub_model = settings.get("sub_model") or RLM_SUB_MODEL
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

    # Build other_backends for sub-model routing (depth-1 calls)
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

    setup_code = build_search_setup_code(
        api_url=CASCADE_API_URL,
        api_key=CASCADE_API_KEY,
        kb_overview_data=_kb_overview_cache,
        rlm_model=model,
        rlm_backend=backend,
        depth=0,
        max_delegation_depth=max_delegation_depth,
        sub_iterations=sub_iterations,
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


def _pre_classify(query: str, kb_overview: dict | None) -> str:
    """Classify query via cheap LM call and return enriched context string.

    Returns the original query with appended classification metadata.
    Falls back to plain query on any failure (no-op degradation).
    """
    if not kb_overview:
        return query

    # Build category + cluster summary from cached KB overview
    cat_lines = []
    for code, cat in kb_overview.get("categories", {}).items():
        name = cat.get("name", code)
        clusters = list(cat.get("clusters", {}).keys())[:10]
        cat_lines.append(f"{code} — {name}: {', '.join(clusters)}")
    cat_info = "\n".join(cat_lines)

    prompt = [
        {
            "role": "user",
            "content": (
                "Classify this Islamic Q&A question into one of these categories"
                " and suggest search filters.\n\n"
                f'Question: "{query}"\n\n'
                f"Categories and their clusters:\n{cat_info}\n\n"
                "Respond with exactly (no other text):\n"
                "CATEGORY: <code>\n"
                "CLUSTERS: <comma-separated relevant cluster labels>\n"
                'FILTERS: <json dict, e.g. {"parent_code": "BE"}>\n'
                "STRATEGY: <1 sentence search plan>"
            ),
        },
    ]

    try:
        from rlm.clients import get_client

        # Use the configured backend — claude_cli for tunnel, anthropic for direct API
        if RLM_BACKEND == "claude_cli":
            classify_kwargs: dict[str, Any] = {"model": RLM_CLASSIFY_MODEL}
        else:
            classify_kwargs = {"model_name": RLM_CLASSIFY_MODEL}
            if ANTHROPIC_API_KEY:
                classify_kwargs["api_key"] = ANTHROPIC_API_KEY

        client = get_client(RLM_BACKEND, classify_kwargs)
        classification = client.completion(prompt)
        return f"{query}\n\n--- Pre-Classification ---\n{classification}"
    except Exception as e:
        _log.warning("Pre-classification failed, proceeding without: %s", e)
        return query


def _emit_metadata(logger: StreamingLogger, rlm: RLM) -> None:
    """Emit RLM metadata to a logger (used for follow-up searches where __init__ already ran)."""
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


# ---------------------------------------------------------------------------
# Core search orchestration
# ---------------------------------------------------------------------------


def _run_search(search_id: str, query: str, settings: dict[str, Any], session_id: str) -> None:
    """Run an RLM completion in a thread. Pushes events to the StreamingLogger."""
    logger = _searches[search_id]
    session = _sessions.get(session_id)

    # Track active search for race-free busy detection
    if session is not None:
        session.active_search_id = search_id

    try:
        try:
            if session is not None:
                # ── Follow-up search: reuse persistent RLM ──
                bk = session.rlm.backend_kwargs or {}
                model = bk.get("model_name") or bk.get("model", "unknown")
                model_short = model.rsplit("-", 1)[0] if len(model.split("-")) > 3 else model

                with session.lock:
                    session.search_count += 1
                    session.last_active = time.monotonic()
                    rlm = session.rlm

                    # Swap logger for this search
                    rlm.logger = logger

                    # Manually emit metadata (since __init__ already ran)
                    _emit_metadata(logger, rlm)

                    # Sync tool_call offset so the new logger computes correct deltas
                    # and update the progress callback to point at the new logger
                    if rlm._persistent_env is not None:
                        tc = rlm._persistent_env.locals.get("tool_calls", [])
                        logger._last_tool_call_count = len(tc)

                        rlm._persistent_env.globals["_progress_callback"] = logger.emit_tool_event
                        rlm._persistent_env.globals["_parent_logger_ref"] = logger

                        # _ctx starts with underscore so it's excluded from self.locals
                        # by LocalREPL's filter — access it through wrapper function closures
                        _ctx = None
                        search_fn = rlm._persistent_env.locals.get("search")
                        if search_fn and hasattr(search_fn, "__globals__"):
                            _ctx = search_fn.__globals__.get("_ctx")
                        if _ctx is not None:
                            _ctx.progress_callback = logger.emit_tool_event
                            _ctx._parent_logger = logger

                    print(
                        f"[SEARCH:{search_id}] Follow-up #{session.search_count} in session "
                        f"{session_id} | query={query!r}"
                    )
                    logger.emit_progress("reasoning", f"Follow-up analysis with {model_short}")

                    result = rlm.completion(query, root_prompt=query)

            else:
                # ── New session: create persistent RLM ──
                kw = _build_rlm_kwargs(settings)
                model_short = (
                    kw["model"].rsplit("-", 1)[0]
                    if len(kw["model"].split("-")) > 3
                    else kw["model"]
                )

                print(
                    f"[SEARCH:{search_id}] New session {session_id} | query={query!r} "
                    f"backend={kw['backend']} model={kw['model']} sub_model={kw['sub_model'] or '(same)'}"
                )

                rlm = RLM(
                    backend=kw["backend"],
                    backend_kwargs=kw["backend_kwargs"],
                    other_backends=kw["other_backends"],
                    other_backend_kwargs=kw["other_backend_kwargs"],
                    environment="local",
                    environment_kwargs={
                        "setup_code": kw["setup_code"],
                        "progress_callback": logger.emit_tool_event,
                        "_parent_logger_ref": logger,
                    },
                    max_iterations=kw["max_iterations"],
                    max_depth=kw["max_depth"],
                    custom_system_prompt=build_system_prompt(kw["max_iterations"]),
                    logger=logger,
                    persistent=True,
                )

                _sessions[session_id] = SessionState(
                    session_id=session_id,
                    rlm=rlm,
                    lock=threading.Lock(),
                    active_search_id=search_id,
                )
                session = _sessions[session_id]  # update local ref for finally block

                logger.emit_progress("classifying", f"Pre-classifying with {RLM_CLASSIFY_MODEL}")

                t0 = time.monotonic()
                enriched_query = _pre_classify(query, _kb_overview_cache)
                classify_ms = int((time.monotonic() - t0) * 1000)

                # Extract classification text if it was appended
                classification = None
                if "\n\n--- Pre-Classification ---\n" in enriched_query:
                    classification = enriched_query.split("\n\n--- Pre-Classification ---\n", 1)[1]

                logger.emit_progress(
                    "classified",
                    f"Pre-classified in {classify_ms}ms",
                    duration_ms=classify_ms,
                    **({"classification": classification} if classification else {}),
                )

                logger.emit_progress("reasoning", f"Analyzing your question with {model_short}")
                result = rlm.completion(enriched_query, root_prompt=query)

            print(
                f"[SEARCH:{search_id}] Completed | answer_len={len(result.response or '')} "
                f"time={result.execution_time:.2f}s"
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
            logger.mark_cancelled()

        except Exception as e:
            print(f"[SEARCH:{search_id}] ERROR | {type(e).__name__}: {e}")
            logger.mark_error(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    finally:
        if session is not None:
            session.active_search_id = None


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.post("/api/search", response_model=SearchResponse)
async def start_search(req: SearchRequest) -> SearchResponse:
    session_id = req.session_id

    # Validate existing session if provided
    if session_id:
        session = _sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.active_search_id is not None:
            raise HTTPException(status_code=409, detail="Session has an active search")
    else:
        # New session
        session_id = str(uuid.uuid4())[:12]

    search_id = str(uuid.uuid4())[:12]
    print(
        f"[API] POST /api/search | search={search_id} session={session_id} "
        f"follow_up={req.session_id is not None} query={req.query!r}"
    )

    logger = StreamingLogger(
        log_dir=str(_PROJECT_ROOT / "rlm_logs"),
        file_name=f"search_{search_id}",
        search_id=search_id,
        query=req.query,
    )
    _searches[search_id] = logger

    settings = req.settings.model_dump() if req.settings else {}
    _executor.submit(_run_search, search_id, req.query, settings, session_id)

    return SearchResponse(search_id=search_id, session_id=session_id)


@app.post("/api/search/{search_id}/cancel")
async def cancel_search(search_id: str) -> dict:
    print(f"[API] POST /api/search/{search_id}/cancel | found={search_id in _searches}")
    logger = _searches.get(search_id)
    if not logger:
        raise HTTPException(status_code=404, detail="Search not found")
    logger.cancel()
    return {"status": "cancelled"}


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Explicitly tear down a persistent session and free resources."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.active_search_id is not None:
        raise HTTPException(status_code=409, detail="Session has an active search")
    _sessions.pop(session_id, None)
    session.rlm.close()
    print(f"[SESSION:{session_id}] Deleted (search_count={session.search_count})")
    return {"status": "deleted"}


@app.get("/api/search/{search_id}/stream")
async def stream_search(search_id: str, request: Request) -> StreamingResponse:
    print(f"[API] GET /api/search/{search_id}/stream | found={search_id in _searches}")
    if search_id not in _searches:
        raise HTTPException(status_code=404, detail="Search not found")

    logger = _searches[search_id]

    async def event_generator():
        deadline = time.monotonic() + 600  # 10 minute max
        last_sent = time.monotonic()
        while time.monotonic() < deadline:
            # Detect client disconnect before draining to avoid losing events
            if await request.is_disconnected():
                logger.cancel()
                _searches.pop(search_id, None)
                return
            events = logger.drain()
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                last_sent = time.monotonic()
                if event.get("type") in ("done", "error", "cancelled"):
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
