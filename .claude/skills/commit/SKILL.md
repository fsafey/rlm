---
name: commit
description: >
  Intelligent git commit with AI-generated conventional messages.
  Routes to dedicated haiku commit agent for token efficiency.
  Use when user types /commit.
---

# Commit

Spawn the `commit` agent to handle the entire workflow in a fresh haiku context.

Use the Task tool:

- **subagent_type**: `"commit"`
- **prompt**: `"Run the commit workflow for the current changes."`
- If the user specified instructions (e.g., "only frontend files", "dry-run"), include them in the prompt.

The agent handles extraction, message generation, execution, and verification autonomously.

If the agent reports untracked files that should be committed, stage them with `git add <file>` and re-run `/commit`.
