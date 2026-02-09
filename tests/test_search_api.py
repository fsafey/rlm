"""Tests for rlm_search.api — FastAPI endpoints."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from rlm_search.api import _searches, app
from rlm_search.streaming_logger import StreamingLogger


@pytest.fixture()
def client():
    """Create a fresh test client, clearing active searches between tests."""
    _searches.clear()
    return TestClient(app)


class TestHealthEndpoint:
    """GET /api/health returns status ok."""

    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


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
    def test_search_with_collection(self, mock_executor: MagicMock, client: TestClient):
        mock_executor.submit = MagicMock()
        resp = client.post(
            "/api/search",
            json={"query": "zakat rules", "collection": "custom_collection"},
        )
        assert resp.status_code == 200
        # Verify the submit was called with the correct collection
        call_args = mock_executor.submit.call_args
        assert call_args[0][2] == "zakat rules"  # query
        assert call_args[0][3] == "custom_collection"  # collection

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
        settings = call_args[0][4]  # settings dict
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
