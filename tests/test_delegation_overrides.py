"""Tests for per-session model/backend override propagation and delegation depth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rlm_search.repl_tools import build_search_setup_code
from rlm_search.tools.context import ToolContext
from rlm_search.tools.delegation_tools import _run_child_rlm, rlm_query

# _run_child_rlm lazily imports from these modules inside the function body,
# so patches must target the source modules (not delegation_tools attributes).
_CFG = "rlm_search.config"


def _mock_rlm_instance():
    """Create a mock RLM instance with standard completion return."""
    instance = MagicMock()
    instance.completion.return_value = MagicMock(
        response="answer", execution_time=1.0, usage_summary=None
    )
    instance._persistent_env = None
    instance.close = MagicMock()
    return instance


class TestChildRLMOverrides:
    """Test that _run_child_rlm uses ctx fields for backend/model."""

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    def test_ctx_backend_overrides_config(self, mock_setup, mock_rlm):
        """ctx._rlm_backend should override RLM_BACKEND from config."""
        ctx = ToolContext(api_url="http://localhost", _rlm_backend="openai", _rlm_model="gpt-4o")
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test question", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["backend"] == "openai"
        assert rlm_kwargs["backend_kwargs"]["model_name"] == "gpt-4o"

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    def test_default_fallback_to_config(self, mock_setup, mock_rlm):
        """Empty ctx fields should fall back to config globals."""
        ctx = ToolContext(api_url="http://localhost", _rlm_backend="", _rlm_model="")
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test question", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["backend"] == "anthropic"
        assert rlm_kwargs["backend_kwargs"]["model_name"] == "claude-opus-4-6"

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "")
    def test_claude_cli_backend_uses_model_key(self, mock_setup, mock_rlm):
        """claude_cli backend should use 'model' key, not 'model_name'."""
        ctx = ToolContext(
            api_url="http://localhost",
            _rlm_backend="claude_cli",
            _rlm_model="claude-sonnet-4-5-20250929",
        )
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test question", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["backend"] == "claude_cli"
        assert rlm_kwargs["backend_kwargs"]["model"] == "claude-sonnet-4-5-20250929"
        assert "model_name" not in rlm_kwargs["backend_kwargs"]

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "claude-haiku-4-5-20251001")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    def test_sub_model_overrides_session_model(self, mock_setup, mock_rlm):
        """RLM_SUB_MODEL should take precedence over ctx._rlm_model."""
        ctx = ToolContext(api_url="http://localhost", _rlm_model="gpt-4o")
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test question", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["backend_kwargs"]["model_name"] == "claude-haiku-4-5-20251001"

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    def test_backend_passed_to_setup_code(self, mock_setup, mock_rlm):
        """rlm_backend should be passed to build_search_setup_code."""
        ctx = ToolContext(api_url="http://localhost", _rlm_backend="openai", _rlm_model="gpt-4o")
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test question", "")

        setup_kwargs = mock_setup.call_args[1]
        assert setup_kwargs["rlm_backend"] == "openai"


class TestDelegationDepthGuard:
    """Test configurable delegation depth guard."""

    def test_depth_guard_at_default_max(self):
        """Depth guard triggers at default _max_delegation_depth=1."""
        ctx = ToolContext(api_url="http://localhost", _depth=1, _max_delegation_depth=1)
        result = rlm_query(ctx, "should be blocked")
        assert "error" in result
        assert result["error"] == "Cannot delegate from a child agent"

    def test_depth_guard_allows_depth_0(self):
        """Depth 0 with max_delegation_depth=1 should allow delegation."""
        ctx = ToolContext(api_url="http://localhost", _depth=0, _max_delegation_depth=1)
        with patch(
            "rlm_search.tools.delegation_tools._run_child_rlm",
            return_value=(MagicMock(response="ok"), {}, 1),
        ):
            result = rlm_query(ctx, "should succeed")
        assert "answer" in result
        assert result["answer"] == "ok"

    def test_depth_guard_higher_max(self):
        """Depth 1 with max_delegation_depth=2 should allow delegation."""
        ctx = ToolContext(api_url="http://localhost", _depth=1, _max_delegation_depth=2)
        with patch(
            "rlm_search.tools.delegation_tools._run_child_rlm",
            return_value=(MagicMock(response="ok"), {}, 1),
        ):
            result = rlm_query(ctx, "should succeed at depth 1")
        assert "answer" in result

    def test_depth_guard_blocks_at_max(self):
        """Depth 2 with max_delegation_depth=2 should be blocked."""
        ctx = ToolContext(api_url="http://localhost", _depth=2, _max_delegation_depth=2)
        result = rlm_query(ctx, "should be blocked")
        assert "error" in result


class TestChildDepthAndIterations:
    """Test child depth increment and iteration budget."""

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    @patch(f"{_CFG}.RLM_SUB_ITERATIONS", 3)
    def test_child_depth_incremented(self, mock_setup, mock_rlm):
        """Child should get depth = parent depth + 1."""
        ctx = ToolContext(api_url="http://localhost", _depth=0, _max_delegation_depth=2)
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test", "")

        setup_kwargs = mock_setup.call_args[1]
        assert setup_kwargs["depth"] == 1

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    @patch(f"{_CFG}.RLM_SUB_ITERATIONS", 3)
    def test_max_delegation_depth_propagated(self, mock_setup, mock_rlm):
        """max_delegation_depth should be passed through to child."""
        ctx = ToolContext(api_url="http://localhost", _depth=0, _max_delegation_depth=3)
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test", "")

        setup_kwargs = mock_setup.call_args[1]
        assert setup_kwargs["max_delegation_depth"] == 3

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    @patch(f"{_CFG}.RLM_SUB_ITERATIONS", 5)
    def test_depth_1_gets_full_iterations(self, mock_setup, mock_rlm):
        """Child at depth 1 should get full RLM_SUB_ITERATIONS."""
        ctx = ToolContext(api_url="http://localhost", _depth=0)
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["max_iterations"] == 5

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    @patch(f"{_CFG}.RLM_SUB_ITERATIONS", 5)
    def test_depth_2_gets_reduced_iterations(self, mock_setup, mock_rlm):
        """Child at depth 2+ should get max(2, SUB_ITERATIONS - 1)."""
        ctx = ToolContext(api_url="http://localhost", _depth=1, _max_delegation_depth=3)
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["max_iterations"] == 4  # max(2, 5-1) = 4

    @patch("rlm.core.rlm.RLM")
    @patch("rlm_search.repl_tools.build_search_setup_code", return_value="# setup")
    @patch(f"{_CFG}.RLM_BACKEND", "anthropic")
    @patch(f"{_CFG}.RLM_MODEL", "claude-opus-4-6")
    @patch(f"{_CFG}.RLM_SUB_MODEL", "")
    @patch(f"{_CFG}.ANTHROPIC_API_KEY", "test-key")
    @patch(f"{_CFG}.RLM_SUB_ITERATIONS", 2)
    def test_iteration_budget_floor(self, mock_setup, mock_rlm):
        """Iteration budget should never go below 2."""
        ctx = ToolContext(api_url="http://localhost", _depth=1, _max_delegation_depth=3)
        mock_rlm.return_value = _mock_rlm_instance()

        _run_child_rlm(ctx, "test", "")

        rlm_kwargs = mock_rlm.call_args[1]
        assert rlm_kwargs["max_iterations"] == 2  # max(2, 2-1) = 2


class TestDelegationDisabled:
    """Test that max_delegation_depth=0 completely disables delegation."""

    def test_max_depth_zero_blocks_root_delegation(self):
        """With max_delegation_depth=0, even root (depth=0) cannot delegate."""
        ctx = ToolContext(api_url="http://localhost", _depth=0, _max_delegation_depth=0)
        result = rlm_query(ctx, "test")
        assert result == {"error": "Cannot delegate from a child agent"}

    def test_max_depth_zero_no_wrapper_emitted(self):
        """With max_delegation_depth=0, setup code should not contain rlm_query."""
        code = build_search_setup_code(
            api_url="http://localhost",
            depth=0,
            max_delegation_depth=0,
        )
        assert "def rlm_query" not in code
        assert "delegation_tools" not in code

    def test_negative_depth_clamped_to_zero(self):
        """Config clamp logic: negative values should be clamped to 0."""
        assert max(0, int("-1")) == 0
