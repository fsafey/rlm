"""
RLM Real Demo — Uses `claude -p` (Claude Code CLI). No API key required.

Demonstrates the RLM processing a large context that exceeds what you'd
normally want to stuff into a single LLM call. The root model autonomously
writes REPL code to chunk, query sub-LLMs, and synthesize an answer.
"""

import json

from rlm import RLM
from rlm.logger import RLMLogger

# ── Build a large synthetic context ────────────────────────────────
# Simulates a scenario where input far exceeds what you'd want in one call
documents = []
for i in range(50):
    doc = {
        "id": i,
        "title": f"Research Note #{i}",
        "content": f"This is research note {i}. " + ("Background information. " * 200),
    }
    # Hide the answer in document 37
    if i == 37:
        doc["content"] = (
            f"This is research note {i}. "
            + ("Background information. " * 100)
            + "IMPORTANT FINDING: The optimal temperature for the catalyst reaction is 347 degrees in her 2024 paper. "
            + ("Additional details follow. " * 100)
        )
    documents.append(doc)

context = json.dumps(documents, indent=2)
print(f"Context size: {len(context):,} characters ({len(documents)} documents)")
print(f"That's roughly {len(context) // 4:,} tokens\n")

# ── Set up logging ─────────────────────────────────────────────────
logger = RLMLogger(log_dir="./rlm_logs")

# ── Create and run the RLM ─────────────────────────────────────────
question = "What is the optimal temperature for the catalyst reaction, and which document contains this finding?"

rlm = RLM(
    backend="claude_cli",
    backend_kwargs={"model_name": "claude-cli"},
    environment="local",
    max_depth=1,
    max_iterations=15,
    logger=logger,
    verbose=True,
)

print(f"Question: {question}")
print("Sending to RLM (backend: claude_cli)...\n")
print("=" * 70)

result = rlm.completion(context, root_prompt=question)

print("=" * 70)
print(f"\nFINAL ANSWER: {result.response}")
print(f"Execution time: {result.execution_time:.2f}s")
print(f"Usage: {result.usage_summary.to_dict()}")
print("\nLogs saved to: ./rlm_logs/")
