"""Tests for rlm_search.repl_tools — REPL setup code generation."""

import inspect
from unittest.mock import MagicMock, patch

from rlm.environments.local_repl import LocalREPL
from rlm_search.repl_tools import build_search_setup_code

# Common mock target prefix for API tools
_API_POST = "rlm_search.tools.api_tools.requests.post"
_API_GET = "rlm_search.tools.api_tools.requests.get"


class TestBuildSearchSetupCodeValidity:
    """Test that generated code is valid Python and defines expected names."""

    def test_generated_code_compiles(self):
        """Generated code string must be valid Python (no syntax errors)."""
        code = build_search_setup_code(api_url="http://localhost:8091")
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

    def test_defines_source_registry(self):
        """source_registry dict must be defined in the generated namespace."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "source_registry" in ns
        assert isinstance(ns["source_registry"], dict)
        assert len(ns["source_registry"]) == 0


class TestBuildSearchSetupCodeEmbedding:
    """Test that API URL, key, and timeout are correctly embedded."""

    def test_api_url_embedded(self):
        code = build_search_setup_code(api_url="https://my-api.example.com")
        assert "https://my-api.example.com" in code

    def test_api_key_not_embedded(self):
        """API key must NOT appear as a literal in generated code (reads env var instead)."""
        code = build_search_setup_code(api_url="http://localhost")
        assert "sk-secret-123" not in code
        assert "_RLM_CASCADE_API_KEY" in code

    def test_empty_api_key_default(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_ctx"].api_key == ""

    def test_timeout_embedded(self):
        code = build_search_setup_code(api_url="http://localhost", timeout=60)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_ctx"].timeout == 60

    def test_default_timeout(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_ctx"].timeout == 30

    def test_api_key_sets_header_from_env(self):
        """When _RLM_CASCADE_API_KEY env var is set, x-api-key header must be set."""
        import os

        os.environ["_RLM_CASCADE_API_KEY"] = "my-key"
        try:
            code = build_search_setup_code(api_url="http://localhost")
            ns: dict = {}
            exec(code, ns)  # noqa: S102
            assert ns["_ctx"].headers["x-api-key"] == "my-key"
        finally:
            del os.environ["_RLM_CASCADE_API_KEY"]

    def test_no_api_key_no_header(self):
        """When _RLM_CASCADE_API_KEY env var is absent, x-api-key header must NOT be set."""
        import os

        os.environ.pop("_RLM_CASCADE_API_KEY", None)
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "x-api-key" not in ns["_ctx"].headers


class TestBuildSearchSetupCodeBackend:
    """Test rlm_backend parameter propagation."""

    def test_rlm_backend_embedded(self):
        code = build_search_setup_code(api_url="http://localhost:8091", rlm_backend="openai")
        assert "_ctx._rlm_backend = 'openai'" in code

    def test_rlm_backend_default_empty(self):
        code = build_search_setup_code(api_url="http://localhost:8091")
        assert "_ctx._rlm_backend = ''" in code


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
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "1", "score": 0.9, "question": "q", "answer": "a"}],
            "total": 1,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp) as mock_post:
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

    def test_search_populates_source_registry(self):
        """search() must populate source_registry with normalized hits keyed by ID."""
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [
                {
                    "id": "42",
                    "score": 0.85,
                    "question": "What is wudu?",
                    "answer": "Wudu is ablution.",
                    "parent_code": "PT",
                    "cluster_label": "Wudu Basics",
                },
                {"id": "99", "score": 0.7, "question": "Q2", "answer": "A2"},
            ],
            "total": 2,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp):
            ns["search"]("wudu query")

        reg = ns["source_registry"]
        assert "42" in reg
        assert "99" in reg
        assert reg["42"]["question"] == "What is wudu?"
        assert reg["42"]["score"] == 0.85
        assert reg["42"]["metadata"]["parent_code"] == "PT"
        assert reg["42"]["metadata"]["cluster_label"] == "Wudu Basics"
        assert reg["99"]["question"] == "Q2"

    def test_search_always_sends_enriched_collection(self):
        """search() must always include collection=enriched_gemini in payload."""
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp) as mock_post:
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

        with patch(_API_POST, return_value=mock_resp):
            ns["search"]("q1")
            ns["search"]("q2")

        assert len(ns["search_log"]) == 2
        assert ns["search_log"][0]["query"] == "q1"
        assert ns["search_log"][1]["query"] == "q2"

    def test_search_truncates_long_query(self, capsys):
        """search() truncates queries exceeding 500 chars to avoid API 422."""
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        long_query = "x" * 800
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp) as mock_post:
            ns["search"](long_query)

        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "truncating" in captured.out
        payload = mock_post.call_args[1]["json"]
        assert len(payload["query"]) == 500

    def test_search_short_query_not_truncated(self):
        """search() does not truncate queries under the limit."""
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp) as mock_post:
            ns["search"]("short query")

        payload = mock_post.call_args[1]["json"]
        assert payload["query"] == "short query"


class TestFormatEvidence:
    """Test format_evidence() output formatting and limits."""

    def _exec_ns(self):
        code = build_search_setup_code(api_url="http://api.test")
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
        code = build_search_setup_code(api_url="http://api.test")
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

        with patch(_API_GET, return_value=mock_resp) as mock_get:
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

        with patch(_API_GET, return_value=mock_resp):
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
        code = build_search_setup_code(api_url="http://api.test")
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

        with patch(_API_POST, return_value=mock_resp) as mock_post:
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

        with patch(_API_POST, return_value=mock_resp):
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

        with patch(_API_POST, return_value=mock_resp) as mock_post:
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

        with patch(_API_POST, return_value=mock_resp):
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
        """kb_overview() must return a dict with collection, total_documents, categories."""
        overview_data = {
            "collection": "enriched_gemini",
            "total_documents": 18835,
            "categories": {
                "PT": {
                    "name": "Prayer & Tahara",
                    "document_count": 5200,
                    "clusters": {"Ghusl": "How to do ghusl?"},
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
        assert isinstance(result, dict)
        assert result["collection"] == "enriched_gemini"
        assert result["total_documents"] == 18835
        cats = result["categories"]
        assert isinstance(cats, list)
        assert len(cats) == 1
        assert cats[0]["code"] == "PT"
        assert cats[0]["document_count"] == 5200
        assert "Ghusl" in cats[0]["cluster_labels"]

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
                        "Ghusl": "How to do ghusl?",
                        "Wudu": "Does bleeding break wudu?",
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
            assert "source_registry" in repl.locals
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
            assert "tool_calls" in repl.locals
            assert isinstance(repl.locals["tool_calls"], list)
            assert len(repl.locals["tool_calls"]) == 0
            # Sub-agent tools
            for name in [
                "evaluate_results",
                "reformulate",
                "critique_answer",
            ]:
                assert name in repl.locals, f"Missing sub-agent tool: {name}"
                assert callable(repl.locals[name])
            # Composite tools
            for name in ["research", "draft_answer"]:
                assert name in repl.locals, f"Missing composite tool: {name}"
                assert callable(repl.locals[name])
        finally:
            repl.cleanup()


def _make_sub_agent_ns(kb_overview_data=None):
    """Helper: build setup code namespace with mock llm_query wired into _ctx."""
    mock_overview = kb_overview_data or {
        "collection": "test",
        "total_documents": 100,
        "categories": {
            "PT": {
                "name": "Prayer",
                "document_count": 50,
                "facets": {},
                "clusters": {"Ghusl": "How to perform ghusl?"},
            }
        },
    }
    code = build_search_setup_code(api_url="http://localhost:8091", kb_overview_data=mock_overview)
    # Provide dummy llm callables so bootstrap can wire them into _ctx
    ns: dict = {
        "llm_query": lambda prompt, model=None: "",
        "llm_query_batched": lambda prompts, model=None: [""] * len(prompts),
    }
    exec(code, ns)  # noqa: S102
    return ns


class TestEvaluateResults:
    """Tests for the evaluate_results sub-agent function."""

    def test_empty_results(self):
        ns = _make_sub_agent_ns()
        result = ns["evaluate_results"]("test question", [])
        assert isinstance(result, dict)
        assert result["ratings"] == []
        assert "No results" in result["suggestion"]

    def test_empty_results_from_dict(self):
        ns = _make_sub_agent_ns()
        result = ns["evaluate_results"]("test question", {"results": []})
        assert isinstance(result, dict)
        assert result["ratings"] == []
        assert "No results" in result["suggestion"]

    def test_calls_llm_query_batched(self):
        ns = _make_sub_agent_ns()
        calls = []

        def mock_batched(prompts, model=None):
            calls.extend(prompts)
            return ["RELEVANT CONFIDENCE:4"] * len(prompts)

        ns["_ctx"].llm_query_batched = mock_batched
        results = {"results": [{"id": "q1", "score": 0.8, "question": "Q", "answer": "A"}]}
        result = ns["evaluate_results"]("test question", results)
        assert len(calls) == 1
        assert "test question" in calls[0]
        assert "q1" in calls[0]
        assert isinstance(result, dict)
        assert result["ratings"][0]["id"] == "q1"
        assert result["ratings"][0]["rating"] == "RELEVANT"

    def test_accepts_dict_or_list(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "ok"
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["ok"] * len(prompts)
        hit = {"id": "q1", "score": 0.5, "question": "Q", "answer": "A"}
        # Dict form
        ns["evaluate_results"]("q", {"results": [hit]})
        # List form
        ns["evaluate_results"]("q", [hit])

    def test_handles_missing_fields(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["ok"] * len(prompts)
        ns["evaluate_results"]("q", [{"id": "q1"}])  # no score, question, answer

    def test_respects_top_n(self, capsys):
        ns = _make_sub_agent_ns()
        captured_prompts = []

        def mock_batched(prompts, model=None):
            captured_prompts.extend(prompts)
            return ["RELEVANT CONFIDENCE:4", "PARTIAL CONFIDENCE:3", "OFF-TOPIC CONFIDENCE:2"][
                : len(prompts)
            ]

        ns["_ctx"].llm_query_batched = mock_batched
        hits = [{"id": f"q{i}", "score": 0.5, "question": "Q", "answer": "A"} for i in range(10)]
        result = ns["evaluate_results"]("q", hits, top_n=3)
        assert len(captured_prompts) == 3
        for p in captured_prompts:
            assert p.count("score=") == 1
        assert isinstance(result, dict)
        assert len(result["ratings"]) == 3
        assert result["ratings"][0]["rating"] == "RELEVANT"
        assert result["ratings"][1]["rating"] == "PARTIAL"
        assert result["ratings"][2]["rating"] == "OFF-TOPIC"
        captured = capsys.readouterr()
        assert "3 rated" in captured.out

    def test_ids_assigned_by_index(self):
        """Each rating ID comes from the corresponding input result by index."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: [
            "RELEVANT CONFIDENCE:4",
            "OFF-TOPIC CONFIDENCE:1",
            "PARTIAL CONFIDENCE:3",
        ]
        hits = [
            {"id": "q1", "score": 0.5, "question": "Q1", "answer": "A"},
            {"id": "q10", "score": 0.6, "question": "Q10", "answer": "A"},
            {"id": "q2", "score": 0.4, "question": "Q2", "answer": "A"},
        ]
        result = ns["evaluate_results"]("q", hits)
        ratings_by_id = {r["id"]: r["rating"] for r in result["ratings"]}
        assert ratings_by_id["q1"] == "RELEVANT"
        assert ratings_by_id["q10"] == "OFF-TOPIC"
        assert ratings_by_id["q2"] == "PARTIAL"

    def test_unknown_rating_fallback(self):
        """No keyword in response → UNKNOWN rating."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: [
            "this result is somewhat useful"
        ]
        hits = [{"id": "q1", "score": 0.5, "question": "Q", "answer": "A"}]
        result = ns["evaluate_results"]("q", hits)
        assert len(result["ratings"]) == 1
        assert result["ratings"][0]["rating"] == "UNKNOWN"

    def test_suggestion_always_derived(self):
        """Suggestion is always derived algorithmically from ratings."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"]
        hits = [{"id": "q1", "score": 0.5, "question": "Q", "answer": "A"}]
        result = ns["evaluate_results"]("q", hits)
        assert result["suggestion"] != ""
        assert result["ratings"][0]["rating"] == "RELEVANT"

    def test_integer_ids_do_not_crash(self):
        """Cascade API returns int IDs — str() conversion must not TypeError."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: [
            "RELEVANT CONFIDENCE:4",
            "PARTIAL CONFIDENCE:3",
        ]
        hits = [
            {"id": 58, "score": 1.05, "question": "Cannabis delivery", "answer": "A"},
            {"id": 504, "score": 1.04, "question": "Accountant for adult co", "answer": "B"},
        ]
        result = ns["evaluate_results"]("test question", hits)
        assert len(result["ratings"]) == 2
        assert result["ratings"][0]["rating"] == "RELEVANT"

    def test_batched_eval_includes_answer_content(self):
        """Per-result prompts include answer text (up to 1000 chars)."""
        ns = _make_sub_agent_ns()
        captured = []
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: (
            captured.extend(prompts),
            ["RELEVANT CONFIDENCE:5"] * len(prompts),
        )[1]
        hits = [
            {
                "id": "q1",
                "score": 0.8,
                "question": "What is X?",
                "answer": "X is the answer to everything.",
            }
        ]
        ns["evaluate_results"]("test question", hits)
        assert len(captured) == 1
        assert "X is the answer to everything." in captured[0]

    def test_batched_eval_confidence_score(self):
        """Parse CONFIDENCE:5 -> confidence=5."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:5"]
        hits = [{"id": "q1", "score": 0.8, "question": "Q", "answer": "A"}]
        result = ns["evaluate_results"]("q", hits)
        assert result["ratings"][0]["confidence"] == 5

    def test_batched_eval_default_confidence(self):
        """Missing CONFIDENCE -> confidence=3."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT"]
        hits = [{"id": "q1", "score": 0.8, "question": "Q", "answer": "A"}]
        result = ns["evaluate_results"]("q", hits)
        assert result["ratings"][0]["confidence"] == 3

    def test_batched_eval_error_resilience(self):
        """One 'Error:' response -> UNKNOWN with confidence=0, others unaffected."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: [
            "RELEVANT CONFIDENCE:4",
            "Error: rate limit exceeded",
            "PARTIAL CONFIDENCE:2",
        ]
        hits = [
            {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": "q2", "score": 0.8, "question": "Q2", "answer": "A2"},
            {"id": "q3", "score": 0.7, "question": "Q3", "answer": "A3"},
        ]
        result = ns["evaluate_results"]("q", hits, top_n=3)
        assert result["ratings"][0]["rating"] == "RELEVANT"
        assert result["ratings"][0]["confidence"] == 4
        assert result["ratings"][1]["rating"] == "UNKNOWN"
        assert result["ratings"][1]["confidence"] == 0
        assert result["ratings"][2]["rating"] == "PARTIAL"
        assert result["ratings"][2]["confidence"] == 2

    def test_batched_eval_suggestion_derived(self):
        """3 relevant -> 'Proceed to synthesis'."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        hits = [{"id": f"q{i}", "score": 0.8, "question": "Q", "answer": "A"} for i in range(5)]
        result = ns["evaluate_results"]("q", hits)
        assert result["suggestion"] == "Proceed to synthesis"

    def test_batched_eval_raw_field_joined(self):
        """raw field is all responses joined by --- separator."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: [
            "RELEVANT CONFIDENCE:5",
            "PARTIAL CONFIDENCE:3",
        ]
        hits = [
            {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": "q2", "score": 0.8, "question": "Q2", "answer": "A2"},
        ]
        result = ns["evaluate_results"]("q", hits)
        assert "---" in result["raw"]
        assert "RELEVANT" in result["raw"]
        assert "PARTIAL" in result["raw"]

    def test_batched_eval_single_result(self):
        """top_n=1 edge case works."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:5"]
        hits = [{"id": "q1", "score": 0.9, "question": "Q", "answer": "A"}]
        result = ns["evaluate_results"]("q", hits, top_n=1)
        assert len(result["ratings"]) == 1
        assert result["ratings"][0]["rating"] == "RELEVANT"


class TestParseRatingLine:
    """Unit tests for _parse_rating_line helper."""

    def test_standard_format(self):
        from rlm_search.tools.subagent_tools import _parse_rating_line

        assert _parse_rating_line("[q1] RELEVANT CONFIDENCE:4") == ("q1", "RELEVANT", 4)
        assert _parse_rating_line("[q2] PARTIAL CONFIDENCE:2") == ("q2", "PARTIAL", 2)
        assert _parse_rating_line("[q3] OFF-TOPIC CONFIDENCE:5") == ("q3", "OFF-TOPIC", 5)

    def test_missing_confidence(self):
        from rlm_search.tools.subagent_tools import _parse_rating_line

        result = _parse_rating_line("[q1] RELEVANT")
        assert result == ("q1", "RELEVANT", 3)  # default confidence

    def test_unparseable_lines(self):
        from rlm_search.tools.subagent_tools import _parse_rating_line

        assert _parse_rating_line("") is None
        assert _parse_rating_line("Here are my evaluations:") is None
        assert _parse_rating_line("q1 RELEVANT CONFIDENCE:4") is None  # no brackets

    def test_off_topic_underscore_variant(self):
        from rlm_search.tools.subagent_tools import _parse_rating_line

        result = _parse_rating_line("[q1] OFF_TOPIC CONFIDENCE:3")
        assert result == ("q1", "OFF-TOPIC", 3)

    def test_extra_text_after_rating(self):
        from rlm_search.tools.subagent_tools import _parse_rating_line

        result = _parse_rating_line("[q1] RELEVANT (directly answers the question) CONFIDENCE:4")
        assert result == ("q1", "RELEVANT", 4)


class TestBatchFirstEvaluateResults:
    """Tests for the batch-first (single prompt) evaluate_results path."""

    def test_batch_first_happy_path(self):
        """When llm_query returns well-formatted batch response, llm_query_batched is NOT called."""
        ns = _make_sub_agent_ns()
        batch_calls = []

        def mock_llm(prompt, model=None):
            return "[q1] RELEVANT CONFIDENCE:4\n[q2] PARTIAL CONFIDENCE:3\n[q3] OFF-TOPIC CONFIDENCE:2"

        def mock_batched(prompts, model=None):
            batch_calls.append(len(prompts))
            return ["RELEVANT CONFIDENCE:4"] * len(prompts)

        ns["_ctx"].llm_query = mock_llm
        ns["_ctx"].llm_query_batched = mock_batched

        hits = [
            {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": "q2", "score": 0.7, "question": "Q2", "answer": "A2"},
            {"id": "q3", "score": 0.5, "question": "Q3", "answer": "A3"},
        ]
        result = ns["evaluate_results"]("test question", hits, top_n=3)

        assert len(batch_calls) == 0, "llm_query_batched should NOT be called for batch-first path"
        assert len(result["ratings"]) == 3
        ratings_by_id = {r["id"]: r for r in result["ratings"]}
        assert ratings_by_id["q1"]["rating"] == "RELEVANT"
        assert ratings_by_id["q2"]["rating"] == "PARTIAL"
        assert ratings_by_id["q3"]["rating"] == "OFF-TOPIC"

    def test_batch_first_with_preamble(self):
        """Batch parse handles LLM preamble text before rating lines."""
        ns = _make_sub_agent_ns()

        def mock_llm(prompt, model=None):
            return "Here are my evaluations:\n\n[q1] RELEVANT CONFIDENCE:4\n[q2] PARTIAL CONFIDENCE:3"

        ns["_ctx"].llm_query = mock_llm

        hits = [
            {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": "q2", "score": 0.7, "question": "Q2", "answer": "A2"},
        ]
        result = ns["evaluate_results"]("test question", hits, top_n=2)

        assert len(result["ratings"]) == 2
        ratings_by_id = {r["id"]: r for r in result["ratings"]}
        assert ratings_by_id["q1"]["rating"] == "RELEVANT"
        assert ratings_by_id["q2"]["rating"] == "PARTIAL"

    def test_batch_first_fallback_on_bad_response(self, capsys):
        """When batch parse gets <50% of results, falls back to per-result calls."""
        ns = _make_sub_agent_ns()
        batch_calls = []

        def mock_llm(prompt, model=None):
            return "I cannot evaluate these results."  # no parseable lines

        def mock_batched(prompts, model=None):
            batch_calls.append(len(prompts))
            return ["RELEVANT CONFIDENCE:4"] * len(prompts)

        ns["_ctx"].llm_query = mock_llm
        ns["_ctx"].llm_query_batched = mock_batched

        hits = [
            {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": "q2", "score": 0.7, "question": "Q2", "answer": "A2"},
        ]
        result = ns["evaluate_results"]("test question", hits, top_n=2)

        assert len(batch_calls) == 1, "llm_query_batched should be called as fallback"
        assert batch_calls[0] == 2
        captured = capsys.readouterr()
        assert "falling back to per-result" in captured.out

    def test_batch_first_missing_ids_filled_as_unknown(self):
        """IDs not parsed from batch response get UNKNOWN rating."""
        ns = _make_sub_agent_ns()

        def mock_llm(prompt, model=None):
            return "[q1] RELEVANT CONFIDENCE:4"  # only 1 of 2

        ns["_ctx"].llm_query = mock_llm

        hits = [
            {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": "q2", "score": 0.7, "question": "Q2", "answer": "A2"},
        ]
        result = ns["evaluate_results"]("test question", hits, top_n=2)

        # 1/2 = 50% which meets the threshold (>= 50%), so batch path is used
        ratings_by_id = {r["id"]: r for r in result["ratings"]}
        assert ratings_by_id["q1"]["rating"] == "RELEVANT"
        assert ratings_by_id["q2"]["rating"] == "UNKNOWN"


class TestCrossCallDedup:
    """Tests for cross-call deduplication in research()."""

    def test_second_research_skips_already_rated(self, capsys):
        """When research() is called twice with overlapping results, evaluation is skipped for prior IDs."""
        from unittest.mock import MagicMock, patch

        ns = _make_sub_agent_ns()

        # Mock search_multi to return controlled hits
        hit_sets = iter([
            # First call returns q1, q2
            [
                {"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"},
                {"id": "q2", "score": 0.7, "question": "Q2", "answer": "A2"},
            ],
            # Second call returns q2 (overlap), q3 (new)
            [
                {"id": "q2", "score": 0.75, "question": "Q2", "answer": "A2"},
                {"id": "q3", "score": 0.6, "question": "Q3", "answer": "A3"},
            ],
        ])

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        def mock_post(*args, **kwargs):
            try:
                hits = next(hit_sets)
            except StopIteration:
                hits = []
            mock_resp.json.return_value = {"hits": hits, "total": len(hits)}
            return mock_resp

        eval_calls = []

        def mock_llm(prompt, model=None):
            """Track evaluate_results batch prompts by checking for the batch format."""
            if "For each result" in prompt:
                eval_calls.append(prompt)
            # Return ratings for any IDs found in the prompt
            lines = []
            for rid in ["q1", "q2", "q3"]:
                if f"[{rid}]" in prompt:
                    lines.append(f"[{rid}] RELEVANT CONFIDENCE:4")
            return "\n".join(lines) if lines else "PASS"

        ns["_ctx"].llm_query = mock_llm

        with patch("rlm_search.tools.api_tools.requests.post", side_effect=mock_post):
            # First research call — should evaluate q1, q2
            r1 = ns["research"]("question 1")
            assert len(eval_calls) == 1
            assert "[q1]" in eval_calls[0]
            assert "[q2]" in eval_calls[0]

            # Second research call — should only evaluate q3 (q2 already rated)
            r2 = ns["research"]("question 2")
            assert len(eval_calls) == 2
            assert "[q3]" in eval_calls[1]
            assert "[q2]" not in eval_calls[1]  # q2 was already rated

    def test_evaluated_ratings_persist_on_context(self):
        """evaluated_ratings accumulates across research() calls."""
        from unittest.mock import MagicMock, patch

        ns = _make_sub_agent_ns()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "q1", "score": 0.9, "question": "Q1", "answer": "A1"}],
            "total": 1,
        }

        ns["_ctx"].llm_query = lambda prompt, model=None: "[q1] RELEVANT CONFIDENCE:4"

        with patch("rlm_search.tools.api_tools.requests.post", return_value=mock_resp):
            ns["research"]("question")

        assert "q1" in ns["_ctx"].evaluated_ratings
        assert ns["_ctx"].evaluated_ratings["q1"] == "RELEVANT"


class TestReformulate:
    """Tests for the reformulate sub-agent function."""

    def test_returns_list(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "query one\nquery two\nquery three"
        result = ns["reformulate"]("question", "failed query", 0.1)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == "query one"

    def test_caps_at_three(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "q1\nq2\nq3\nq4\nq5"
        result = ns["reformulate"]("question", "failed", 0.1)
        assert len(result) <= 3

    def test_strips_empty_lines(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "\nq1\n\nq2\n\n"
        result = ns["reformulate"]("question", "failed", 0.1)
        assert result == ["q1", "q2"]

    def test_prompt_contains_score(self):
        ns = _make_sub_agent_ns()
        calls = []
        ns["_ctx"].llm_query = lambda prompt, model=None: (calls.append(prompt), "q1")[1]
        ns["reformulate"]("question", "bad query", 0.18)
        assert "0.18" in calls[0]


class TestCritiqueAnswer:
    """Tests for critique_answer."""

    def test_pass_verdict(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "PASS - all citations verified"
        result = ns["critique_answer"]("question", "draft answer")
        assert result["passed"] is True
        assert "PASS" in result["verdict"]

    def test_fail_verdict(self, capsys):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "FAIL - missing citations"
        result = ns["critique_answer"]("question", "draft")
        assert result["passed"] is False
        assert "FAIL" in result["verdict"]
        captured = capsys.readouterr()
        assert "verdict=FAIL" in captured.out

    def test_returns_dict_with_verdict_and_passed(self):
        """critique_answer returns dict with verdict and passed keys."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "PASS — ok"
        result = ns["critique_answer"]("question", "draft")
        assert isinstance(result, dict)
        assert "verdict" in result
        assert "passed" in result
        assert result["passed"] is True

    def test_auto_pulls_evidence_from_source_registry(self):
        """When evidence omitted, auto-builds from source_registry."""
        ns = _make_sub_agent_ns()
        prompts_seen = []

        def capture_prompt(prompt, model=None):
            prompts_seen.append(prompt)
            return "PASS\nAll good."

        ns["_ctx"].llm_query = capture_prompt
        ns["_ctx"].evidence.register_hit(
            {"id": "42", "question": "Test Q", "answer": "Test A"}
        )
        result = ns["critique_answer"]("question", "draft [Source: 42]")
        assert result["passed"] is True
        # Should have used evidence-grounded path (CITATION ACCURACY check)
        assert "CITATION ACCURACY" in prompts_seen[0]
        assert "[Source: 42]" in prompts_seen[0]

    def test_explicit_evidence_takes_precedence(self):
        """Explicit evidence param is used even when source_registry exists."""
        ns = _make_sub_agent_ns()
        prompts_seen = []

        def capture_prompt(prompt, model=None):
            prompts_seen.append(prompt)
            return "PASS\nOK"

        ns["_ctx"].llm_query = capture_prompt
        ns["_ctx"].evidence.register_hit(
            {"id": "99", "question": "Noise", "answer": "Should not appear"}
        )
        evidence = ["[Source: 1] Q: Real A: Evidence"]
        result = ns["critique_answer"]("question", "draft", evidence=evidence)
        assert result["passed"] is True
        assert "[Source: 1] Q: Real A: Evidence" in prompts_seen[0]
        assert "Noise" not in prompts_seen[0]


class TestClassificationInSetupCode:
    """Tests for init_classify() wired into setup_code."""

    def test_classify_question_wrapper_removed(self):
        """classify_question should no longer be in the generated namespace."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "classify_question" not in ns

    def test_classification_variable_exposed(self):
        """classification variable should be defined in the namespace."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "classification" in ns
        # Without query, init_classify is not called, so classification is None
        assert ns["classification"] is None

    @patch("rlm_search.tools.api_tools.requests.post")
    @patch("rlm_search.tools.subagent_tools.get_client")
    @patch("rlm_search.config.RLM_BACKEND", "claude_cli")
    @patch("rlm_search.config.ANTHROPIC_API_KEY", "")
    def test_init_classify_called_with_query(self, mock_get_client, mock_post):
        """When query is provided, init_classify runs and sets classification."""
        mock_client = MagicMock()
        mock_client.completion.return_value = "CATEGORY: PT"
        mock_get_client.return_value = mock_client

        # Mock browse response for Phase 2
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": [],
            "total": 50,
            "has_more": False,
            "facets": {"clusters": [], "subtopics": []},
            "grouped_results": {
                "clusters": [
                    {"label": "Ghusl", "total_count": 50, "hits": [{"question": "How to perform ghusl?"}]},
                ]
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        kb = {
            "categories": {
                "PT": {"name": "Prayer", "clusters": {"Ghusl": "g"}},
            },
            "total_documents": 50,
        }
        code = build_search_setup_code(
            api_url="http://localhost:8091",
            kb_overview_data=kb,
            query="How to perform ghusl?",
            classify_model="test-model",
        )
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["classification"] is not None
        assert ns["classification"]["category"] == "PT"
        assert ns["classification"]["filters"] == {"parent_code": "PT"}


def _make_search_mock(hits=None):
    """Helper: create a mock requests.post that returns given hits."""
    if hits is None:
        hits = [
            {"id": 1, "score": 0.9, "question": "Q1", "answer": "A1"},
            {"id": 2, "score": 0.7, "question": "Q2", "answer": "A2"},
            {"id": 3, "score": 0.5, "question": "Q3", "answer": "A3"},
        ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": hits, "total": len(hits)}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestResearch:
    """Tests for the research() composite tool."""

    def test_basic_research(self, capsys):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: [
            "RELEVANT CONFIDENCE:4" if i == 0 else "PARTIAL CONFIDENCE:3"
            for i in range(len(prompts))
        ]
        mock_resp = _make_search_mock()

        with patch(_API_POST, return_value=mock_resp):
            result = ns["research"]("test question")

        assert "results" in result
        assert "ratings" in result
        assert result["search_count"] == 1
        assert len(result["results"]) >= 1
        captured = capsys.readouterr()
        assert "[research]" in captured.out

    def test_extra_queries(self, capsys):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        mock_resp = _make_search_mock()

        with patch(_API_POST, return_value=mock_resp):
            result = ns["research"](
                "main query",
                extra_queries=[
                    {"query": "angle one"},
                    {"query": "angle two", "filters": {"parent_code": "FN"}},
                ],
            )

        assert result["search_count"] == 3  # primary + 2 extra

    def test_deduplicates_by_id(self):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        # Two searches return overlapping results
        hits_a = [{"id": 1, "score": 0.9, "question": "Q1", "answer": "A1"}]
        hits_b = [{"id": 1, "score": 0.5, "question": "Q1", "answer": "A1"}]
        call_count = {"n": 0}

        def mock_post(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "hits": hits_a if call_count["n"] == 1 else hits_b,
                "total": 1,
            }
            return resp

        with patch(_API_POST, side_effect=mock_post):
            result = ns["research"]("query", extra_queries=[{"query": "other"}])

        # Should deduplicate: one result, keeping highest score
        ids = [r["id"] for r in result["results"]]
        assert ids.count("1") == 1
        assert result["results"][0]["score"] == 0.9

    def test_filters_off_topic(self, capsys):
        ns = _make_sub_agent_ns()
        # Per-result responses: first RELEVANT, second OFF-TOPIC, third PARTIAL
        batched_responses = [
            "RELEVANT CONFIDENCE:4",
            "OFF-TOPIC CONFIDENCE:1",
            "PARTIAL CONFIDENCE:3",
        ]
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: batched_responses[: len(prompts)]
        mock_resp = _make_search_mock()

        with patch(_API_POST, return_value=mock_resp):
            result = ns["research"]("question")

        result_ids = {r["id"] for r in result["results"]}
        assert "2" not in result_ids  # OFF-TOPIC filtered out
        assert "1" in result_ids
        assert "3" in result_ids

    def test_handles_search_error(self, capsys):
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query = lambda prompt, model=None: "1 RELEVANT"

        def failing_post(*args, **kwargs):
            raise Exception("Connection refused")

        with patch(_API_POST, side_effect=failing_post):
            result = ns["research"]("query")

        assert result["results"] == []
        assert result["eval_summary"] == "no results"
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "ERROR" in captured.out

    def test_handles_partial_search_failure(self, capsys):
        """One extra_query fails but primary succeeds."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        call_count = {"n": 0}

        def mixed_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise Exception("timeout")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "hits": [{"id": 1, "score": 0.8, "question": "Q", "answer": "A"}],
                "total": 1,
            }
            return resp

        with patch(_API_POST, side_effect=mixed_post):
            result = ns["research"]("query", extra_queries=[{"query": "fail"}])

        assert len(result["results"]) >= 1  # primary results survived
        assert result["search_count"] == 1  # primary succeeded, extra failed (no fallback)


class TestResearchListQuery:
    """Tests for research() list-of-specs (multi-topic) mode."""

    def test_list_query_basic(self, capsys):
        """List of specs runs all queries and merges results."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        call_count = {"n": 0}

        def mock_post(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "hits": [
                    {
                        "id": call_count["n"],
                        "score": 0.8,
                        "question": f"Q{call_count['n']}",
                        "answer": "A",
                    }
                ],
                "total": 1,
            }
            return resp

        with patch(_API_POST, side_effect=mock_post):
            result = ns["research"](
                [
                    {"query": "topic one", "filters": {"parent_code": "FN"}},
                    {"query": "topic two", "filters": {"parent_code": "MF"}},
                ]
            )

        assert result["search_count"] == 2
        assert len(result["results"]) == 2
        captured = capsys.readouterr()
        assert "[research]" in captured.out

    def test_list_query_with_per_spec_extra_queries(self, capsys):
        """Each spec can carry its own extra_queries."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        mock_resp = _make_search_mock()

        with patch(_API_POST, return_value=mock_resp):
            result = ns["research"](
                [
                    {
                        "query": "topic one",
                        "extra_queries": [{"query": "angle 1a"}, {"query": "angle 1b"}],
                    },
                    {"query": "topic two"},
                ]
            )

        # spec 1: primary + 2 extra = 3; spec 2: primary = 1; total = 4
        assert result["search_count"] == 4

    def test_list_query_deduplicates_across_specs(self):
        """Results from different specs are deduped by ID."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        # Both specs return the same ID
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": 1, "score": 0.9, "question": "Q1", "answer": "A1"}],
            "total": 1,
        }

        with patch(_API_POST, return_value=mock_resp):
            result = ns["research"](
                [
                    {"query": "topic one"},
                    {"query": "topic two"},
                ]
            )

        ids = [r["id"] for r in result["results"]]
        assert ids.count("1") == 1

    def test_list_query_partial_spec_failure(self, capsys):
        """One spec fails, others succeed — partial results returned."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        call_count = {"n": 0}

        def mixed_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("timeout")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "hits": [{"id": 1, "score": 0.8, "question": "Q", "answer": "A"}],
                "total": 1,
            }
            return resp

        with patch(_API_POST, side_effect=mixed_post):
            result = ns["research"](
                [
                    {"query": "failing topic"},
                    {"query": "working topic"},
                ]
            )

        assert len(result["results"]) >= 1
        assert result["search_count"] == 1  # first spec failed (no fallback), second succeeded

    def test_list_query_empty_list(self, capsys):
        """Empty list returns immediately with no-results dict."""
        ns = _make_sub_agent_ns()
        result = ns["research"]([])

        assert result["results"] == []
        assert result["search_count"] == 0
        assert result["eval_summary"] == "no queries provided"
        captured = capsys.readouterr()
        assert "empty query list" in captured.out

    def test_list_query_single_spec(self, capsys):
        """Single-element list works identically to string query."""
        ns = _make_sub_agent_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        mock_resp = _make_search_mock()

        with patch(_API_POST, return_value=mock_resp):
            result = ns["research"]([{"query": "single topic"}])

        assert result["search_count"] == 1
        assert len(result["results"]) >= 1

    def test_list_query_eval_question_joins_queries(self):
        """List mode passes joined query strings to evaluate_results."""
        ns = _make_sub_agent_ns()
        captured_prompts = []

        def tracking_batched(prompts, model=None):
            captured_prompts.extend(prompts)
            return ["RELEVANT CONFIDENCE:4"] * len(prompts)

        ns["_ctx"].llm_query_batched = tracking_batched
        mock_resp = _make_search_mock()

        with patch(_API_POST, return_value=mock_resp):
            ns["research"](
                [
                    {"query": "salary from fraud"},
                    {"query": "selling clothing"},
                ]
            )

        # Each per-result prompt should contain the joined question
        assert len(captured_prompts) >= 1
        assert "salary from fraud" in captured_prompts[0]
        assert "selling clothing" in captured_prompts[0]


class TestResearchEvalCoverage:
    """Test that research() evaluates up to 15 results with batched eval."""

    def test_evaluates_up_to_15_results(self):
        """research() sends up to 15 results to evaluate_results."""
        ns = _make_sub_agent_ns()
        captured_prompts = []

        def tracking_batched(prompts, model=None):
            captured_prompts.extend(prompts)
            return ["RELEVANT CONFIDENCE:4"] * len(prompts)

        ns["_ctx"].llm_query_batched = tracking_batched
        hits = [
            {"id": i, "score": 1.0 - i * 0.01, "question": f"Q{i}", "answer": f"A{i}"}
            for i in range(20)
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": hits, "total": 20}
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp):
            ns["research"]("test question")

        assert len(captured_prompts) == 15


class TestDraftAnswer:
    """Tests for the draft_answer() composite tool."""

    def test_pass_on_first_try(self, capsys):
        ns = _make_sub_agent_ns()
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            if call_count["n"] == 1:  # synthesis
                return "## Answer\nTest answer [Source: 1]\n## Evidence\n- [Source: 1]\n## Confidence\nHigh"
            return "PASS — content and citations ok"  # unified critique

        ns["_ctx"].llm_query = mock_llm

        results = [
            {"id": "1", "score": 0.9, "question": "Q", "answer": "A"},
        ]
        out = ns["draft_answer"]("question", results)

        assert out["passed"] is True
        assert out["revised"] is False
        assert "## Answer" in out["answer"]
        captured = capsys.readouterr()
        assert "[draft_answer] PASS" in captured.out

    def test_revises_on_fail(self, capsys):
        ns = _make_sub_agent_ns()
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            if call_count["n"] == 1:  # synthesis
                return "Bad draft"
            if call_count["n"] == 2:  # first critique -> FAIL
                return "FAIL — missing citations and sources"
            if call_count["n"] == 3:  # revision
                return "## Answer\nRevised [Source: 1]\n## Evidence\n## Confidence\nHigh"
            return "PASS — fixed"  # second critique -> PASS

        ns["_ctx"].llm_query = mock_llm

        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        out = ns["draft_answer"]("question", results)

        assert out["revised"] is True
        assert out["passed"] is True
        assert call_count["n"] == 4  # synthesis + critique + revision + critique
        captured = capsys.readouterr()
        assert "(revised)" in captured.out

    def test_empty_results(self, capsys):
        ns = _make_sub_agent_ns()
        out = ns["draft_answer"]("question", [])

        assert out["answer"] == ""
        assert out["passed"] is False
        captured = capsys.readouterr()
        assert "ERROR" in captured.out

    def test_instructions_included_in_prompt(self):
        ns = _make_sub_agent_ns()
        captured_prompt = []
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            captured_prompt.append(prompt)
            if call_count["n"] == 1:  # synthesis
                return "## Answer\nTest [Source: 1]"
            return "PASS — ok"  # critique

        ns["_ctx"].llm_query = mock_llm

        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        ns["draft_answer"]("question", results, instructions="address all 4 scenarios")

        assert "address all 4 scenarios" in captured_prompt[0]

    def test_unified_critique_pass(self, capsys):
        """Unified critique PASS -> overall PASS."""
        ns = _make_sub_agent_ns()
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            if call_count["n"] == 1:  # synthesis
                return "## Answer\nTest [Source: 1]"
            return "PASS — content and citations ok"  # critique

        ns["_ctx"].llm_query = mock_llm

        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        out = ns["draft_answer"]("question", results)

        assert out["passed"] is True
        captured = capsys.readouterr()
        assert "verdict=PASS" in captured.out

    def test_unified_critique_fail_triggers_revision(self, capsys):
        """Unified critique FAIL triggers revision."""
        ns = _make_sub_agent_ns()
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            if call_count["n"] == 1:  # synthesis
                return "Bad draft"
            if call_count["n"] == 2:  # first critique -> FAIL
                return "FAIL — missing citations for key claims"
            if call_count["n"] == 3:  # revision
                return "## Answer\nRevised [Source: 1]"
            return "PASS — fixed"  # second critique -> PASS

        ns["_ctx"].llm_query = mock_llm

        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        out = ns["draft_answer"]("question", results)

        assert out["revised"] is True
        assert out["passed"] is True
        captured = capsys.readouterr()
        assert "failed: evidence-grounded review" in captured.out

    def test_unified_critique_feedback_in_revision(self):
        """Revision prompt includes the unified critique feedback."""
        ns = _make_sub_agent_ns()
        captured_prompts = []
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            captured_prompts.append(prompt)
            if call_count["n"] == 1:  # synthesis
                return "Bad draft"
            if call_count["n"] == 2:  # first critique -> FAIL
                return "FAIL — missing citations for key claims about riba"
            if call_count["n"] == 3:  # revision
                return "## Answer\nRevised [Source: 1]"
            return "PASS"  # second critique -> PASS

        ns["_ctx"].llm_query = mock_llm

        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        ns["draft_answer"]("question", results)

        revision_prompt = captured_prompts[2]  # 3rd call is revision
        assert "missing citations" in revision_prompt


class TestToolCallsTracking:
    """Tests for structured tool call tracking via tool_calls list."""

    def _exec_ns(self):
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {
            "llm_query": lambda prompt, model=None: "",
            "llm_query_batched": lambda prompts, model=None: [""] * len(prompts),
        }
        exec(code, ns)  # noqa: S102
        return ns

    def test_tool_calls_initialized_empty(self):
        """tool_calls list exists and is empty after setup."""
        ns = self._exec_ns()
        assert "tool_calls" in ns
        assert isinstance(ns["tool_calls"], list)
        assert len(ns["tool_calls"]) == 0

    def test_search_records_tool_call(self):
        """search() appends an entry with correct tool/args/summary/duration."""
        ns = self._exec_ns()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "1", "score": 0.9, "question": "q", "answer": "a"}],
            "total": 1,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp):
            ns["search"]("test query", top_k=5)

        assert len(ns["tool_calls"]) == 1
        tc = ns["tool_calls"][0]
        assert tc["tool"] == "search"
        assert tc["args"]["query"] == "test query"
        assert tc["args"]["top_k"] == 5
        assert tc["result_summary"]["num_results"] == 1
        assert tc["result_summary"]["total"] == 1
        assert tc["result_summary"]["query"] == "test query"
        assert tc["duration_ms"] >= 0
        assert tc["error"] is None
        assert tc["children"] == []

    def test_browse_records_tool_call(self):
        """browse() appends an entry with correct fields."""
        ns = self._exec_ns()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "1", "question": "q", "answer": "a"}],
            "total": 42,
            "has_more": True,
            "facets": {},
            "grouped_results": [],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp):
            ns["browse"](filters={"parent_code": "PT"})

        assert len(ns["tool_calls"]) == 1
        tc = ns["tool_calls"][0]
        assert tc["tool"] == "browse"
        assert tc["result_summary"]["num_results"] == 1
        assert tc["result_summary"]["total"] == 42
        assert tc["error"] is None

    def test_fiqh_lookup_records_tool_call(self):
        """fiqh_lookup() appends an entry with correct fields."""
        ns = self._exec_ns()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "bridges": [{"canonical": "salah"}],
            "related": [{"term": "qasr"}, {"term": "jamaa"}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_GET, return_value=mock_resp):
            ns["fiqh_lookup"]("prayer")

        assert len(ns["tool_calls"]) == 1
        tc = ns["tool_calls"][0]
        assert tc["tool"] == "fiqh_lookup"
        assert tc["args"]["query"] == "prayer"
        assert tc["result_summary"]["num_bridges"] == 1
        assert tc["result_summary"]["num_related"] == 2

    def test_research_records_parent_children(self):
        """research() has children indices pointing to search + evaluate calls."""
        ns = self._exec_ns()
        ns["_ctx"].llm_query_batched = lambda prompts, model=None: ["RELEVANT CONFIDENCE:4"] * len(
            prompts
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}],
            "total": 1,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp):
            ns["research"]("test question")

        # research is the parent (idx 0), search is child (idx 1), evaluate is child (idx 2)
        assert len(ns["tool_calls"]) >= 3
        research_tc = ns["tool_calls"][0]
        assert research_tc["tool"] == "research"
        assert len(research_tc["children"]) >= 2
        # Children should include search and evaluate_results
        child_tools = [ns["tool_calls"][i]["tool"] for i in research_tc["children"]]
        assert "search" in child_tools
        assert "evaluate_results" in child_tools
        assert research_tc["result_summary"]["search_count"] == 1

    def test_draft_answer_records_parent_children(self):
        """draft_answer() has critique_answer as child."""
        ns = self._exec_ns()
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            if call_count["n"] == 1:  # synthesis
                return "## Answer\nTest [Source: 1]\n## Evidence\n## Confidence\nHigh"
            return "PASS — good"  # critique

        ns["_ctx"].llm_query = mock_llm

        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        ns["draft_answer"]("question", results)

        assert len(ns["tool_calls"]) >= 2
        draft_tc = ns["tool_calls"][0]
        assert draft_tc["tool"] == "draft_answer"
        assert draft_tc["result_summary"]["passed"] is True
        assert len(draft_tc["children"]) >= 1
        child_tools = [ns["tool_calls"][i]["tool"] for i in draft_tc["children"]]
        assert "critique_answer" in child_tools

    def test_critique_answer_tracked(self):
        """critique_answer records tool call with verdict summary."""
        ns = self._exec_ns()
        call_count = {"n": 0}

        def mock_llm(prompt, model=None):
            call_count["n"] += 1
            if call_count["n"] == 1:  # synthesis
                return "## Answer\nTest [Source: 1]"
            return "FAIL — missing citation for key claim"

        ns["_ctx"].llm_query = mock_llm
        results = [{"id": "1", "score": 0.9, "question": "Q", "answer": "A"}]
        ns["draft_answer"]("question", results)

        critique_entries = [tc for tc in ns["tool_calls"] if tc["tool"] == "critique_answer"]
        assert len(critique_entries) >= 1
        tc = critique_entries[0]
        assert tc["result_summary"]["verdict"] == "FAIL"
        assert tc["duration_ms"] >= 0

    def test_tool_call_captures_error(self):
        """Failed API call populates the error field."""
        ns = self._exec_ns()

        with patch(_API_POST, side_effect=Exception("Connection refused")):
            try:
                ns["search"]("test")
            except Exception:
                pass

        assert len(ns["tool_calls"]) == 1
        tc = ns["tool_calls"][0]
        assert tc["error"] is not None
        assert "Connection refused" in tc["error"]

    def test_tool_calls_accumulate(self):
        """Multiple calls grow the tool_calls list."""
        ns = self._exec_ns()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch(_API_POST, return_value=mock_resp):
            ns["search"]("q1")
            ns["search"]("q2")
            ns["browse"]()

        assert len(ns["tool_calls"]) == 3
        assert ns["tool_calls"][0]["tool"] == "search"
        assert ns["tool_calls"][1]["tool"] == "search"
        assert ns["tool_calls"][2]["tool"] == "browse"


# --- KB fixture with categories and clusters for progress tests ---

_KB_PROGRESS = {
    "collection": "test",
    "total_documents": 5000,
    "categories": {
        "FN": {
            "name": "Finance & Transactions",
            "document_count": 2000,
            "clusters": {"Zakat": "How to calculate zakat?"},
            "facets": {
                "clusters": [
                    {"value": "Zakat", "count": 500},
                    {"value": "Banking", "count": 300},
                ]
            },
        },
        "PT": {
            "name": "Prayer & Tahara",
            "document_count": 2500,
            "clusters": {"Ghusl": "How to perform ghusl?"},
            "facets": {
                "clusters": [
                    {"value": "Ghusl", "count": 400},
                    {"value": "Wudu", "count": 350},
                ]
            },
        },
        "BE": {
            "name": "Beliefs & Ethics",
            "document_count": 500,
            "clusters": {"Iman": "What is iman?"},
            "facets": {
                "clusters": [
                    {"value": "Iman", "count": 200},
                ]
            },
        },
    },
}


_UNSET = object()


class TestCheckProgress:
    """Tests for the check_progress() progress advisor."""

    def _exec_ns(self, kb_data=_UNSET):
        data = _KB_PROGRESS if kb_data is _UNSET else kb_data
        code = build_search_setup_code(api_url="http://api.test", kb_overview_data=data)
        ns: dict = {
            "llm_query": lambda prompt, model=None: "",
            "llm_query_batched": lambda prompts, model=None: [""] * len(prompts),
        }
        exec(code, ns)  # noqa: S102
        return ns

    def test_empty_state(self, capsys):
        """No mutations → phase=continue, confidence<30."""
        ns = self._exec_ns()
        result = ns["check_progress"]()

        assert result["phase"] == "continue"
        assert result["confidence"] < 30
        assert result["searches_run"] == 0
        assert result["unique_sources"] == 0
        captured = capsys.readouterr()
        assert "[check_progress]" in captured.out
        assert "continue" in captured.out

    def test_ready_with_relevant_results(self):
        """3 relevant sources with good scores → phase=ready, confidence>=60."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        # Register 3 hits and rate them RELEVANT via evidence store
        for i in range(3):
            ctx.evidence.register_hit({"id": str(i), "question": "Q", "answer": "A", "score": 0.8})
            ctx.evidence.set_rating(str(i), "RELEVANT", confidence=4)
        # Log searches (breadth factor needs >= 2 to cross 60 threshold)
        ctx.evidence.log_search(query="q1", num_results=3)
        ctx.evidence.log_search(query="q2", num_results=3)

        result = ns["check_progress"]()
        assert result["phase"] == "ready"
        assert result["confidence"] >= 60

    def test_stalled_many_searches(self):
        """6+ searches with <2 relevant → phase=stalled."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        for i in range(6):
            ctx.evidence.log_search(
                query=f"query_{i}", num_results=2, filters={"parent_code": "FN"}
            )
        # Register 1 hit rated RELEVANT (<2 relevant triggers stalled)
        ctx.evidence.register_hit({"id": "0", "question": "Q", "answer": "A", "score": 0.3})
        ctx.evidence.set_rating("0", "RELEVANT", confidence=2)

        result = ns["check_progress"]()
        assert result["phase"] == "stalled"
        assert "reformulate" in result["guidance"]

    def test_repeating_low_diversity(self):
        """3 identical queries with no relevant → phase=continue (QualityGate has no repeating)."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        for _ in range(3):
            ctx.evidence.log_search(query="same query", num_results=3)

        result = ns["check_progress"]()
        assert result["phase"] == "continue"
        assert "No relevant results yet" in result["guidance"]

    def test_finalize_after_draft(self):
        """Draft recorded + critique passed + confidence>=60 → phase=finalize."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        # Build enough evidence for confidence >= 60
        for i in range(3):
            ctx.evidence.register_hit({"id": str(i), "question": "Q", "answer": "A", "score": 0.8})
            ctx.evidence.set_rating(str(i), "RELEVANT", confidence=4)
        ctx.evidence.log_search(query="q1", num_results=3)
        # Record draft and passing critique via QualityGate
        ctx.quality.record_draft(length=500)
        ctx.quality.record_critique(passed=True, verdict="PASS\nGood answer.")

        result = ns["check_progress"]()
        assert result["phase"] == "finalize"
        assert result["confidence"] >= 60

    def test_confidence_scoring(self):
        """Verify score ranges match QualityGate 5-factor formula."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        # Setup: 2 relevant, 2 partial, top_score=0.5, 3 searches, no draft
        for i in range(4):
            ctx.evidence.register_hit(
                {"id": str(i), "question": "Q", "answer": "A", "score": 0.5}
            )
        ctx.evidence.set_rating("0", "RELEVANT", confidence=4)
        ctx.evidence.set_rating("1", "RELEVANT", confidence=4)
        ctx.evidence.set_rating("2", "PARTIAL", confidence=3)
        ctx.evidence.set_rating("3", "PARTIAL", confidence=3)
        for j in range(3):
            ctx.evidence.log_search(
                query=f"q_{j}", num_results=4, filters={"parent_code": "FN"}
            )

        result = ns["check_progress"]()
        # QualityGate formula:
        #   relevance: min(35, int(35 * (2 + 0.3*2) / 4)) = 22
        #   top_score: min(25, int(25 * 0.5)) = 12
        #   breadth:   min(10, 3 * 3) = 9
        #   draft: 0, critique: 0
        #   total = 43
        assert 35 <= result["confidence"] <= 50

    def test_strategy_suggests_unexplored_category(self):
        """Only FN searched, no relevant → QualityGate gives generic continue guidance."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        ctx.evidence.log_search(query="q", num_results=3, filters={"parent_code": "FN"})

        result = ns["check_progress"]()
        # QualityGate guidance (no taxonomy strategy): generic continue text
        assert result["phase"] == "continue"
        assert "No relevant results yet" in result["guidance"]

    def test_strategy_suggests_unexplored_cluster(self):
        """All categories searched, no relevant → QualityGate gives generic continue guidance."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        # Mark all categories as explored
        for code in ["FN", "PT", "BE"]:
            ctx.evidence.log_search(query=f"q_{code}", num_results=3, filters={"parent_code": code})

        result = ns["check_progress"]()
        # QualityGate guidance: no taxonomy-aware strategy, just generic continue
        assert result["phase"] == "continue"
        assert "No relevant results yet" in result["guidance"]

    def test_audit_trail_printed(self, capsys):
        """3 searches → capsys contains numbered list and diversity ratio."""
        ns = self._exec_ns()
        ctx = ns["_ctx"]
        ctx.search_log.extend(
            [
                {
                    "type": "search",
                    "query": "zakat crypto",
                    "filters": {"parent_code": "FN"},
                    "num_results": 5,
                },
                {
                    "type": "search",
                    "query": "bitcoin halal",
                    "filters": {"parent_code": "FN"},
                    "num_results": 4,
                },
                {"type": "search", "query": "digital currency", "filters": None, "num_results": 6},
            ]
        )

        ns["check_progress"]()
        captured = capsys.readouterr()
        assert '1. "zakat crypto"' in captured.out
        assert '2. "bitcoin halal"' in captured.out
        assert '3. "digital currency"' in captured.out
        assert "Diversity: 3/3" in captured.out

    def test_stdout_tag(self, capsys):
        """Output contains [check_progress] tag."""
        ns = self._exec_ns()
        ns["check_progress"]()
        captured = capsys.readouterr()
        assert "[check_progress]" in captured.out

    def test_tool_call_tracked(self):
        """tool_calls entry has tool=check_progress with phase and confidence."""
        ns = self._exec_ns()
        ns["check_progress"]()

        tc = ns["tool_calls"][-1]
        assert tc["tool"] == "check_progress"
        assert "phase" in tc["result_summary"]
        assert "confidence" in tc["result_summary"]
        assert tc["duration_ms"] >= 0
        assert tc["error"] is None

    def test_no_kb_data_graceful(self):
        """kb_overview_data=None → still works, QualityGate gives generic guidance."""
        ns = self._exec_ns(kb_data=None)
        result = ns["check_progress"]()

        assert result["phase"] == "continue"
        assert "No relevant results yet" in result["guidance"]


class TestRlmQuery:
    """Tests for the rlm_query() delegation tool."""

    def _exec_ns(self, depth=0):
        """Build namespace with depth=0 (root) to get rlm_query wrapper."""
        code = build_search_setup_code(
            api_url="http://api.test",
            rlm_model="test-model",
            depth=depth,
        )
        ns: dict = {
            "llm_query": lambda prompt, model=None: "",
            "llm_query_batched": lambda prompts, model=None: [""] * len(prompts),
        }
        exec(code, ns)  # noqa: S102
        return ns

    def test_wrapper_emitted_at_depth_0(self):
        """rlm_query wrapper must be defined at depth=0."""
        code = build_search_setup_code(api_url="http://api.test", rlm_model="m", depth=0)
        assert "rlm_query" in code
        assert "delegation_tools" in code

    def test_wrapper_not_emitted_at_depth_1(self):
        """rlm_query wrapper must NOT be emitted at depth=1."""
        code = build_search_setup_code(api_url="http://api.test", rlm_model="m", depth=1)
        assert "rlm_query" not in code
        assert "delegation_tools" not in code

    def test_context_fields_set(self):
        """_rlm_model and _depth must be set on ToolContext."""
        ns = self._exec_ns(depth=0)
        assert ns["_ctx"]._rlm_model == "test-model"
        assert ns["_ctx"]._depth == 0

    def test_context_fields_depth_1(self):
        """depth=1 context fields are set correctly (no rlm_query wrapper)."""
        code = build_search_setup_code(api_url="http://api.test", rlm_model="child-model", depth=1)
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_ctx"]._rlm_model == "child-model"
        assert ns["_ctx"]._depth == 1

    def test_depth_guard(self):
        """rlm_query at depth>=1 must return error dict."""
        ns = self._exec_ns(depth=0)
        # Override depth to simulate child calling rlm_query
        ns["_ctx"]._depth = 1
        result = ns["rlm_query"]("test sub-question")
        assert "error" in result
        assert "Cannot delegate" in result["error"]

    def test_tool_call_tracked(self):
        """Depth-guarded rlm_query call must be tracked in tool_calls."""
        ns = self._exec_ns(depth=0)
        ns["_ctx"]._depth = 1
        ns["rlm_query"]("test")
        assert len(ns["tool_calls"]) >= 1
        assert ns["tool_calls"][-1]["tool"] == "rlm_query"

    def test_stdout_tag(self, capsys):
        """rlm_query output must contain [rlm_query] tag."""
        ns = self._exec_ns(depth=0)
        ns["_ctx"]._depth = 1  # trigger guard path
        ns["rlm_query"]("test")
        captured = capsys.readouterr()
        assert "[rlm_query]" in captured.out

    def test_rlm_query_callable_at_depth_0(self):
        """rlm_query must be defined and callable in the namespace at depth=0."""
        ns = self._exec_ns(depth=0)
        assert "rlm_query" in ns
        assert callable(ns["rlm_query"])

    def test_names_available_in_repl_depth_0(self):
        """All standard tools + rlm_query must exist at depth=0."""
        code = build_search_setup_code(api_url="http://localhost:8091", rlm_model="m", depth=0)
        repl = LocalREPL(setup_code=code)
        try:
            assert "rlm_query" in repl.locals
            assert callable(repl.locals["rlm_query"])
            # Standard tools still present
            assert "search" in repl.locals
            assert "research" in repl.locals
        finally:
            repl.cleanup()

    def test_names_not_in_repl_depth_1(self):
        """rlm_query must NOT exist in namespace at depth=1."""
        code = build_search_setup_code(api_url="http://localhost:8091", rlm_model="m", depth=1)
        repl = LocalREPL(setup_code=code)
        try:
            assert "rlm_query" not in repl.locals
            # Standard tools still present
            assert "search" in repl.locals
            assert "research" in repl.locals
        finally:
            repl.cleanup()

    def test_max_delegation_depth_set(self):
        """_max_delegation_depth must be set on ToolContext."""
        code = build_search_setup_code(
            api_url="http://api.test", rlm_model="m", depth=0, max_delegation_depth=3
        )
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert ns["_ctx"]._max_delegation_depth == 3

    def test_wrapper_emitted_when_depth_lt_max(self):
        """rlm_query wrapper emitted when depth < max_delegation_depth."""
        code = build_search_setup_code(
            api_url="http://api.test", rlm_model="m", depth=1, max_delegation_depth=2
        )
        assert "rlm_query" in code

    def test_wrapper_not_emitted_when_depth_eq_max(self):
        """rlm_query wrapper NOT emitted when depth == max_delegation_depth."""
        code = build_search_setup_code(
            api_url="http://api.test", rlm_model="m", depth=2, max_delegation_depth=2
        )
        assert "rlm_query" not in code


# Mock target for _run_child_rlm
_CHILD_RLM = "rlm_search.tools.delegation_tools._run_child_rlm"


class _FakeResult:
    """Minimal stand-in for RLMChatCompletion."""

    def __init__(self, response: str = "test answer"):
        self.response = response
        self.usage_summary = None


class TestRlmQueryDelegation:
    """Tests for rlm_query() delegation with mocked _run_child_rlm."""

    def _make_ctx(self):
        """Build a ToolContext at depth=0 with rlm_model set."""
        from rlm_search.tools.context import ToolContext

        return ToolContext(
            api_url="http://api.test", api_key="k", _rlm_model="test-model", _depth=0
        )

    def test_happy_path(self, capsys):
        """Successful delegation returns structured result with stdout tags."""
        from rlm_search.tools.delegation_tools import rlm_query

        ctx = self._make_ctx()
        child_sources = {"src1": {"title": "Source 1"}}
        with patch(_CHILD_RLM, return_value=(_FakeResult("answer"), child_sources, 2)):
            result = rlm_query(ctx, "test question")

        assert result["answer"] == "answer"
        assert result["sub_question"] == "test question"
        assert result["searches_run"] == 2
        assert result["sources_merged"] == 1
        captured = capsys.readouterr()
        assert "[rlm_query] Delegating" in captured.out
        assert "[rlm_query] Complete" in captured.out

    def test_source_merging(self):
        """Child sources are merged into parent source_registry."""
        from rlm_search.tools.delegation_tools import rlm_query

        ctx = self._make_ctx()
        child_sources = {"src_a": {"title": "A"}, "src_b": {"title": "B"}}
        with patch(_CHILD_RLM, return_value=(_FakeResult(), child_sources, 1)):
            rlm_query(ctx, "q")

        assert "src_a" in ctx.source_registry
        assert "src_b" in ctx.source_registry

    def test_duplicate_source_not_overwritten(self):
        """Pre-existing parent source must not be overwritten by child."""
        from rlm_search.tools.delegation_tools import rlm_query

        ctx = self._make_ctx()
        ctx.source_registry["src_a"] = {"original": True}
        child_sources = {"src_a": {"original": False}, "src_b": {"title": "B"}}
        with patch(_CHILD_RLM, return_value=(_FakeResult(), child_sources, 1)):
            result = rlm_query(ctx, "q")

        assert ctx.source_registry["src_a"]["original"] is True
        assert "src_b" in ctx.source_registry
        assert result["sources_merged"] == 1  # only src_b counted

    def test_child_failure_returns_error(self):
        """_run_child_rlm exception is caught and returned as error dict."""
        from rlm_search.tools.delegation_tools import rlm_query

        ctx = self._make_ctx()
        with patch(_CHILD_RLM, side_effect=RuntimeError("API timeout")):
            result = rlm_query(ctx, "failing question")

        assert "error" in result
        assert "API timeout" in result["error"]
        assert result["searches_run"] == 0
        assert result["sources_merged"] == 0

    def test_child_failure_tracked_in_tool_calls(self):
        """Error handled inside with-block so tracker entry has error=None."""
        from rlm_search.tools.delegation_tools import rlm_query

        ctx = self._make_ctx()
        with patch(_CHILD_RLM, side_effect=RuntimeError("boom")):
            rlm_query(ctx, "q")

        assert len(ctx.tool_calls) >= 1
        assert ctx.tool_calls[-1]["error"] is None

    def test_empty_response_handled(self):
        """Empty child response does not crash."""
        from rlm_search.tools.delegation_tools import rlm_query

        ctx = self._make_ctx()
        with patch(_CHILD_RLM, return_value=(_FakeResult(""), {}, 0)):
            result = rlm_query(ctx, "q")

        assert result["answer"] == ""
        assert result["searches_run"] == 0
        assert result["sources_merged"] == 0


class TestCtxAccessViaWrapperGlobals:
    """Test that _ctx is accessible through wrapper function __globals__ after setup_code runs.

    LocalREPL filters variables starting with '_' from self.locals (line 438).
    So _ctx defined in setup_code is NOT in self.locals.  However, wrapper
    functions like search() defined in setup_code DO have _ctx in their
    __globals__ dict because they were exec'd in a namespace that includes _ctx.

    This is the pattern used by the follow-up session path in api.py to recover
    _ctx and update _parent_logger on reconnect.
    """

    def test_ctx_not_in_locals(self):
        """_ctx must be filtered out of repl.locals by the underscore filter."""

        code = build_search_setup_code(api_url="http://localhost")
        repl = LocalREPL(setup_code=code)
        try:
            assert "_ctx" not in repl.locals
        finally:
            repl.cleanup()

    def test_ctx_accessible_via_search_globals(self):
        """_ctx must be reachable through search().__globals__ as a ToolContext."""
        from rlm_search.tools.context import ToolContext

        code = build_search_setup_code(api_url="http://localhost")
        repl = LocalREPL(setup_code=code)
        try:
            search_fn = repl.locals["search"]
            _ctx = search_fn.__globals__["_ctx"]
            assert isinstance(_ctx, ToolContext)
            assert _ctx.api_url == "http://localhost"
        finally:
            repl.cleanup()

    def test_ctx_parent_logger_updatable_via_globals(self):
        """Mutating _ctx via one wrapper's __globals__ must be visible via another wrapper."""
        code = build_search_setup_code(api_url="http://localhost")
        repl = LocalREPL(setup_code=code)
        try:
            sentinel = object()

            # Set _parent_logger through search's __globals__
            search_fn = repl.locals["search"]
            _ctx = search_fn.__globals__["_ctx"]
            _ctx._parent_logger = sentinel

            # Read it back through browse's __globals__ — same namespace, same _ctx
            browse_fn = repl.locals["browse"]
            _ctx_via_browse = browse_fn.__globals__["_ctx"]
            assert _ctx_via_browse._parent_logger is sentinel
        finally:
            repl.cleanup()
