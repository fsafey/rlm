"""Tests for rlm_search.api — department-model FastAPI endpoints."""

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from rlm_search.api import _extract_sources, app


class TestSearchEndpoint:
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
            "99": {"id": "99", "score": 0.7, "question": "Q2", "answer": "A2"},
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
        registry = {"42": {"id": "42", "score": 0.9, "question": "Q", "answer": "A"}}
        answer = "[Source: 42] and [Source: 999]"
        sources = _extract_sources(answer, registry)
        assert sources[0]["question"] == "Q"
        assert sources[1] == {"id": "999"}

    def test_extract_deduplicates(self):
        """Repeated source IDs in answer produce only one entry."""
        answer = "[Source: 42] says X. As noted in [Source: 42], Y."
        sources = _extract_sources(answer)
        assert len(sources) == 1


class TestApiKeyAuth:
    """Test optional API key authentication."""

    @patch("rlm_search.api.SEARCH_API_KEY", "")
    def test_no_auth_when_key_empty(self):
        """When SEARCH_API_KEY is empty, endpoints work without auth."""
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200

    @patch("rlm_search.api.SEARCH_API_KEY", "test-secret-key")
    def test_401_without_key(self):
        """When SEARCH_API_KEY is set, requests without key get 401."""
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"]

    @patch("rlm_search.api.SEARCH_API_KEY", "test-secret-key")
    def test_401_with_wrong_key(self):
        """When SEARCH_API_KEY is set, wrong key gets 401."""
        client = TestClient(app)
        resp = client.get("/api/health", headers={"x-api-key": "wrong-key"})
        assert resp.status_code == 401

    @patch("rlm_search.api.SEARCH_API_KEY", "test-secret-key")
    def test_success_with_correct_key(self):
        """When SEARCH_API_KEY is set, correct key allows access."""
        client = TestClient(app)
        resp = client.get("/api/health", headers={"x-api-key": "test-secret-key"})
        assert resp.status_code == 200


class TestBuildSystemPrompt:
    """Prompt builder preserves base and substitutes iteration count."""

    def test_default_iterations(self):
        from rlm_search.prompts import build_system_prompt

        prompt = build_system_prompt()
        assert "15 iterations" in prompt
        assert "iteration 12" in prompt  # 15 - 3

    def test_base_prompt_preserved(self):
        from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT, build_system_prompt

        prompt = build_system_prompt(15)
        assert prompt.startswith(AGENTIC_SEARCH_SYSTEM_PROMPT)
