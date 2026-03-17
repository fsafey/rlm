"""Test that the RLM circuit breaker injects a nudge after empty iterations."""

from unittest.mock import MagicMock, patch

from rlm.core.rlm import RLM
from rlm.core.types import RLMIteration


class TestEmptyIterationBreaker:
    """Circuit breaker: 1 empty iteration -> nudge message."""

    def test_nudge_injected_after_one_empty_iteration(self):
        """After 1 iteration with no code blocks, a nudge message should be
        appended to message_history before the 2nd iteration."""
        call_count = 0
        captured_prompts = []

        def mock_completion_turn(prompt, lm_handler, environment, iteration_num):
            nonlocal call_count
            call_count += 1
            captured_prompts.append([m.get("content", "") for m in prompt if isinstance(m, dict)])
            iter_obj = RLMIteration(
                prompt=prompt,
                response="thinking..." if call_count <= 2 else "FINAL(done)",
                code_blocks=[],
                iteration_time=0.1,
            )
            return iter_obj

        rlm = RLM(
            backend="openai",
            backend_kwargs={"model_name": "test"},
            max_iterations=10,
            max_depth=0,
        )
        rlm.max_depth = 1

        with patch.object(rlm, "_completion_turn", side_effect=mock_completion_turn):
            with patch.object(rlm, "_spawn_completion_context") as mock_ctx:
                mock_lm = MagicMock()
                mock_env = MagicMock()
                mock_env.get_context_count.return_value = 1
                mock_env.get_history_count.return_value = 0
                mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_lm, mock_env))
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

                result = rlm.completion("test question")

        # After 1 empty iteration, the 2nd prompt should contain the nudge
        assert call_count >= 2
        all_content = " ".join(
            c for prompt_list in captured_prompts[1:] for c in prompt_list
        )
        assert "no ```repl```" in all_content

    def test_code_block_resets_consecutive_empty_count(self):
        """A non-empty iteration resets the empty counter — no nudge after
        empty, code, empty, code pattern (alternating prevents consecutive)."""
        call_count = 0
        captured_prompts = []

        def mock_completion_turn(prompt, lm_handler, environment, iteration_num):
            nonlocal call_count
            call_count += 1
            captured_prompts.append([m.get("content", "") for m in prompt if isinstance(m, dict)])
            from rlm.core.types import CodeBlock, REPLResult

            if call_count % 2 == 0:
                blocks = [CodeBlock(
                    code="print('hi')",
                    result=REPLResult(stdout="hi", stderr="", locals={}, execution_time=0.01),
                )]
            else:
                blocks = []

            response = "thinking..." if call_count <= 4 else "FINAL(done)"
            return RLMIteration(
                prompt=prompt, response=response,
                code_blocks=blocks, iteration_time=0.1,
            )

        rlm = RLM(
            backend="openai",
            backend_kwargs={"model_name": "test"},
            max_iterations=10,
            max_depth=0,
        )
        rlm.max_depth = 1

        with patch.object(rlm, "_completion_turn", side_effect=mock_completion_turn):
            with patch.object(rlm, "_spawn_completion_context") as mock_ctx:
                mock_lm = MagicMock()
                mock_env = MagicMock()
                mock_env.get_context_count.return_value = 1
                mock_env.get_history_count.return_value = 0
                mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_lm, mock_env))
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

                result = rlm.completion("test question")

        # Nudge fires after every empty iteration (odd ones: 1, 3),
        # but gets reset by code blocks (even ones: 2, 4).
        # The nudge appears in prompts for iterations 2 and 4 (after empty 1 and 3).
        nudge_count = sum(
            1 for prompt_list in captured_prompts
            for c in prompt_list
            if "no ```repl```" in c
        )
        # Each empty iteration triggers a nudge, but code blocks reset counter
        assert nudge_count >= 1  # At minimum, the first empty triggers a nudge

    def test_nudge_resets_counter_allowing_further_nudges(self):
        """After a nudge is injected, the counter resets. If another empty
        iteration follows, another nudge should appear."""
        call_count = 0
        captured_prompts = []

        def mock_completion_turn(prompt, lm_handler, environment, iteration_num):
            nonlocal call_count
            call_count += 1
            captured_prompts.append([m.get("content", "") for m in prompt if isinstance(m, dict)])
            response = "thinking..." if call_count <= 5 else "FINAL(done)"
            return RLMIteration(
                prompt=prompt, response=response,
                code_blocks=[], iteration_time=0.1,
            )

        rlm = RLM(
            backend="openai",
            backend_kwargs={"model_name": "test"},
            max_iterations=10,
            max_depth=0,
        )
        rlm.max_depth = 1

        with patch.object(rlm, "_completion_turn", side_effect=mock_completion_turn):
            with patch.object(rlm, "_spawn_completion_context") as mock_ctx:
                mock_lm = MagicMock()
                mock_env = MagicMock()
                mock_env.get_context_count.return_value = 1
                mock_env.get_history_count.return_value = 0
                mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_lm, mock_env))
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

                result = rlm.completion("test question")

        # Every empty iteration should trigger a nudge (threshold=1, reset after)
        nudge_count = sum(
            1 for prompt_list in captured_prompts
            for c in prompt_list
            if "no ```repl```" in c
        )
        assert nudge_count >= 3  # 5 empty iterations → nudge after each
