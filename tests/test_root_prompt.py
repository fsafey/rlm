"""Tests for root_prompt drift prevention and _completion_turn behavior."""

from rlm.utils.prompts import USER_PROMPT, build_user_prompt


class TestBuildUserPromptWithoutRootPrompt:
    """Verify default behavior when root_prompt is None."""

    def test_iteration_0_uses_generic_prompt(self):
        result = build_user_prompt(root_prompt=None, iteration=0)
        assert result["role"] == "user"
        assert USER_PROMPT in result["content"]
        assert "original prompt" not in result["content"]

    def test_iteration_n_uses_generic_prompt(self):
        result = build_user_prompt(root_prompt=None, iteration=3)
        assert "The history before" in result["content"]
        assert USER_PROMPT in result["content"]
        assert "original prompt" not in result["content"]


class TestBuildUserPromptWithRootPrompt:
    """Verify root_prompt is injected into every iteration."""

    def test_iteration_0_embeds_root_prompt(self):
        result = build_user_prompt(root_prompt="What is the ruling on music?", iteration=0)
        assert "What is the ruling on music?" in result["content"]
        assert "original prompt" in result["content"]

    def test_iteration_0_includes_safeguard(self):
        result = build_user_prompt(root_prompt="test question", iteration=0)
        assert "You have not interacted" in result["content"]

    def test_iteration_n_embeds_root_prompt(self):
        """root_prompt must appear on every subsequent iteration, not just the first."""
        for i in range(1, 6):
            result = build_user_prompt(root_prompt="What is the optimal temperature?", iteration=i)
            assert "What is the optimal temperature?" in result["content"]
            assert "original prompt" in result["content"]

    def test_iteration_n_includes_history_prefix(self):
        result = build_user_prompt(root_prompt="test question", iteration=2)
        assert "The history before" in result["content"]

    def test_root_prompt_with_special_characters(self):
        """Ensure quotes and special chars in root_prompt don't break formatting."""
        result = build_user_prompt(root_prompt='Is "mut\'ah" marriage valid?', iteration=1)
        assert "mut'ah" in result["content"]

    def test_root_prompt_empty_string_treated_as_falsy(self):
        """Empty string root_prompt should fall back to generic prompt."""
        result = build_user_prompt(root_prompt="", iteration=0)
        assert "original prompt" not in result["content"]
        assert USER_PROMPT in result["content"]


class TestBuildUserPromptContextAndHistory:
    """Verify root_prompt composes cleanly with context_count and history_count."""

    def test_root_prompt_with_multiple_contexts(self):
        result = build_user_prompt(root_prompt="Find the answer", iteration=1, context_count=3)
        assert "Find the answer" in result["content"]
        assert "3 contexts available" in result["content"]

    def test_root_prompt_with_history(self):
        result = build_user_prompt(root_prompt="Find the answer", iteration=1, history_count=2)
        assert "Find the answer" in result["content"]
        assert "2 prior conversation histories" in result["content"]

    def test_root_prompt_with_single_history(self):
        result = build_user_prompt(root_prompt="Find the answer", iteration=1, history_count=1)
        assert "Find the answer" in result["content"]
        assert "1 prior conversation history" in result["content"]


class TestDefaultAnswerRootPrompt:
    """Verify _default_answer incorporates root_prompt when provided."""

    def test_default_answer_without_root_prompt(self):
        """Without root_prompt, the fallback uses the generic nudge."""
        from unittest.mock import MagicMock

        from rlm.core.rlm import RLM

        mock_handler = MagicMock()
        mock_handler.completion.return_value = "fallback answer"

        rlm_instance = RLM.__new__(RLM)
        rlm_instance.logger = None
        result = rlm_instance._default_answer([], mock_handler, root_prompt=None)

        prompt_sent = mock_handler.completion.call_args[0][0]
        assert prompt_sent[-1]["content"] == (
            "Please provide a final answer to the user's question "
            "based on the information provided."
        )
        assert result == "fallback answer"

    def test_default_answer_with_root_prompt(self):
        """With root_prompt, the fallback re-anchors to the original question."""
        from unittest.mock import MagicMock

        from rlm.core.rlm import RLM

        mock_handler = MagicMock()
        mock_handler.completion.return_value = "anchored answer"

        rlm_instance = RLM.__new__(RLM)
        rlm_instance.logger = None
        result = rlm_instance._default_answer(
            [], mock_handler, root_prompt="What is the ruling on music?"
        )

        prompt_sent = mock_handler.completion.call_args[0][0]
        assert "What is the ruling on music?" in prompt_sent[-1]["content"]
        assert "original question" in prompt_sent[-1]["content"]
        assert result == "anchored answer"


class TestCompletionTurnCascadeSkip:
    """Verify _completion_turn skips remaining blocks after consecutive runtime errors."""

    def _make_rlm(self):
        from rlm.core.rlm import RLM

        rlm_instance = RLM.__new__(RLM)
        rlm_instance.logger = None
        return rlm_instance

    def test_cascade_skip_after_two_consecutive_errors(self):
        """Two consecutive runtime errors → remaining blocks skipped."""
        from unittest.mock import MagicMock

        from rlm.core.types import REPLResult

        rlm = self._make_rlm()
        mock_handler = MagicMock()
        # 5 code blocks: ok, error, error, should-skip, should-skip
        mock_handler.completion.return_value = (
            "```repl\nprint('ok')\n```\n"
            "```repl\nresults_main\n```\n"
            "```repl\nresults_main\n```\n"
            "```repl\nresults_main\n```\n"
            "```repl\nresults_main\n```\n"
        )
        call_count = 0

        def mock_execute(code):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return REPLResult(stdout="ok", stderr="", locals={}, execution_time=0.01)
            return REPLResult(
                stdout="",
                stderr="NameError: name 'results_main' is not defined",
                locals={},
                execution_time=0.01,
            )

        mock_env = MagicMock()
        mock_env.execute_code.side_effect = mock_execute

        iteration = rlm._completion_turn("test", mock_handler, mock_env)
        assert len(iteration.code_blocks) == 5
        # Blocks 0, 1, 2 executed; blocks 3, 4 skipped
        assert call_count == 3
        assert iteration.code_blocks[0].result.stdout == "ok"
        assert "NameError" in iteration.code_blocks[1].result.stderr
        assert "NameError" in iteration.code_blocks[2].result.stderr
        assert "[Skipped:" in iteration.code_blocks[3].result.stderr
        assert "cascading" in iteration.code_blocks[3].result.stderr
        assert "[Skipped:" in iteration.code_blocks[4].result.stderr

    def test_success_resets_consecutive_error_count(self):
        """A successful block between errors resets the counter."""
        from unittest.mock import MagicMock

        from rlm.core.types import REPLResult

        rlm = self._make_rlm()
        mock_handler = MagicMock()
        # 4 blocks: error, ok, error, should-NOT-skip
        mock_handler.completion.return_value = (
            "```repl\nbad1\n```\n```repl\ngood\n```\n```repl\nbad2\n```\n```repl\nbad3\n```\n"
        )
        results = [
            REPLResult(stdout="", stderr="NameError: bad1", locals={}, execution_time=0.01),
            REPLResult(stdout="ok", stderr="", locals={}, execution_time=0.01),
            REPLResult(stdout="", stderr="NameError: bad2", locals={}, execution_time=0.01),
            REPLResult(stdout="", stderr="NameError: bad3", locals={}, execution_time=0.01),
        ]
        mock_env = MagicMock()
        mock_env.execute_code.side_effect = results

        iteration = rlm._completion_turn("test", mock_handler, mock_env)
        # All 4 blocks should execute (success resets counter, then 2 errors triggers skip
        # only at block 4... but we only have 4 blocks, so block 3 is the 2nd error → skip block 4)
        assert len(iteration.code_blocks) == 4
        # Blocks 0-3 executed: err, ok, err, err (3 is 2nd consecutive → triggers skip)
        # But since block 3 is the last... it still executes.
        # Actually: block 2 = 1st error after reset, block 3 = 2nd → triggers skip for block 4+
        # But there's no block 4, so all 4 execute.
        assert mock_env.execute_code.call_count == 4
        assert iteration.code_blocks[0].result.stderr == "NameError: bad1"
        assert iteration.code_blocks[1].result.stdout == "ok"
        assert iteration.code_blocks[2].result.stderr == "NameError: bad2"
        assert iteration.code_blocks[3].result.stderr == "NameError: bad3"

    def test_syntax_error_still_skips_immediately(self):
        """SyntaxError skips all remaining blocks (pre-existing behavior)."""
        from unittest.mock import MagicMock

        from rlm.core.types import REPLResult

        rlm = self._make_rlm()
        mock_handler = MagicMock()
        mock_handler.completion.return_value = (
            "```repl\ndef foo(\n```\n```repl\nprint('never')\n```\n"
        )
        mock_env = MagicMock()
        mock_env.execute_code.return_value = REPLResult(
            stdout="",
            stderr="SyntaxError: unexpected EOF",
            locals={},
            execution_time=0.01,
        )

        iteration = rlm._completion_turn("test", mock_handler, mock_env)
        assert mock_env.execute_code.call_count == 1
        assert "SyntaxError" in iteration.code_blocks[1].result.stderr
        assert "[Skipped:" in iteration.code_blocks[1].result.stderr
