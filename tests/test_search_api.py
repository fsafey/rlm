"""Tests for rlm_search.api — FastAPI endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient

from rlm.core.types import CodeBlock, REPLResult, RLMIteration
from rlm_search.api import _extract_sources, _pre_classify, _searches, _sessions, app
from rlm_search.streaming_logger import StreamingLogger


@pytest.fixture()
def client():
    """Create a fresh test client, clearing active searches between tests.

    Cascade health check is patched to avoid real network calls during lifespan.
    """
    _searches.clear()
    _sessions.clear()
    with patch("rlm_search.api.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(side_effect=httpx.ConnectError("no cascade in test"))
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance
        return TestClient(app)


class TestHealthEndpoint:
    """GET /api/health returns status and cascade_api connectivity."""

    @patch("rlm_search.api.httpx.AsyncClient")
    def test_health_cascade_unreachable(self, mock_client_cls):
        """Health ping fails -> degraded."""
        _searches.clear()
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        with TestClient(app) as client:
            assert app.state.cascade_url is None
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["cascade_api"] == "unreachable"
        assert "version" in data
        assert data["cascade_url"] is not None

    @patch("rlm_search.api.build_kb_overview", new_callable=AsyncMock, return_value=None)
    @patch("rlm_search.api.httpx.AsyncClient")
    def test_health_cascade_connected(self, mock_client_cls, mock_kb_overview):
        """Health ping succeeds -> ok."""
        _searches.clear()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        with TestClient(app) as client:
            assert app.state.cascade_url is not None
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["cascade_api"] == "connected"


class TestSearchEndpoint:
    """POST /api/search creates a search and returns a search_id."""

    @patch("rlm_search.api._executor")
    def test_search_returns_search_id(self, mock_executor: MagicMock, client: TestClient):
        mock_executor.submit = MagicMock()
        resp = client.post("/api/search", json={"query": "prayer rules"})
        assert resp.status_code == 200
        data = resp.json()
        assert "search_id" in data
        assert isinstance(data["search_id"], str)
        assert len(data["search_id"]) > 0
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0

    @patch("rlm_search.api._executor")
    def test_search_with_settings(self, mock_executor: MagicMock, client: TestClient):
        mock_executor.submit = MagicMock()
        resp = client.post(
            "/api/search",
            json={
                "query": "fasting",
                "settings": {
                    "backend": "openai",
                    "model": "gpt-4o",
                    "max_iterations": 5,
                    "max_depth": 2,
                },
            },
        )
        assert resp.status_code == 200
        call_args = mock_executor.submit.call_args
        settings = call_args[0][3]  # settings dict
        assert settings["backend"] == "openai"
        assert settings["model"] == "gpt-4o"
        assert settings["max_iterations"] == 5
        assert settings["max_depth"] == 2
        session_id = call_args[0][4]  # session_id
        assert isinstance(session_id, str)
        assert len(session_id) > 0

    def test_search_missing_query(self, client: TestClient):
        resp = client.post("/api/search", json={})
        assert resp.status_code == 422  # Pydantic validation error

    @patch("rlm_search.api._executor")
    def test_search_registers_logger(self, mock_executor: MagicMock, client: TestClient):
        mock_executor.submit = MagicMock()
        resp = client.post("/api/search", json={"query": "test"})
        search_id = resp.json()["search_id"]
        assert search_id in _searches
        assert isinstance(_searches[search_id], StreamingLogger)


class TestStreamEndpoint:
    """GET /api/search/{search_id}/stream returns SSE events."""

    def test_stream_not_found(self, client: TestClient):
        resp = client.get("/api/search/nonexistent/stream")
        assert resp.status_code == 404

    def test_stream_returns_done_event(self, client: TestClient):
        """Pre-populate a logger with a done event and verify SSE output."""
        search_id = "test-stream-1"
        logger = StreamingLogger(log_dir="/tmp/rlm_test_logs", file_name=f"test_{search_id}")
        logger.mark_done(
            answer="The ruling is X.",
            sources=[],
            execution_time=1.5,
            usage={"total_tokens": 100},
        )
        _searches[search_id] = logger

        resp = client.get(f"/api/search/{search_id}/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        # Parse SSE data lines
        events = _parse_sse_events(resp.text)
        assert len(events) >= 1

        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1
        assert done_events[0]["answer"] == "The ruling is X."
        assert done_events[0]["execution_time"] == 1.5

    def test_stream_returns_error_event(self, client: TestClient):
        """Pre-populate a logger with an error event and verify SSE output."""
        search_id = "test-stream-2"
        logger = StreamingLogger(log_dir="/tmp/rlm_test_logs", file_name=f"test_{search_id}")
        logger.mark_error("RuntimeError: something broke")
        _searches[search_id] = logger

        resp = client.get(f"/api/search/{search_id}/stream")
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "something broke" in error_events[0]["message"]

    def test_stream_cleans_up_after_done(self, client: TestClient):
        """After a terminal event, the search_id should be removed from _searches."""
        search_id = "test-stream-3"
        logger = StreamingLogger(log_dir="/tmp/rlm_test_logs", file_name=f"test_{search_id}")
        logger.mark_done(answer="done", sources=[], execution_time=0.1, usage={})
        _searches[search_id] = logger

        client.get(f"/api/search/{search_id}/stream")
        assert search_id not in _searches

    def test_stream_iteration_includes_tool_calls(self, client: TestClient):
        """Iteration events include tool_calls from locals."""
        search_id = "test-stream-tc"
        logger = StreamingLogger(log_dir="/tmp/rlm_test_logs", file_name=f"test_{search_id}")

        # Create an iteration with tool_calls in locals
        repl_result = REPLResult(
            stdout="[search] query='test' results=3",
            stderr="",
            locals={
                "tool_calls": [
                    {
                        "tool": "search",
                        "args": {"query": "test"},
                        "result_summary": {"num_results": 3},
                        "duration_ms": 150,
                        "children": [],
                        "error": None,
                    },
                ]
            },
            execution_time=0.2,
        )
        code_block = CodeBlock(code="search('test')", result=repl_result)
        iteration = RLMIteration(
            prompt="Search for test",
            response="Let me search for that.",
            code_blocks=[code_block],
            final_answer=None,
            iteration_time=1.0,
        )
        logger.log(iteration)
        logger.mark_done(answer="Found it.", sources=[], execution_time=2.0, usage={})
        _searches[search_id] = logger

        resp = client.get(f"/api/search/{search_id}/stream")
        events = _parse_sse_events(resp.text)
        iter_events = [e for e in events if e.get("type") == "iteration"]
        assert len(iter_events) == 1
        assert "tool_calls" in iter_events[0]
        assert len(iter_events[0]["tool_calls"]) == 1
        assert iter_events[0]["tool_calls"][0]["tool"] == "search"


class TestExtractSources:
    """Test _extract_sources with and without registry enrichment."""

    def test_extract_ids_only(self):
        """Without registry, returns minimal dicts with ID only."""
        answer = "Based on [Source: 42] and [Source: 99], the ruling is clear."
        sources = _extract_sources(answer)
        assert len(sources) == 2
        assert sources[0] == {"id": "42"}
        assert sources[1] == {"id": "99"}

    def test_extract_with_registry(self):
        """With registry, returns enriched source dicts."""
        registry = {
            "42": {
                "id": "42",
                "score": 0.85,
                "question": "What is wudu?",
                "answer": "Wudu is ablution.",
                "metadata": {"parent_code": "PT"},
            },
            "99": {
                "id": "99",
                "score": 0.7,
                "question": "Q2",
                "answer": "A2",
            },
        }
        answer = "Based on [Source: 42] and [Source: 99], the ruling is clear."
        sources = _extract_sources(answer, registry)
        assert len(sources) == 2
        assert sources[0]["question"] == "What is wudu?"
        assert sources[0]["score"] == 0.85
        assert sources[0]["metadata"]["parent_code"] == "PT"
        assert sources[1]["question"] == "Q2"

    def test_extract_partial_registry(self):
        """Sources not in registry fall back to ID-only dict."""
        registry = {
            "42": {"id": "42", "score": 0.9, "question": "Q", "answer": "A"},
        }
        answer = "[Source: 42] and [Source: 999]"
        sources = _extract_sources(answer, registry)
        assert sources[0]["question"] == "Q"
        assert sources[1] == {"id": "999"}

    def test_extract_deduplicates(self):
        """Repeated source IDs in answer produce only one entry."""
        answer = "[Source: 42] says X. As noted in [Source: 42], Y."
        sources = _extract_sources(answer)
        assert len(sources) == 1


class TestSubModelWiring:
    """Test sub_model → other_backends wiring in _run_search."""

    @patch("rlm_search.api._executor")
    def test_sub_model_passed_in_settings(self, mock_executor: MagicMock, client: TestClient):
        """sub_model in settings is forwarded to _run_search."""
        mock_executor.submit = MagicMock()
        resp = client.post(
            "/api/search",
            json={
                "query": "test",
                "settings": {"sub_model": "claude-sonnet-4-5-20250929"},
            },
        )
        assert resp.status_code == 200
        call_args = mock_executor.submit.call_args
        settings = call_args[0][3]
        assert settings["sub_model"] == "claude-sonnet-4-5-20250929"

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    @patch("rlm_search.api.RLM_BACKEND", "anthropic")
    def test_sub_model_wires_other_backends(self, _mock_setup, mock_rlm):
        """When sub_model differs from model, other_backends is set."""
        from rlm_search.api import _run_search, _searches
        from rlm_search.streaming_logger import StreamingLogger

        search_id = "test-sub-1"
        session_id = "test-session-1"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(
            search_id,
            "test query",
            {"model": "claude-opus-4-6", "sub_model": "claude-sonnet-4-5-20250929"},
            session_id,
        )

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["other_backends"] == ["anthropic"]
        assert rlm_kwargs["other_backend_kwargs"] is not None
        assert rlm_kwargs["other_backend_kwargs"][0]["model_name"] == "claude-sonnet-4-5-20250929"
        _sessions.clear()

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    def test_sub_model_same_as_root_skips(self, _mock_setup, mock_rlm):
        """When sub_model == model, other_backends is None."""
        from rlm_search.api import _run_search, _searches
        from rlm_search.streaming_logger import StreamingLogger

        search_id = "test-sub-2"
        session_id = "test-session-2"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(
            search_id,
            "test query",
            {"model": "claude-opus-4-6", "sub_model": "claude-opus-4-6"},
            session_id,
        )

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["other_backends"] is None
        assert rlm_kwargs["other_backend_kwargs"] is None
        _sessions.clear()

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    def test_sub_model_empty_skips(self, _mock_setup, mock_rlm):
        """When sub_model is empty string, other_backends is None."""
        from rlm_search.api import _run_search, _searches
        from rlm_search.streaming_logger import StreamingLogger

        search_id = "test-sub-3"
        session_id = "test-session-3"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(search_id, "test query", {"sub_model": ""}, session_id)

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["other_backends"] is None
        assert rlm_kwargs["other_backend_kwargs"] is None
        _sessions.clear()

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    @patch("rlm_search.api.RLM_SUB_MODEL", "claude-haiku-4-5-20251001")
    @patch("rlm_search.api.RLM_BACKEND", "anthropic")
    def test_env_var_fallback(self, _mock_setup, mock_rlm):
        """When settings has no sub_model, falls back to RLM_SUB_MODEL env var."""
        from rlm_search.api import _run_search, _searches
        from rlm_search.streaming_logger import StreamingLogger

        search_id = "test-sub-4"
        session_id = "test-session-4"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(search_id, "test query", {}, session_id)

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["other_backends"] == ["anthropic"]
        assert rlm_kwargs["other_backend_kwargs"][0]["model_name"] == "claude-haiku-4-5-20251001"
        _sessions.clear()

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    @patch("rlm_search.api.RLM_BACKEND", "claude_cli")
    def test_sub_model_claude_cli_backend(self, _mock_setup, mock_rlm):
        """claude_cli backend uses 'model' key instead of 'model_name'."""
        from rlm_search.api import _run_search, _searches
        from rlm_search.streaming_logger import StreamingLogger

        search_id = "test-sub-5"
        session_id = "test-session-5"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(
            search_id,
            "test query",
            {"sub_model": "claude-sonnet-4-5-20250929"},
            session_id,
        )

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["other_backends"] == ["claude_cli"]
        assert rlm_kwargs["other_backend_kwargs"][0]["model"] == "claude-sonnet-4-5-20250929"
        assert "model_name" not in rlm_kwargs["other_backend_kwargs"][0]
        _sessions.clear()


class TestStreamingLoggerSourceRegistry:
    """Test that StreamingLogger accumulates source_registry from iterations."""

    def test_source_registry_initialized_empty(self):
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name="test")
        assert logger.source_registry == {}


class TestSessionLifecycle:
    """Test persistent session creation, follow-up, and cleanup."""

    @patch("rlm_search.api._executor")
    def test_first_search_returns_session_id(self, mock_executor: MagicMock, client: TestClient):
        """First search creates a new session_id."""
        mock_executor.submit = MagicMock()
        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0

    @patch("rlm_search.api._executor")
    def test_follow_up_preserves_session_id(self, mock_executor: MagicMock, client: TestClient):
        """Follow-up search with session_id reuses the same session."""
        mock_executor.submit = MagicMock()

        # Simulate an existing session
        from rlm_search.api import SessionState, _sessions

        mock_rlm = MagicMock()
        mock_rlm.close = MagicMock()
        import threading

        session = SessionState(
            session_id="existing-session",
            rlm=mock_rlm,
            lock=threading.Lock(),
        )
        _sessions["existing-session"] = session

        resp = client.post(
            "/api/search",
            json={"query": "follow-up", "session_id": "existing-session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "existing-session"
        _sessions.clear()

    @patch("rlm_search.api._executor")
    def test_follow_up_invalid_session_404(self, mock_executor: MagicMock, client: TestClient):
        """Follow-up with non-existent session returns 404."""
        mock_executor.submit = MagicMock()
        resp = client.post(
            "/api/search",
            json={"query": "test", "session_id": "nonexistent"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @patch("rlm_search.api._executor")
    def test_follow_up_busy_session_409(self, mock_executor: MagicMock, client: TestClient):
        """Follow-up on a session with active search returns 409."""
        import threading

        from rlm_search.api import SessionState, _sessions

        mock_rlm = MagicMock()
        session = SessionState(
            session_id="busy-session",
            rlm=mock_rlm,
            lock=threading.Lock(),
            active_search_id="some-active-search",
        )
        _sessions["busy-session"] = session

        resp = client.post(
            "/api/search",
            json={"query": "test", "session_id": "busy-session"},
        )
        assert resp.status_code == 409
        _sessions.clear()

    def test_delete_session(self, client: TestClient):
        """DELETE /api/session/{id} cleans up the session."""
        import threading

        from rlm_search.api import SessionState, _sessions

        mock_rlm = MagicMock()
        mock_rlm.close = MagicMock()
        _sessions["del-session"] = SessionState(
            session_id="del-session",
            rlm=mock_rlm,
            lock=threading.Lock(),
        )

        resp = client.request("DELETE", "/api/session/del-session")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert "del-session" not in _sessions
        mock_rlm.close.assert_called_once()

    def test_delete_nonexistent_session_404(self, client: TestClient):
        resp = client.request("DELETE", "/api/session/nonexistent")
        assert resp.status_code == 404

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    def test_run_search_creates_persistent_rlm(self, _mock_setup, mock_rlm):
        """First _run_search in a session creates RLM with persistent=True."""
        from rlm_search.api import _run_search, _searches, _sessions

        search_id = "test-persist-1"
        session_id = "test-persist-session"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(search_id, "test query", {}, session_id)

        # Verify persistent=True was passed
        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["persistent"] is True

        # Verify session was registered
        assert session_id in _sessions
        assert _sessions[session_id].rlm is mock_instance
        _sessions.clear()

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    def test_follow_up_reuses_rlm_instance(self, _mock_setup, mock_rlm):
        """Follow-up _run_search reuses existing RLM, swaps logger."""
        import threading

        from rlm_search.api import SessionState, _run_search, _searches, _sessions

        # Setup: create an existing session with a mock RLM
        existing_rlm = MagicMock()
        existing_rlm.completion.return_value = MagicMock(
            response="follow-up answer", execution_time=0.5, usage_summary=None
        )
        existing_rlm._persistent_env = MagicMock()
        existing_rlm._persistent_env.locals = {"tool_calls": [{"tool": "search"}]}
        existing_rlm.backend_kwargs = {"model_name": "claude-opus-4-6"}
        existing_rlm.max_depth = 1
        existing_rlm.max_iterations = 15
        existing_rlm.backend = "anthropic"
        existing_rlm.environment_type = "local"
        existing_rlm.environment_kwargs = {}
        existing_rlm.other_backends = None

        session_id = "follow-up-session"
        _sessions[session_id] = SessionState(
            session_id=session_id,
            rlm=existing_rlm,
            lock=threading.Lock(),
        )

        # Run follow-up search
        search_id = "test-followup-1"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        _run_search(search_id, "follow-up query", {}, session_id)

        # RLM constructor should NOT have been called (reused existing)
        mock_rlm.assert_not_called()

        # Existing RLM's completion() was called
        existing_rlm.completion.assert_called_once_with(
            "follow-up query", root_prompt="follow-up query"
        )

        # Logger was swapped
        assert existing_rlm.logger is logger

        # Session search_count incremented
        assert _sessions[session_id].search_count == 1

        # Tool call offset was synced from persistent env
        assert logger._last_tool_call_count == 1

        _sessions.clear()


class TestPreClassifyTimingInProgress:
    """Test that pre-classification emits a 'classified' progress event with duration_ms."""

    @patch("rlm_search.api.RLM")
    @patch("rlm_search.api.build_search_setup_code", return_value="# setup")
    @patch("rlm_search.api._pre_classify")
    @patch("rlm_search.api._kb_overview_cache", {"categories": {}, "total_documents": 0})
    def test_pre_classify_timing_emitted(self, mock_classify, _mock_setup, mock_rlm):
        """_run_search emits a 'classified' progress event with duration_ms."""
        from rlm_search.api import _run_search, _searches, _sessions

        mock_classify.return_value = "test\n\n--- Pre-Classification ---\nCATEGORY: PT"

        search_id = "test-classify-timing"
        session_id = "test-classify-session"
        logger = StreamingLogger(log_dir="/tmp/rlm_test", file_name=f"test_{search_id}")
        _searches[search_id] = logger

        mock_instance = MagicMock()
        mock_instance.completion.return_value = MagicMock(
            response="answer", execution_time=1.0, usage_summary=None
        )
        mock_instance._persistent_env = None
        mock_instance.close = MagicMock()
        mock_rlm.return_value = mock_instance

        _run_search(search_id, "test query", {}, session_id)

        events = logger.drain()
        classified_events = [
            e for e in events if e.get("type") == "progress" and e.get("phase") == "classified"
        ]
        assert len(classified_events) == 1
        ev = classified_events[0]
        assert "duration_ms" in ev
        assert isinstance(ev["duration_ms"], int)
        assert ev["duration_ms"] >= 0
        assert ev["classification"] == "CATEGORY: PT"
        _sessions.clear()


class TestPreClassify:
    """Test _pre_classify() enrichment and fallback behavior."""

    _KB_OVERVIEW = {
        "categories": {
            "PT": {"name": "Prayer & Tahara", "clusters": {"Wudu": {}, "Ghusl": {}}},
            "FN": {"name": "Finance & Transactions", "clusters": {"Riba": {}, "Zakat": {}}},
        },
        "total_documents": 100,
    }

    @patch("rlm.clients.get_client")
    @patch("rlm_search.api.RLM_BACKEND", "claude_cli")
    def test_happy_path_claude_cli(self, mock_get_client):
        """Classification via claude_cli backend uses 'model' key."""
        mock_client = MagicMock()
        mock_client.completion.return_value = (
            "CATEGORY: FN\nCLUSTERS: Riba, Zakat\n"
            'FILTERS: {"parent_code": "FN"}\n'
            "STRATEGY: Search for riba rulings"
        )
        mock_get_client.return_value = mock_client

        result = _pre_classify("Is riba haram?", self._KB_OVERVIEW)

        assert result.startswith("Is riba haram?")
        assert "\n\n--- Pre-Classification ---\n" in result
        assert "CATEGORY: FN" in result
        mock_get_client.assert_called_once_with(
            "claude_cli",
            {"model": "claude-haiku-4-5-20251001"},
        )

    @patch("rlm.clients.get_client")
    @patch("rlm_search.api.RLM_BACKEND", "anthropic")
    @patch("rlm_search.api.ANTHROPIC_API_KEY", "test-key")
    def test_happy_path_anthropic(self, mock_get_client):
        """Classification via anthropic backend uses 'model_name' + api_key."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT"
        mock_get_client.return_value = mock_client

        result = _pre_classify("wudu question", self._KB_OVERVIEW)

        assert "\n\n--- Pre-Classification ---\n" in result
        mock_get_client.assert_called_once_with(
            "anthropic",
            {"model_name": "claude-haiku-4-5-20251001", "api_key": "test-key"},
        )

    def test_no_kb_overview_returns_plain_query(self):
        """Without KB overview, returns query unchanged."""
        assert _pre_classify("test query", None) == "test query"

    @patch("rlm.clients.get_client")
    @patch("rlm_search.api.RLM_BACKEND", "claude_cli")
    def test_client_exception_returns_plain_query(self, mock_get_client):
        """Client error falls back to plain query."""
        mock_get_client.side_effect = RuntimeError("model unavailable")

        result = _pre_classify("test query", self._KB_OVERVIEW)
        assert result == "test query"

    @patch("rlm.clients.get_client")
    @patch("rlm_search.api.RLM_BACKEND", "claude_cli")
    def test_enriched_format(self, mock_get_client):
        """Verify the exact separator format."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT"
        mock_get_client.return_value = mock_client

        result = _pre_classify("wudu question", self._KB_OVERVIEW)
        parts = result.split("\n\n--- Pre-Classification ---\n")
        assert len(parts) == 2
        assert parts[0] == "wudu question"
        assert parts[1] == "CATEGORY: PT"


class TestBuildSystemPrompt:
    """Test build_system_prompt() generates correct budget text."""

    def test_includes_budget_section(self):
        from rlm_search.prompts import build_system_prompt

        prompt = build_system_prompt(10)
        assert "10 iterations" in prompt
        assert "iteration 7" in prompt  # max_iterations - 3
        assert "check_progress()" in prompt

    def test_default_iterations(self):
        from rlm_search.prompts import build_system_prompt

        prompt = build_system_prompt()
        assert "15 iterations" in prompt
        assert "iteration 12" in prompt  # 15 - 3

    def test_base_prompt_preserved(self):
        from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT, build_system_prompt

        prompt = build_system_prompt(15)
        assert prompt.startswith(AGENTIC_SEARCH_SYSTEM_PROMPT)


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of JSON event dicts."""
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            events.append(json.loads(payload))
    return events
