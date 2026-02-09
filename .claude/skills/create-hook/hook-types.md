# Hook Types & Configuration

## Environment Detection

Detect project tooling and suggest relevant hooks:

**TypeScript** (`tsconfig.json`):

- PostToolUse: "Type-check files after editing"
- PreToolUse: "Block edits with type errors"

**Prettier** (`.prettierrc`, `prettier.config.js`):

- PostToolUse: "Auto-format files after editing"
- PreToolUse: "Require formatted code"

**ESLint** (`.eslintrc.*`):

- PostToolUse: "Lint and auto-fix after editing"
- PreToolUse: "Block commits with linting errors"

**package.json scripts**:

- `test` script -> "Run tests before commits"
- `build` script -> "Validate build before commits"

**Git repository**:

- PreToolUse/Bash: "Prevent commits with secrets"
- PostToolUse: "Security scan on file changes"

**Decision tree**:

```
TypeScript?  -> type checking hooks
Formatter?   -> formatting hooks
Tests?       -> test validation hooks
Security?    -> security hooks
+ Scan for custom scripts, unique file patterns, project-specific tooling
```

## Configuration Questions

Only ask about details you're unsure of from the user's description:

1. **Trigger timing**: `PreToolUse` (before, can block) | `PostToolUse` (after, feedback) | `UserPromptSubmit` (before processing)
2. **Tool matcher**: `Write`, `Edit`, `Bash`, `*`
3. **Scope**: `global` | `project` | `project-local`
4. **Response approach**: Exit codes (simple pass/fail) | JSON (rich feedback)
   - Exit 0 = success, Exit 2 = block (PreToolUse only)
   - JSON = `{continue, additionalContext, suppressOutput}`
5. **Blocking behavior**: PreToolUse can block; PostToolUse provides feedback only
6. **Claude integration**: `additionalContext` for auto-fix | `suppressOutput` for silent
7. **Context pollution**: Silent success for routine checks, visible for security alerts
8. **File filtering**: Which file types to process

## Hook Types by Use Case

| Use Case     | Timing      | Purpose                    |
| ------------ | ----------- | -------------------------- |
| Code Quality | PostToolUse | Feedback and auto-fixes    |
| Security     | PreToolUse  | Block dangerous operations |
| CI/CD        | PreToolUse  | Validate before commits    |
| Development  | PostToolUse | Automated improvements     |

## Execution Notes

- Hooks run in parallel (order not guaranteed)
- Design for independence
- Plan interactions carefully when multiple hooks affect the same files
