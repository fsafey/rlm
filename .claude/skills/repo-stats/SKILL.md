---
name: repo-stats
description: >
  Analyze git repository statistics: commit type distribution, layer activity,
  hotspot files, velocity, and tag inventory. Use when user types /repo-stats,
  asks about codebase activity, commit patterns, or "what's been changing".
context: fork
allowed-tools: Bash, Read
---

# Repo Stats

Analyze git history for commit patterns, layer activity, and codebase health.

## Step 1: Parse Arguments

Read `$ARGUMENTS` to determine scope:

| Input         | Flag              | Example                             |
| ------------- | ----------------- | ----------------------------------- |
| (empty)       | `-n 50`           | Last 50 commits (default)           |
| `last N`      | `-n N`            | `last 100` -> `-n 100`              |
| `since TAG`   | `--since-tag TAG` | `since v0.21.0`                     |
| `last N days` | `--since-days N`  | `last 30 days` -> `--since-days 30` |

## Step 2: Run Analysis

```bash
uv run python .claude/skills/repo-stats/scripts/analyze.py [FLAGS]
```

**Examples:**

```bash
# Default: last 50 commits
uv run python .claude/skills/repo-stats/scripts/analyze.py

# Last 100 commits
uv run python .claude/skills/repo-stats/scripts/analyze.py -n 100

# Since a tag
uv run python .claude/skills/repo-stats/scripts/analyze.py --since-tag v0.21.0

# Last 30 days
uv run python .claude/skills/repo-stats/scripts/analyze.py --since-days 30
```

## Step 3: Return Report

The script outputs a formatted report directly. Return it as-is to the user. Do not summarize or restructure — the report is designed for direct consumption.

If the report is empty or shows 0 commits, note the range and suggest broadening (e.g., increase `-n` or use `--since-days`).
