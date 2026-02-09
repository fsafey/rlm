---
name: create-hook
description: Create Claude Code hooks with environment detection and testing. Use when user mentions "hook", "create hook", "pre-commit", "post-edit", "auto-format", or "automated checks".
context: fork
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# Create Hook

Analyze the project, suggest practical hooks, and create them with proper testing.

## Workflow

### 1. Analyze Environment

Detect tooling (`tsconfig.json`, `.prettierrc`, `.eslintrc.*`, `package.json` scripts, `.git/`) and suggest relevant hooks. See [hook-types.md](hook-types.md) for the detection decision tree and configuration questions.

### 2. Configure

Ask: **"What should this hook do?"** with suggestions from analysis. Only ask about details you're unsure of (trigger timing, scope, blocking behavior). See [hook-types.md](hook-types.md) for the 8 configuration questions.

### 3. Create

- Create hooks directory (`~/.claude/hooks/` or `.claude/hooks/` based on scope)
- Generate script with proper shebang, executable permissions
- Update settings.json with hook configuration
- Use `$CLAUDE_PROJECT_DIR` for project-relative paths

See [templates.md](templates.md) for implementation standards, I/O format, and code templates.

### 4. Test & Validate

Test both happy path (hook should pass) and sad path (hook should fail/warn). See [templates.md](templates.md) for testing checklist and troubleshooting.

## Success Criteria

- Script has executable permissions
- Registered in correct settings.json
- Responds correctly to both pass and fail scenarios
- Integrates with Claude via `additionalContext` (errors) or `suppressOutput` (silent success)

## Quick Reference

- **Official docs**: https://docs.claude.com/en/docs/claude-code/hooks
- **stdin input**: `JSON.parse(process.stdin.read())`
- **Success**: `{continue: true, suppressOutput: true}`
- **Error**: `{continue: true, additionalContext: "error details"}`
- **Block**: `exit(2)` in PreToolUse hooks
