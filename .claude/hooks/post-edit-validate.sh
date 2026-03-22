#!/bin/bash
# PostToolUse hook: runs ruff check on Python files after Edit/Write
# Reports lint errors as context — never blocks

set -eo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

INPUT=$(cat /dev/stdin)

# Only intercept Edit and Write tool calls
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

# Extract the file path
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Only check Python files
if [[ "$FILE_PATH" != *.py ]]; then
  exit 0
fi

# Skip if file doesn't exist (Write might have failed)
if [[ ! -f "$FILE_PATH" ]]; then
  exit 0
fi

# Run ruff check — use exit code to detect errors
cd "$PROJECT_DIR" 2>/dev/null || exit 0
RUFF_OUTPUT=$(uv run ruff check "$FILE_PATH" 2>&1) && exit 0

# ruff failed (has lint errors) — report them
CONTEXT="Ruff lint errors in $(basename "$FILE_PATH"):\n$RUFF_OUTPUT\n\nFix these before continuing."
jq -n --arg ctx "$(echo -e "$CONTEXT")" '{"additionalContext": $ctx}'
