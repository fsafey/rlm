"""Comprehensive tests for LocalREPL environment."""

import os

import pytest

from rlm.environments.base_env import SetupCodeError
from rlm.environments.local_repl import LocalREPL


class TestLocalREPLBasic:
    """Basic functionality tests for LocalREPL."""

    def test_simple_execution(self):
        """Test basic code execution."""
        repl = LocalREPL()
        result = repl.execute_code("x = 1 + 2")
        assert result.stderr == ""
        assert repl.locals["x"] == 3
        repl.cleanup()

    def test_print_output(self):
        """Test that print statements are captured."""
        repl = LocalREPL()
        result = repl.execute_code("print('Hello, World!')")
        assert "Hello, World!" in result.stdout
        repl.cleanup()

    def test_error_handling(self):
        """Test that errors are captured in stderr."""
        repl = LocalREPL()
        result = repl.execute_code("1 / 0")
        assert "ZeroDivisionError" in result.stderr
        repl.cleanup()

    def test_syntax_error(self):
        """Test syntax error handling."""
        repl = LocalREPL()
        result = repl.execute_code("def broken(")
        assert "SyntaxError" in result.stderr
        repl.cleanup()


class TestLocalREPLPersistence:
    """Tests for state persistence across executions."""

    def test_variable_persistence(self):
        """Test that variables persist across multiple code executions."""
        repl = LocalREPL()

        result1 = repl.execute_code("x = 42")
        assert result1.stderr == ""
        assert repl.locals["x"] == 42

        result2 = repl.execute_code("y = x + 8")
        assert result2.stderr == ""
        assert repl.locals["y"] == 50

        result3 = repl.execute_code("print(y)")
        assert "50" in result3.stdout

        repl.cleanup()

    def test_function_persistence(self):
        """Test that defined functions persist."""
        repl = LocalREPL()

        repl.execute_code(
            """
def greet(name):
    return f"Hello, {name}!"
"""
        )

        result = repl.execute_code("print(greet('World'))")
        assert "Hello, World!" in result.stdout
        repl.cleanup()

    def test_list_comprehension(self):
        """Test that list comprehensions work."""
        repl = LocalREPL()

        repl.execute_code("squares = [x**2 for x in range(5)]")
        assert repl.locals["squares"] == [0, 1, 4, 9, 16]

        result = repl.execute_code("print(sum(squares))")
        assert "30" in result.stdout
        repl.cleanup()


class TestLocalREPLBuiltins:
    """Tests for safe builtins and blocked functions."""

    def test_safe_builtins_available(self):
        """Test that safe builtins are available."""
        repl = LocalREPL()

        # Test various safe builtins
        _ = repl.execute_code("x = len([1, 2, 3])")
        assert repl.locals["x"] == 3

        _ = repl.execute_code("y = sum([1, 2, 3, 4])")
        assert repl.locals["y"] == 10

        _ = repl.execute_code("z = sorted([3, 1, 2])")
        assert repl.locals["z"] == [1, 2, 3]

        repl.cleanup()

    def test_imports_work(self):
        """Test that imports work."""
        repl = LocalREPL()
        result = repl.execute_code("import math\nx = math.pi")
        assert result.stderr == ""
        assert abs(repl.locals["x"] - 3.14159) < 0.001
        repl.cleanup()


class TestLocalREPLContextManager:
    """Tests for context manager usage."""

    def test_context_manager(self):
        """Test using LocalREPL as context manager."""
        with LocalREPL() as repl:
            _ = repl.execute_code("x = 100")
            assert repl.locals["x"] == 100


class TestLocalREPLHelpers:
    """Tests for helper functions (FINAL_VAR, etc.)."""

    def test_final_var_existing(self):
        """Test FINAL_VAR with existing variable."""
        repl = LocalREPL()
        repl.execute_code("answer = 42")
        _ = repl.execute_code("result = FINAL_VAR('answer')")
        assert repl.locals["result"] == "42"
        repl.cleanup()

    def test_final_var_missing(self):
        """Test FINAL_VAR with non-existent variable."""
        repl = LocalREPL()
        _ = repl.execute_code("result = FINAL_VAR('nonexistent')")
        assert "Error" in repl.locals["result"]
        repl.cleanup()

    def test_llm_query_no_handler(self):
        """Test llm_query without handler configured."""
        repl = LocalREPL()
        _ = repl.execute_code("response = llm_query('test')")
        assert "Error" in repl.locals["response"]
        repl.cleanup()


class TestLocalREPLContext:
    """Tests for context loading."""

    def test_string_context(self):
        """Test loading string context."""
        repl = LocalREPL(context_payload="This is the context data.")
        assert "context" in repl.locals
        assert repl.locals["context"] == "This is the context data."
        repl.cleanup()

    def test_dict_context(self):
        """Test loading dict context."""
        repl = LocalREPL(context_payload={"key": "value", "number": 42})
        assert "context" in repl.locals
        assert repl.locals["context"]["key"] == "value"
        assert repl.locals["context"]["number"] == 42
        repl.cleanup()

    def test_list_context(self):
        """Test loading list context."""
        repl = LocalREPL(context_payload=[1, 2, 3, "four"])
        assert "context" in repl.locals
        assert repl.locals["context"] == [1, 2, 3, "four"]
        repl.cleanup()


class TestLocalREPLCleanup:
    """Tests for cleanup behavior."""

    def test_cleanup_clears_state(self):
        """Test that cleanup clears the namespace."""
        repl = LocalREPL()
        repl.execute_code("x = 42")
        assert "x" in repl.locals
        repl.cleanup()
        assert len(repl.locals) == 0

    def test_temp_dir_created_and_cleaned(self):
        """Test that temp directory is created and cleaned up."""
        repl = LocalREPL()
        temp_dir = repl.temp_dir
        assert os.path.exists(temp_dir)
        repl.cleanup()
        assert not os.path.exists(temp_dir)


class TestLocalREPLSimulatingRLMNoPersistence:
    """
    Tests simulating RLM's non-persistent completion behavior.

    When RLM is configured without persistent=True (the default), each
    get_completion() call spawns a fresh environment and destroys it after.
    This test suite simulates that behavior to prove variables don't survive
    across RLM completions.

    Why this matters: This is NOT just testing that two Python objects don't
    share state (trivially true). This simulates the actual RLM workflow where
    environments are created and destroyed per completion.
    """

    def test_simulated_rlm_completions_reset_environment(self):
        """
        Simulates 2 RLM completions to show env resets between calls.

        Without persistent=True, RLM creates a fresh environment for each
        completion, so state doesn't carry over.
        """
        completion_1_env = LocalREPL()
        completion_1_env.execute_code("important_result = 42")
        assert completion_1_env.locals["important_result"] == 42
        completion_1_env.cleanup()

        completion_2_env = LocalREPL()
        result = completion_2_env.execute_code("print(important_result)")

        assert "NameError" in result.stderr
        assert "important_result" in result.stderr
        completion_2_env.cleanup()

    def test_simulated_rlm_completions_functions_not_preserved(self):
        """
        Simulates 2 RLM completions to show functions don't persist.
        """
        completion_1_env = LocalREPL()
        completion_1_env.execute_code("def my_helper(): return 'useful'")
        assert completion_1_env.execute_code("print(my_helper())").stdout.strip() == "useful"
        completion_1_env.cleanup()

        completion_2_env = LocalREPL()
        result = completion_2_env.execute_code("my_helper()")

        assert "NameError" in result.stderr
        assert "my_helper" in result.stderr
        completion_2_env.cleanup()


class TestSetupCodeErrorHandling:
    """Tests that setup_code errors surface immediately instead of failing silently."""

    def test_syntax_error_in_setup_code_raises(self):
        """SyntaxError in setup_code must raise SetupCodeError at init time."""
        with pytest.raises(SetupCodeError, match="SyntaxError"):
            LocalREPL(setup_code="def broken(")

    def test_runtime_error_in_setup_code_raises(self):
        """Runtime error in setup_code must raise SetupCodeError at init time."""
        with pytest.raises(SetupCodeError, match="ZeroDivisionError"):
            LocalREPL(setup_code="x = 1 / 0")

    def test_name_error_in_setup_code_raises(self):
        """NameError in setup_code must raise SetupCodeError at init time."""
        with pytest.raises(SetupCodeError, match="NameError"):
            LocalREPL(setup_code="x = undefined_variable")

    def test_setup_code_error_contains_stderr(self):
        """SetupCodeError should carry the stderr content for diagnostics."""
        with pytest.raises(SetupCodeError) as exc_info:
            LocalREPL(setup_code="raise ValueError('bad config')")
        assert "bad config" in exc_info.value.stderr

    def test_valid_setup_code_still_works(self):
        """Valid setup_code should inject tools as before."""
        repl = LocalREPL(setup_code="def greet(name): return f'hi {name}'")
        assert "greet" in repl.locals
        assert repl.locals["greet"]("world") == "hi world"
        repl.cleanup()

    def test_valid_setup_code_with_state(self):
        """Setup code can define mutable state that persists across iterations."""
        repl = LocalREPL(setup_code="log = []\ndef add(x): log.append(x)")
        repl.execute_code("add(1); add(2)")
        assert repl.locals["log"] == [1, 2]
        repl.cleanup()

    def test_partial_setup_code_failure_raises(self):
        """If setup_code defines some tools then errors, it should still raise."""
        code = "def good_fn(): return 1\nraise RuntimeError('halfway')"
        with pytest.raises(SetupCodeError, match="halfway"):
            LocalREPL(setup_code=code)
