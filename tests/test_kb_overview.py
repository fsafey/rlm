"""Tests for rlm_search.kb_overview — async KB taxonomy builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rlm_search.kb_overview import CATEGORIES, COLLECTION, build_kb_overview


def _make_global_response() -> dict:
    """Mock response for the global /browse call."""
    return {
        "total": 18835,
        "hits": [{"id": "1", "question": "sample"}],
        "facets": {
            "parent_code": {"PT": 5200, "WP": 3100, "MF": 4100, "FN": 2500, "BE": 2400, "OT": 1535},
            "cluster_label": {"Ghusl Requirements": 120, "Wudu Invalidators": 95},
        },
    }


def _make_category_response(code: str, doc_count: int) -> dict:
    """Mock response for a per-category /browse call."""
    return {
        "total": doc_count,
        "hits": [],
        "facets": {"subtopics": {"topic_a": 50, "topic_b": 30}},
        "grouped_results": [
            {
                "group_key": f"Cluster1_{code}",
                "hits": [{"id": f"{code}_1", "question": f"Sample question for {code}"}],
            },
            {
                "group_key": f"Cluster2_{code}",
                "hits": [{"id": f"{code}_2", "question": f"Another question for {code}"}],
            },
        ],
    }


CATEGORY_COUNTS = {"PT": 5200, "WP": 3100, "MF": 4100, "FN": 2500, "BE": 2400, "OT": 1535}


class TestBuildKbOverview:
    """Test build_kb_overview with mocked httpx responses."""

    def _make_mock_response(self, data: dict) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = data
        resp.status_code = 200
        return resp

    @pytest.mark.asyncio
    async def test_builds_overview_with_all_categories(self):
        """Should return overview with all 6 categories populated."""
        global_resp = self._make_mock_response(_make_global_response())

        cat_responses = {
            code: self._make_mock_response(_make_category_response(code, count))
            for code, count in CATEGORY_COUNTS.items()
        }

        call_count = 0

        async def mock_post(url: str, **kwargs):
            nonlocal call_count
            json_data = kwargs.get("json", {})
            filters = json_data.get("filters", {})
            parent_code = filters.get("parent_code")
            call_count += 1
            if parent_code and parent_code in cat_responses:
                return cat_responses[parent_code]
            return global_resp

        with patch("rlm_search.kb_overview.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await build_kb_overview("http://test:8091", "test-key")

        assert result is not None
        assert result["collection"] == COLLECTION
        assert result["total_documents"] == 18835
        assert len(result["categories"]) == 6

        for code in CATEGORIES:
            cat = result["categories"][code]
            assert cat["name"] == CATEGORIES[code]
            assert cat["document_count"] == CATEGORY_COUNTS[code]
            assert len(cat["clusters"]) == 2
            # Check cluster samples extracted
            cluster_key = f"Cluster1_{code}"
            assert cluster_key in cat["clusters"]
            assert cat["clusters"][cluster_key] == f"Sample question for {code}"

        assert "global_facets" in result
        assert "parent_code" in result["global_facets"]

    @pytest.mark.asyncio
    async def test_makes_7_concurrent_calls(self):
        """Should make exactly 7 API calls: 1 global + 6 per-category."""
        call_urls: list[str] = []

        async def mock_post(url: str, **kwargs):
            call_urls.append(url)
            resp = MagicMock(spec=httpx.Response)
            resp.json.return_value = {
                "total": 100,
                "hits": [],
                "facets": {},
                "grouped_results": [],
            }
            return resp

        with patch("rlm_search.kb_overview.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await build_kb_overview("http://test:8091")

        assert len(call_urls) == 7
        assert all(url == "http://test:8091/browse" for url in call_urls)

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self):
        """Should return None gracefully when Cascade is unreachable."""
        with patch("rlm_search.kb_overview.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await build_kb_overview("http://unreachable:8091")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_partial_category_failure(self):
        """If one category call fails, others should still populate."""
        call_count = 0

        async def mock_post(url: str, **kwargs):
            nonlocal call_count
            call_count += 1
            json_data = kwargs.get("json", {})
            filters = json_data.get("filters", {})
            parent_code = filters.get("parent_code")
            # Make PT category fail
            if parent_code == "PT":
                raise httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
            resp = MagicMock(spec=httpx.Response)
            resp.json.return_value = {
                "total": 100,
                "hits": [],
                "facets": {},
                "grouped_results": [
                    {"group_key": "TestCluster", "hits": [{"id": "1", "question": "q"}]}
                ],
            }
            return resp

        with patch("rlm_search.kb_overview.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await build_kb_overview("http://test:8091")

        assert result is not None
        # PT should have empty clusters due to failure
        assert result["categories"]["PT"]["document_count"] == 0
        assert result["categories"]["PT"]["clusters"] == {}
        # Other categories should be populated
        assert result["categories"]["MF"]["document_count"] == 100
        assert len(result["categories"]["MF"]["clusters"]) == 1

    @pytest.mark.asyncio
    async def test_api_key_included_in_headers(self):
        """Should include x-api-key header when api_key is provided."""
        captured_headers = {}

        with patch("rlm_search.kb_overview.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()

            async def mock_post(url: str, **kwargs):
                resp = MagicMock(spec=httpx.Response)
                resp.json.return_value = {
                    "total": 0,
                    "hits": [],
                    "facets": {},
                    "grouped_results": [],
                }
                return resp

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            def capture_init(**kwargs):
                captured_headers.update(kwargs.get("headers", {}))
                return mock_client

            mock_client_cls.side_effect = capture_init

            await build_kb_overview("http://test:8091", api_key="secret-key")

        assert captured_headers.get("x-api-key") == "secret-key"

    @pytest.mark.asyncio
    async def test_returns_none_when_global_call_fails(self):
        """If the global facets call fails, should return None."""
        call_count = 0

        async def mock_post(url: str, **kwargs):
            nonlocal call_count
            call_count += 1
            json_data = kwargs.get("json", {})
            filters = json_data.get("filters", {})
            # Global call has no parent_code filter
            if not filters.get("parent_code"):
                raise httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
            resp = MagicMock(spec=httpx.Response)
            resp.json.return_value = {
                "total": 100,
                "hits": [],
                "facets": {},
                "grouped_results": [],
            }
            return resp

        with patch("rlm_search.kb_overview.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await build_kb_overview("http://test:8091")

        assert result is None
