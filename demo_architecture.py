"""
RLM Architecture Demo — No API key required.

Demonstrates the full RLM execution flow using a mock LM:
1. Context is stored in the REPL as a variable (not stuffed into the LLM prompt)
2. The root model writes code that runs in the sandboxed REPL
3. The REPL can call sub-LLMs via llm_query()
4. The model terminates with FINAL() or FINAL_VAR()

This is the core thesis of the paper: treat context as an environment,
not as input to a fixed-size neural network forward pass.
"""

from unittest.mock import Mock, patch

import rlm.core.rlm as rlm_module
from rlm import RLM
from rlm.core.lm_handler import LMHandler
from rlm.core.types import ModelUsageSummary, UsageSummary
from rlm.environments.local_repl import LocalREPL
from tests.mock_lm import MockLM

# ═══════════════════════════════════════════════════════════════════════
# DEMO 1: The REPL Environment — Context Lives Outside the Model
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("DEMO 1: The REPL Environment — Context Lives Outside the Model")
print("=" * 70)

# The key insight: context is a variable in the REPL, not prompt tokens
big_context = "A " * 50000 + "The secret answer is 42." + " B" * 50000
print(f"\nContext size: {len(big_context):,} characters")
print("(This would be ~25K tokens — but the root model never sees it directly)\n")

# Create a REPL with a mock LM handler so llm_query() works
mock_client = MockLM()
with LMHandler(client=mock_client) as handler:
    with LocalREPL(
        lm_handler_address=handler.address,
        context_payload=big_context,
    ) as repl:
        # Step 1: The model can inspect context metadata without loading it all
        result = repl.execute_code("print(f'Context length: {len(context)} chars')")
        print(f"[REPL] {result.stdout.strip()}")

        # Step 2: The model writes code to search strategically
        result = repl.execute_code("""
# Smart search — don't read everything, target what matters
import re
match = re.search(r'secret answer is (\\d+)', context)
if match:
    found = match.group(0)
    print(f"Found: {found}")
else:
    print("Not found in this chunk")
""")
        print(f"[REPL] {result.stdout.strip()}")

        # Step 3: The model can call sub-LLMs from within the REPL
        result = repl.execute_code("""
# llm_query() calls a sub-LLM via socket -> LMHandler -> LLM API
# With mock LM, this returns an echo; with real LM, it's a full completion
chunk = context[49990:50050]
response = llm_query(f"What is the answer? Context: {chunk}")
print(f"Sub-LLM response: {response}")
""")
        print(f"[REPL] {result.stdout.strip()}")

        # Step 4: Variables persist across code executions
        result = repl.execute_code("""
final_answer = "The secret answer is 42, found via targeted search"
print(f"Stored final_answer: {final_answer}")
""")
        print(f"[REPL] {result.stdout.strip()}")

        # Step 5: FINAL_VAR retrieves the variable
        val = repl.globals["FINAL_VAR"]("final_answer")
        print(f"\n[FINAL_VAR] -> {val}")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 2: Full RLM Loop with Mock LM (Simulated Multi-Step Reasoning)
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("DEMO 2: Full RLM Loop with Mock LM (Simulated Multi-Step Reasoning)")
print("=" * 70)

# These simulate what the root model would generate at each iteration:
responses = [
    # Iteration 1: Root model inspects the context
    'Let me analyze the context.\n```repl\nprint(f"Context type: {type(context).__name__}, length: {len(context)}")\nchunks = [context[i:i+1000] for i in range(0, len(context), 1000)]\nprint(f"Split into {len(chunks)} chunks of ~1000 chars")\n```',
    # Iteration 2: Root model searches via sub-LLM
    '```repl\n# Search each chunk for the answer\nfor i, chunk in enumerate(chunks[:5]):\n    if "secret" in chunk:\n        answer_chunk = chunk\n        print(f"Found relevant content in chunk {i}")\n        break\n```',
    # Iteration 3: Root model produces final answer
    'Based on the search, I found the answer.\n```repl\nmy_answer = f"Found in the context: the secret answer is 42"\nprint(my_answer)\n```\nFINAL_VAR(my_answer)',
]


def create_mock(resps):
    mock = Mock()
    mock.completion.side_effect = list(resps)
    mock.model_name = "mock-model"
    mock.get_usage_summary.return_value = UsageSummary(
        model_usage_summaries={
            "mock-model": ModelUsageSummary(
                total_calls=len(resps),
                total_input_tokens=500,
                total_output_tokens=300,
            )
        }
    )
    mock.get_last_usage.return_value = mock.get_usage_summary.return_value
    return mock


with patch.object(rlm_module, "get_client") as mock_get_client:
    mock_lm = create_mock(responses)
    mock_get_client.return_value = mock_lm

    rlm = RLM(
        backend="openai",
        backend_kwargs={"model_name": "mock-model"},
        environment="local",
        max_depth=1,
        max_iterations=10,
        verbose=True,
    )

    result = rlm.completion(big_context, root_prompt="What is the secret answer?")
    print(f"\n{'=' * 70}")
    print(f"FINAL RESULT: {result.response}")
    print(f"Execution time: {result.execution_time:.3f}s")
    print(f"{'=' * 70}")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 3: Multi-Turn Persistent Sessions
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("DEMO 3: Multi-Turn Persistent Sessions")
print("=" * 70)
print("(Variables and contexts accumulate across completion calls)\n")

turn1 = [
    "```repl\nsummary_1 = f'Doc 1 has {len(context)} chars about topic A'\nprint(summary_1)\n```",
    "FINAL(Processed doc 1)",
]
turn2 = [
    "```repl\nsummary_2 = f'Doc 2 has {len(context_1)} chars about topic B'\ncombined = f'{summary_1} | {summary_2}'\nprint(combined)\n```",
    "FINAL(Compared both docs)",
]

with patch.object(rlm_module, "get_client") as mock_get_client:
    mock_lm = create_mock(turn1)
    mock_get_client.return_value = mock_lm

    with RLM(
        backend="openai",
        backend_kwargs={"model_name": "mock-model"},
        persistent=True,
    ) as rlm:
        r1 = rlm.completion("First document content about cats")
        print(f"Turn 1 result: {r1.response}")
        print(f"  Contexts loaded: {rlm._persistent_env.get_context_count()}")

        # Reset mock for turn 2
        mock_lm.completion.side_effect = list(turn2)
        r2 = rlm.completion("Second document content about dogs")
        print(f"Turn 2 result: {r2.response}")
        print(f"  Contexts loaded: {rlm._persistent_env.get_context_count()}")
        print(f"  Histories stored: {rlm._persistent_env.get_history_count()}")
        print(
            f"  Variables alive: {[k for k in rlm._persistent_env.locals if not k.startswith('_')]}"
        )

print("\nAll demos completed successfully.")
