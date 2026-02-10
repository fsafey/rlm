"""Tests for rlm_search.repl_tools — REPL setup code generation."""

import inspect
from unittest.mock import MagicMock, patch

from rlm.environments.local_repl import LocalREPL
from rlm_search.repl_tools import build_search_setup_code


class TestBuildSearchSetupCodeValidity:
    """Test that generated code is valid Python and defines expected names."""

    def test_generated_code_compiles(self):
        """Generated code string must be valid Python (no syntax errors)."""
        code = build_search_setup_code(api_url="http://localhost:8091", api_key="test-key")
        compile(code, "<setup_code>", "exec")

    def test_defines_search_function(self):
        """search() must be defined in the generated namespace."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "search" in ns
        assert callable(ns["search"])

    def test_defines_search_log(self):
        """search_log list must be defined in the generated namespace."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "search_log" in ns
        assert isinstance(ns["search_log"], list)
        assert len(ns["search_log"]) == 0


class TestBuildSearchSetupCodeEmbedding:
    """Test that API URL, key, and timeout are correctly embedded."""

    def test_api_url_embedded(self):
        code = build_search_setup_code(api_url="https://my-api.example.com")
        assert "https://my-api.example.com" in code

    def test_api_key_embedded(self):
        code = build_search_setup_code(api_url="http://localhost", api_key="sk-secret-123")
        assert "sk-secret-123" in code

    def test_empty_api_key_default(self):
        code = build_search_setup_code(api_url="http://localhost")
        # Should embed empty string as default
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_API_KEY"] == ""

    def test_timeout_embedded(self):
        code = build_search_setup_code(api_url="http://localhost", timeout=60)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_TIMEOUT"] == 60

    def test_default_timeout(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_TIMEOUT"] == 30

    def test_api_key_sets_header(self):
        """When api_key is provided, x-api-key header must be set."""
        code = build_search_setup_code(api_url="http://localhost", api_key="my-key")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_HEADERS"]["x-api-key"] == "my-key"

    def test_no_api_key_no_header(self):
        """When api_key is empty, x-api-key header must NOT be set."""
        code = build_search_setup_code(api_url="http://localhost", api_key="")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "x-api-key" not in ns["_HEADERS"]


class TestSearchFunctionSignature:
    """Test that search() has the correct signature (no collection param)."""

    def test_search_signature(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        sig = inspect.signature(ns["search"])
        params = list(sig.parameters.keys())
        assert "query" in params
        assert "filters" in params
        assert "top_k" in params
        assert "collection" not in params

    def test_search_defaults(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        sig = inspect.signature(ns["search"])
        assert sig.parameters["filters"].default is None
        assert sig.parameters["top_k"].default == 10


class TestSearchFunctionBehavior:
    """Test that search() calls requests.post correctly (mocked)."""

    def test_search_calls_api(self):
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "1", "score": 0.9, "question": "q", "answer": "a"}],
            "total": 1,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp) as mock_post:
            result = ns["search"]("test query")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "http://api.test/search" in call_kwargs[1].get("url", call_kwargs[0][0])
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "1"
        assert result["total"] == 1
        assert len(ns["search_log"]) == 1
        assert ns["search_log"][0]["type"] == "search"
        assert ns["search_log"][0]["query"] == "test query"

    def test_search_always_sends_enriched_collection(self):
        """search() must always include collection=enriched_gemini in payload."""
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp) as mock_post:
            ns["search"]("test")

        payload = mock_post.call_args[1]["json"]
        assert payload["collection"] == "enriched_gemini"

    def test_search_log_accumulates(self):
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp):
            ns["search"]("q1")
            ns["search"]("q2")

        assert len(ns["search_log"]) == 2
        assert ns["search_log"][0]["query"] == "q1"
        assert ns["search_log"][1]["query"] == "q2"


class TestFormatEvidence:
    """Test format_evidence() output formatting and limits."""

    def _exec_ns(self):
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        return ns

    def test_defines_format_evidence(self):
        ns = self._exec_ns()
        assert "format_evidence" in ns
        assert callable(ns["format_evidence"])

    def test_format_evidence_output(self):
        ns = self._exec_ns()
        results = [
            {"id": "doc1", "question": "What is wudu?", "answer": "Wudu is ablution."},
            {"id": "doc2", "question": "How to pray?", "answer": "Stand facing qibla."},
        ]
        lines = ns["format_evidence"](results)
        assert len(lines) == 2
        assert lines[0].startswith("[Source: doc1]")
        assert "Q: What is wudu?" in lines[0]
        assert "A: Wudu is ablution." in lines[0]

    def test_format_evidence_truncates_long_text(self):
        ns = self._exec_ns()
        results = [{"id": "d1", "question": "x" * 300, "answer": "y" * 2000}]
        lines = ns["format_evidence"](results)
        assert len(lines) == 1
        # Question truncated to 200, answer to 1500
        assert "x" * 200 in lines[0]
        assert "x" * 201 not in lines[0]
        assert "y" * 1500 in lines[0]
        assert "y" * 1501 not in lines[0]

    def test_format_evidence_caps_at_50_results(self):
        ns = self._exec_ns()
        results = [{"id": f"d{i}", "question": "q", "answer": "a"} for i in range(60)]
        lines = ns["format_evidence"](results)
        assert len(lines) == 50

    def test_format_evidence_respects_max_per_source(self):
        ns = self._exec_ns()
        results = [{"id": "same", "question": f"q{i}", "answer": "a"} for i in range(5)]
        lines = ns["format_evidence"](results, max_per_source=2)
        assert len(lines) == 2

    def test_format_evidence_accepts_search_result_dict(self):
        """format_evidence should unwrap {"results": [...]} from search() return value."""
        ns = self._exec_ns()
        results = [
            {"id": "doc1", "question": "What is wudu?", "answer": "Wudu is ablution."},
        ]
        lines = ns["format_evidence"]({"results": results})
        assert len(lines) == 1
        assert lines[0].startswith("[Source: doc1]")


class TestFiqhLookup:
    """Test fiqh_lookup() function generation and behavior."""

    def _exec_ns(self):
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        return ns

    def test_defines_fiqh_lookup(self):
        """fiqh_lookup() must be defined and callable in the generated namespace."""
        ns = self._exec_ns()
        assert "fiqh_lookup" in ns
        assert callable(ns["fiqh_lookup"])

    def test_fiqh_lookup_calls_bridge_endpoint(self):
        """fiqh_lookup() must call GET /bridge with correct params."""
        ns = self._exec_ns()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"bridges": [], "related": []}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "get", return_value=mock_resp) as mock_get:
            ns["fiqh_lookup"]("prayer")

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert (
            "http://api.test/bridge" in call_args[0][0]
            or call_args[1].get("url", "") == "http://api.test/bridge"
        )
        assert call_args[1]["params"] == {"q": "prayer"}

    def test_fiqh_lookup_returns_bridges_and_related(self):
        """fiqh_lookup() must return dict with 'bridges' and 'related' keys."""
        ns = self._exec_ns()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "bridges": [
                {"canonical": "salah", "arabic": "\u0635\u0644\u0627\u0629", "english": "prayer"}
            ],
            "related": [{"term": "qasr"}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "get", return_value=mock_resp):
            result = ns["fiqh_lookup"]("prayer")

        assert "bridges" in result
        assert "related" in result
        assert len(result["bridges"]) == 1
        assert result["bridges"][0]["canonical"] == "salah"
        assert len(result["related"]) == 1

    def test_fiqh_lookup_signature(self):
        """fiqh_lookup() must accept a single 'query' parameter."""
        ns = self._exec_ns()
        sig = inspect.signature(ns["fiqh_lookup"])
        params = list(sig.parameters.keys())
        assert params == ["query"]


class TestBrowseFunction:
    """Test browse() function generation and behavior."""

    def _exec_ns(self):
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        return ns

    def test_defines_browse(self):
        """browse() must be defined and callable in the generated namespace."""
        ns = self._exec_ns()
        assert "browse" in ns
        assert callable(ns["browse"])

    def test_browse_signature(self):
        """browse() must have the correct parameter signature."""
        ns = self._exec_ns()
        sig = inspect.signature(ns["browse"])
        params = list(sig.parameters.keys())
        assert "filters" in params
        assert "offset" in params
        assert "limit" in params
        assert "sort_by" in params
        assert "group_by" in params
        assert "group_limit" in params

    def test_browse_defaults(self):
        ns = self._exec_ns()
        sig = inspect.signature(ns["browse"])
        assert sig.parameters["filters"].default is None
        assert sig.parameters["offset"].default == 0
        assert sig.parameters["limit"].default == 20
        assert sig.parameters["sort_by"].default is None
        assert sig.parameters["group_by"].default is None
        assert sig.parameters["group_limit"].default == 4

    def test_browse_calls_browse_endpoint(self):
        """browse() must call POST /browse with correct payload."""
        ns = self._exec_ns()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "1", "question": "q", "answer": "a"}],
            "total": 1,
            "has_more": False,
            "facets": {"parent_code": {"PT": 100}},
            "grouped_results": [],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp) as mock_post:
            result = ns["browse"](filters={"parent_code": "PT"})

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["collection"] == "enriched_gemini"
        assert payload["filters"] == {"parent_code": "PT"}
        assert payload["include_facets"] is True
        assert len(result["results"]) == 1
        assert result["total"] == 1
        assert "facets" in result

    def test_browse_logs_to_search_log(self):
        """browse() must append to search_log with type='browse'."""
        ns = self._exec_ns()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [],
            "total": 0,
            "has_more": False,
            "facets": {},
            "grouped_results": [],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp):
            ns["browse"](filters={"parent_code": "PT"})

        assert len(ns["search_log"]) == 1
        assert ns["search_log"][0]["type"] == "browse"
        assert ns["search_log"][0]["filters"] == {"parent_code": "PT"}

    def test_browse_with_group_by(self):
        """browse() with group_by should include group_by in payload and log."""
        ns = self._exec_ns()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [],
            "total": 50,
            "has_more": True,
            "facets": {},
            "grouped_results": [
                {"group_key": "Cluster1", "hits": [{"id": "1", "question": "q", "answer": "a"}]},
            ],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp) as mock_post:
            result = ns["browse"](group_by="cluster_label", group_limit=2)

        payload = mock_post.call_args[1]["json"]
        assert payload["group_by"] == "cluster_label"
        assert payload["group_limit"] == 2
        assert len(result["grouped_results"]) == 1
        assert ns["search_log"][0]["group_by"] == "cluster_label"

    def test_browse_normalizes_hits(self):
        """browse() must normalize hits in both results and grouped_results."""
        ns = self._exec_ns()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [
                {
                    "id": "1",
                    "question": "q",
                    "answer": "a",
                    "parent_code": "PT",
                    "cluster_label": "Wudu",
                }
            ],
            "total": 1,
            "has_more": False,
            "facets": {},
            "grouped_results": [
                {
                    "group_key": "Wudu",
                    "hits": [
                        {
                            "id": "2",
                            "question": "q2",
                            "answer": "a2",
                            "parent_code": "PT",
                        }
                    ],
                }
            ],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp):
            result = ns["browse"]()

        # Direct results should be normalized
        assert "metadata" in result["results"][0]
        assert result["results"][0]["metadata"]["parent_code"] == "PT"
        # Grouped results should also be normalized
        grouped_hit = result["grouped_results"][0]["hits"][0]
        assert "metadata" in grouped_hit
        assert grouped_hit["metadata"]["parent_code"] == "PT"


class TestKbOverviewFunction:
    """Test kb_overview() function generation and behavior."""

    def test_defines_kb_overview_with_data(self):
        """kb_overview() must be defined when data is provided."""
        overview_data = {
            "collection": "enriched_gemini",
            "total_documents": 100,
            "categories": {"PT": {"name": "Prayer", "document_count": 50, "clusters": {}}},
            "global_facets": {},
        }
        code = build_search_setup_code(api_url="http://localhost", kb_overview_data=overview_data)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "kb_overview" in ns
        assert callable(ns["kb_overview"])

    def test_kb_overview_returns_data(self):
        """kb_overview() must return the pre-computed dict."""
        overview_data = {
            "collection": "enriched_gemini",
            "total_documents": 18835,
            "categories": {
                "PT": {
                    "name": "Prayer & Tahara",
                    "document_count": 5200,
                    "clusters": {"Ghusl": {"sample": {"id": "1", "question": "How to do ghusl?"}}},
                    "facets": {},
                }
            },
            "global_facets": {"parent_code": {"PT": 5200}},
        }
        code = build_search_setup_code(api_url="http://localhost", kb_overview_data=overview_data)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        result = ns["kb_overview"]()
        assert result is not None
        assert result["total_documents"] == 18835
        assert "PT" in result["categories"]
        assert result["categories"]["PT"]["clusters"]["Ghusl"]["sample"]["id"] == "1"

    def test_kb_overview_returns_none_without_data(self):
        """kb_overview() must return None gracefully when no data provided."""
        code = build_search_setup_code(api_url="http://localhost", kb_overview_data=None)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        result = ns["kb_overview"]()
        assert result is None

    def test_kb_overview_prints_formatted_summary(self, capsys):
        """kb_overview() must print a human-readable taxonomy summary."""
        overview_data = {
            "collection": "enriched_gemini",
            "total_documents": 18835,
            "categories": {
                "PT": {
                    "name": "Prayer & Tahara",
                    "document_count": 5200,
                    "clusters": {
                        "Ghusl": {"sample": {"id": "1", "question": "How to do ghusl?"}},
                        "Wudu": {"sample": {"id": "2", "question": "Does bleeding break wudu?"}},
                    },
                    "facets": {},
                }
            },
            "global_facets": {},
        }
        code = build_search_setup_code(api_url="http://localhost", kb_overview_data=overview_data)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        ns["kb_overview"]()
        captured = capsys.readouterr()
        assert "Knowledge Base: enriched_gemini" in captured.out
        assert "18,835 documents" in captured.out
        assert "PT" in captured.out
        assert "Prayer & Tahara" in captured.out
        assert "Ghusl" in captured.out

    def test_kb_overview_prints_warning_when_none(self, capsys):
        """kb_overview() must print warning when data is None."""
        code = build_search_setup_code(api_url="http://localhost", kb_overview_data=None)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        ns["kb_overview"]()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "unavailable" in captured.out


class TestSetupCodeInLocalREPL:
    """Test that setup code works when injected into a real LocalREPL."""

    def test_names_available_in_repl(self):
        """All tool names must exist in LocalREPL after setup."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        repl = LocalREPL(setup_code=code)
        try:
            assert "search" in repl.locals
            assert "search_log" in repl.locals
            assert "format_evidence" in repl.locals
            assert "fiqh_lookup" in repl.locals
            assert "browse" in repl.locals
            assert "kb_overview" in repl.locals
            assert callable(repl.locals["search"])
            assert callable(repl.locals["format_evidence"])
            assert callable(repl.locals["fiqh_lookup"])
            assert callable(repl.locals["browse"])
            assert callable(repl.locals["kb_overview"])
            assert isinstance(repl.locals["search_log"], list)
        finally:
            repl.cleanup()
