"""Test that the RLM circuit breaker injects a nudge after 2 empty iterations."""

from unittest.mock import MagicMock, patch

from rlm.core.rlm import RLM
from rlm.core.types import RLMIteration


class TestEmptyIterationBreaker:
    """Circuit breaker: 2 consecutive empty iterations -> nudge message."""

    def test_nudge_injected_after_two_empty_iterations(self):
        """After 2 iterations with no code blocks, a nudge message should be
        appended to message_history before the 3rd iteration."""
        call_count = 0
        captured_prompts = []

        def mock_completion_turn(prompt, lm_handler, environment, iteration_num):
            nonlocal call_count
            call_count += 1
            captured_prompts.append([m.get("content", "") for m in prompt if isinstance(m, dict)])
            # Return empty iteration (no code blocks) for first 3, then FINAL on 4th
            iter_obj = RLMIteration(
                prompt=prompt,
                response="thinking..." if call_count <= 3 else "FINAL(done)",
                code_blocks=[],
                iteration_time=0.1,
            )
            return iter_obj

        rlm = RLM(
            backend="openai",
            backend_kwargs={"model_name": "test"},
            max_iterations=10,
            max_depth=0,  # triggers fallback, so override below
        )
        rlm.max_depth = 1  # allow the REPL loop to run

        with patch.object(rlm, "_completion_turn", side_effect=mock_completion_turn):
            with patch.object(rlm, "_spawn_completion_context") as mock_ctx:
                mock_lm = MagicMock()
                mock_env = MagicMock()
                mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_lm, mock_env))
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

                result = rlm.completion("test question")

        # After 2 empty iterations, the 3rd prompt should contain the nudge
        assert call_count >= 3
        # Check that a nudge was injected somewhere in the prompts for iteration 3+
        all_content = " ".join(
            c for prompt_list in captured_prompts[2:] for c in prompt_list
        )
        assert "You have not executed any code" in all_content

    def test_code_block_resets_consecutive_empty_count(self):
        """A non-empty iteration resets the empty counter — no nudge after
        empty, code, empty, code pattern."""
        call_count = 0
        captured_prompts = []

        def mock_completion_turn(prompt, lm_handler, environment, iteration_num):
            nonlocal call_count
            call_count += 1
            captured_prompts.append([m.get("content", "") for m in prompt if isinstance(m, dict)])
            from rlm.core.types import CodeBlock, REPLResult

            if call_count % 2 == 0:
                # Even iterations have code blocks
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
                mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_lm, mock_env))
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

                result = rlm.completion("test question")

        # No nudge should have been injected — alternating empty/non-empty
        all_content = " ".join(
            c for prompt_list in captured_prompts for c in prompt_list
        )
        assert "You have not executed any code" not in all_content

    def test_nudge_resets_counter_allowing_further_nudges(self):
        """After a nudge is injected, the counter resets. If 2 more empty
        iterations follow, another nudge should appear."""
        call_count = 0
        captured_prompts = []

        def mock_completion_turn(prompt, lm_handler, environment, iteration_num):
            nonlocal call_count
            call_count += 1
            captured_prompts.append([m.get("content", "") for m in prompt if isinstance(m, dict)])
            # 5 empty iterations, then final
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
                mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_lm, mock_env))
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

                result = rlm.completion("test question")

        # Nudge should appear in prompts for iteration 3 and iteration 5
        # (after 2 empty: nudge+reset, then 2 more empty: nudge+reset)
        nudge_count = sum(
            1 for prompt_list in captured_prompts
            for c in prompt_list
            if "You have not executed any code" in c
        )
        assert nudge_count >= 2
