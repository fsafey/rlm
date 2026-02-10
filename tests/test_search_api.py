"""Tests for rlm_search.api — FastAPI endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient

from rlm_search.api import _searches, app
from rlm_search.streaming_logger import StreamingLogger


@pytest.fixture()
def client():
    """Create a fresh test client, clearing active searches between tests.

    Cascade health check is patched to avoid real network calls during lifespan.
    """
    _searches.clear()
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

    @patch("rlm_search.api.httpx.AsyncClient")
    def test_health_cascade_connected(self, mock_client_cls):
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
        settings = call_args[0][3]  # settings dict (was [4] when collection existed)
        assert settings["backend"] == "openai"
        assert settings["model"] == "gpt-4o"
        assert settings["max_iterations"] == 5
        assert settings["max_depth"] == 2

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


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of JSON event dicts."""
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            events.append(json.loads(payload))
    return events
