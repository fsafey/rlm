#!/bin/bash
# PreToolUse hook: intercepts Bash git commit commands
# - Shows staged files for visibility
# - Warns (does NOT block) if on main/master branch

set -eo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || dirname "$0"/../..)}"

INPUT=$(cat /dev/stdin)

# Only intercept Bash tool calls
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

# Extract the command being run
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only intercept git commit commands (not git diff, git log, etc.)
if ! echo "$COMMAND" | grep -qE '\bgit\s+commit\b'; then
  exit 0
fi

CONTEXT=""

# Get current branch
BRANCH=$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null || echo "unknown")

# Warn if on main or master
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  CONTEXT+="WARNING: You are committing directly to '$BRANCH'. Consider using a feature branch.\n\n"
fi

# Show staged files
STAGED=$(git -C "$PROJECT_DIR" diff --cached --name-only 2>/dev/null || echo "")

if [[ -z "$STAGED" ]]; then
  CONTEXT+="No files currently staged. The commit may fail or stage files via -a flag."
else
  FILE_COUNT=$(echo "$STAGED" | wc -l | tr -d ' ')
  CONTEXT+="Staged files ($FILE_COUNT):\n$STAGED"
fi

# Output context — never block, just inform
# Use jq for reliable JSON encoding (handles newlines, quotes, special chars)
jq -n --arg ctx "$(echo -e "$CONTEXT")" '{"continue": true, "additionalContext": $ctx}'
