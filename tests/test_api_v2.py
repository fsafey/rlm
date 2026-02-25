"""tests/test_api_v2.py"""
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from rlm_search.api import app


class TestSearchV2Endpoint:
    def test_start_search_returns_ids(self):
        client = TestClient(app)
        with patch("rlm_search.api._executor") as mock_exec:
            mock_exec.submit = MagicMock()
            response = client.post("/api/search", json={"query": "test question"})
        assert response.status_code == 200
        data = response.json()
        assert "search_id" in data
        assert "session_id" in data

    def test_health_endpoint(self):
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
