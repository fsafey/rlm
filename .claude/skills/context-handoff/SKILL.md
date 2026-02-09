---
name: context-handoff
description: Create compressed handoff documents for seamless session transitions. Use PROACTIVELY when session approaches context limits, user requests "fresh context"/"new session"/"handoff", or switching major tasks.
context: fork
allowed-tools: Read, Grep, Glob, Write, Bash
---

# Context Handoff

Distill the current session's essential state into the smallest possible high-signal token set for a fresh session. If `$ARGUMENTS` specifies a focus area, prioritize that context.

## Workflow

### 1. Gather State

```bash
git status
git log -5 --oneline
git diff --stat
```

### 2. Extract

Identify active tasks, key decisions, blockers, and essential file locations from conversation context.

### 3. Compress

- **Keep**: Active tasks with next steps, blockers, key decisions + rationale, essential file paths, specific commands to run
- **Drop**: Completed work details, debugging output, tool results, historical discussion, dead-ends
- **Convert**: File contents -> file paths. Command outputs -> commands to re-run. Long discussions -> one-line decisions.

### 4. Write & Verify

Save to `.claude/handoffs/YYYY-MM-DD-description.md`. Verify all referenced file paths exist with Glob.

## Handoff Structure

Each handoff doc must contain these sections:

**Session Handoff** — Date + previous session descriptor

**Active Tasks** — `[ ] Task: one line -> file:line | Next: action`

**Key Decisions** — `Topic: outcome <15 words -> file:line`

**Blockers** — `Blocker: description -> Needs: what`

**Essential Files** — `path/to/file.ext  # Why it matters`

**Next Steps (Sequenced)** — `1. Action -> specific command`

**Fresh Session Prompt** — Self-contained continuation prompt: `> Task. Continue at: file:line. Next: action.`

## Token Budgets

| Type        | Max Tokens | When                                     |
| ----------- | ---------- | ---------------------------------------- |
| Standard    | <3K        | Overnight break, task switch             |
| Emergency   | <1K        | Near context limit — critical state only |
| Lightweight | <500       | Quick task switch, parking a thread      |

## Constraints

- File paths over file contents (just-in-time loading in fresh session)
- Never include raw tool outputs or debugging traces
- If unsure about task status, use `git status` and recent commits as ground truth
- The continuation prompt must be self-contained (no external context needed)
- Aggressive minimization — accept nuance loss for token efficiency
