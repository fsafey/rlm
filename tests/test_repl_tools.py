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

    def test_defines_browse_function(self):
        """browse() must be defined in the generated namespace."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        assert "browse" in ns
        assert callable(ns["browse"])

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
    """Test that search() and browse() have the correct signatures."""

    def test_search_signature(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        sig = inspect.signature(ns["search"])
        params = list(sig.parameters.keys())
        assert "query" in params
        assert "filters" in params
        assert "top_k" in params

    def test_search_defaults(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        sig = inspect.signature(ns["search"])
        assert sig.parameters["filters"].default is None
        assert sig.parameters["top_k"].default == 10

    def test_browse_signature(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        sig = inspect.signature(ns["browse"])
        params = list(sig.parameters.keys())
        assert "filters" in params
        assert "offset" in params
        assert "limit" in params

    def test_browse_defaults(self):
        code = build_search_setup_code(api_url="http://localhost")
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        sig = inspect.signature(ns["browse"])
        assert sig.parameters["filters"].default is None
        assert sig.parameters["offset"].default == 0
        assert sig.parameters["limit"].default == 20


class TestSearchFunctionBehavior:
    """Test that search() and browse() call requests.post correctly (mocked)."""

    def test_search_calls_api(self):
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [{"id": "1", "score": 0.9, "question": "q", "answer": "a"}], "total": 1}
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

    def test_browse_calls_api(self):
        code = build_search_setup_code(api_url="http://api.test", api_key="k")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [{"id": "2", "question": "q", "answer": "a"}], "total": 1}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp) as mock_post:
            result = ns["browse"](filters={"parent_code": "PT"})

        mock_post.assert_called_once()
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "2"
        assert len(ns["search_log"]) == 1
        assert ns["search_log"][0]["type"] == "browse"

    def test_search_log_accumulates(self):
        code = build_search_setup_code(api_url="http://api.test")
        ns: dict = {}
        exec(code, ns)  # noqa: S102

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(ns["_requests"], "post", return_value=mock_resp):
            ns["search"]("q1")
            ns["search"]("q2")
            ns["browse"]()

        assert len(ns["search_log"]) == 3
        assert ns["search_log"][0]["query"] == "q1"
        assert ns["search_log"][1]["query"] == "q2"
        assert ns["search_log"][2]["type"] == "browse"


class TestSetupCodeInLocalREPL:
    """Test that setup code works when injected into a real LocalREPL."""

    def test_names_available_in_repl(self):
        """search, browse, search_log must exist in LocalREPL after setup."""
        code = build_search_setup_code(api_url="http://localhost:8091")
        repl = LocalREPL(setup_code=code)
        try:
            assert "search" in repl.locals
            assert "browse" in repl.locals
            assert "search_log" in repl.locals
            assert callable(repl.locals["search"])
            assert callable(repl.locals["browse"])
            assert isinstance(repl.locals["search_log"], list)
        finally:
            repl.cleanup()
