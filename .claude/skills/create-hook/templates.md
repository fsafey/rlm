# Hook Implementation & Templates

## Implementation Standards

- Read JSON from stdin (never use argv)
- Use top-level `additionalContext`/`systemMessage` for Claude communication
- Include `suppressOutput: true` for successful operations
- Provide specific error counts and actionable feedback
- Focus on changed files rather than entire codebase
- Use absolute paths; reference project root via `$CLAUDE_PROJECT_DIR`

### Input/Output Format (where most implementations fail)

- **Input**: Read JSON from stdin correctly (not argv)
- **Output**: Top-level JSON structure for Claude communication
- **Reference**: https://docs.claude.com/en/docs/claude-code/hooks for exact schemas

## Templates

### Type Checking (PostToolUse)

```javascript
#!/usr/bin/env node
// Read stdin JSON, check .ts/.tsx files only
// Run: npx tsc --noEmit --pretty
// Output: JSON with additionalContext for errors
const input = JSON.parse(require("fs").readFileSync("/dev/stdin", "utf8"));
const file = input?.tool_input?.file_path || "";
if (!file.match(/\.(ts|tsx)$/)) process.exit(0);

const { execSync } = require("child_process");
try {
  execSync("npx tsc --noEmit --pretty", { stdio: "pipe" });
  console.log(JSON.stringify({ continue: true, suppressOutput: true }));
} catch (e) {
  console.log(
    JSON.stringify({
      continue: true,
      additionalContext: `TypeScript errors:\n${e.stdout?.toString()}`,
    }),
  );
}
```

### Auto-formatting (PostToolUse)

```javascript
#!/usr/bin/env node
// Read stdin JSON, format supported file types
const input = JSON.parse(require("fs").readFileSync("/dev/stdin", "utf8"));
const file = input?.tool_input?.file_path || "";
if (!file.match(/\.(ts|tsx|js|jsx|json|css|md)$/)) process.exit(0);

const { execSync } = require("child_process");
try {
  execSync(`npx prettier --write "${file}"`, { stdio: "pipe" });
  console.log(JSON.stringify({ continue: true, suppressOutput: true }));
} catch (e) {
  console.log(
    JSON.stringify({
      continue: true,
      additionalContext: `Prettier error: ${e.message}`,
    }),
  );
}
```

### Security Scanning (PreToolUse)

```bash
#!/bin/bash
# Read stdin JSON, check for secrets/keys in file content
INPUT=$(cat /dev/stdin)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // empty')

if echo "$CONTENT" | grep -qiE '(api[_-]?key|secret[_-]?key|password|token)\s*[:=]'; then
  echo '{"continue": false, "additionalContext": "Blocked: potential secret detected in file content"}'
  exit 2
fi
exit 0
```

## Testing Checklist

### Happy Path

1. Create conditions where hook should pass
2. Verify exit 0 / `{continue: true, suppressOutput: true}`
3. Examples: valid TypeScript, formatted code, safe commands

### Sad Path

1. Create conditions where hook should fail/warn
2. Verify exit 2 (PreToolUse block) or `additionalContext` (PostToolUse feedback)
3. Examples: type errors, unformatted code, secret patterns

### Troubleshooting

- Check hook registration in settings.json
- Verify script permissions (`chmod +x`)
- Test with simplified version first
- Verify stdin JSON parsing works: `echo '{"test":true}' | ./hook-script.sh`
