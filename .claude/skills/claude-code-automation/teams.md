# Mastering Agent Teams: A Practitioner's Guide

## Coordinating Multiple Claude Code Instances with Shared Tasks, Inter-Agent Messaging & Centralized Management

---

## 1. What Agent Teams Are (Mental Model)

Agent teams let you coordinate **multiple independent Claude Code instances** working together on a shared codebase. One session acts as the **team lead** — it creates the team, spawns teammates, assigns tasks, and synthesizes results. Teammates work independently, each in **its own context window**, and communicate **directly with each other**.

> **The core architectural insight:** LLMs perform worse as context expands. Agent teams formalize the same principle human teams use — specialization is about focus. The testing agent has testing in its context, not the three-hour planning discussion. The security reviewer doesn't wade through performance optimization notes.

**Agent teams are experimental** and disabled by default. Enable via:

```json
// settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Or in your shell:

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

---

## 2. Agent Teams vs. Subagents vs. Skills — When to Use What

This is the critical decision framework. All three parallelize work, but they operate at fundamentally different levels:

| Dimension             | Subagents                                          | Agent Teams                                           | Forked Skills                                    |
| --------------------- | -------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------ |
| **Context**           | Own context window; results return to caller       | Own context window; fully independent                 | Own context window; results return to caller     |
| **Communication**     | Report results back to main agent only             | Teammates message each other directly                 | No inter-agent communication                     |
| **Coordination**      | Main agent manages all work                        | Shared task list with self-coordination               | None — single-shot execution                     |
| **Lifecycle**         | Ephemeral — created and destroyed within a session | Persistent sessions that can run for extended periods | Ephemeral — single invocation                    |
| **Human interaction** | Users don't interact directly with subagents       | Can message any teammate directly, bypass the lead    | Can invoke via `/skill-name`                     |
| **Best for**          | Focused tasks where only the result matters        | Complex work requiring discussion and collaboration   | Heavy exploration without polluting main context |
| **Token cost**        | Lower — results summarized back                    | Highest — each teammate is a separate Claude instance | Moderate — isolated single execution             |
| **Nesting**           | Cannot spawn other subagents                       | Cannot spawn sub-teams. Only lead manages team        | Cannot spawn subagents                           |

### Decision Framework

```
Is the task sequential with clear dependencies?
  → Single session or chained subagents

Does each worker need to operate independently with no inter-worker communication?
  → Subagents (parallel, report back to orchestrator)

Do workers need to share findings, challenge each other, or self-coordinate?
  → Agent Teams

Is it a heavy read-only exploration that shouldn't pollute main context?
  → Forked Skill (context: fork)

Is the task a one-shot knowledge application (conventions, templates)?
  → Inline Skill (context: main)
```

---

## 3. Architecture Deep Dive

### 3.1 Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                        YOU (Human)                          │
│                                                             │
│  • Describe the task and team structure in natural language  │
│  • Can message any teammate directly (bypass lead)          │
│  • Can use Shift+Up/Down to select teammates                │
│  • Press Shift+Tab for delegate mode                        │
│  • Press Ctrl+T to toggle task list                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    TEAM LEAD (Claude)                        │
│                                                             │
│  • Creates the team and spawns teammates                    │
│  • Breaks work into tasks with dependencies                 │
│  • Assigns tasks or lets teammates self-claim               │
│  • Synthesizes findings across all teammates                │
│  • Makes plan approval decisions autonomously               │
│  • Cleans up the team when work is done                     │
│                                                             │
│  In delegate mode: restricted to coordination-only tools    │
│  (spawning, messaging, shutting down, task management)      │
└───────┬──────────────┬──────────────────┬───────────────────┘
        │              │                  │
        ▼              ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Teammate A   │ │ Teammate B   │ │ Teammate C   │
│              │ │              │ │              │
│ Own context  │ │ Own context  │ │ Own context  │
│ Own tools    │ │ Own tools    │ │ Own tools    │
│ Own perms    │ │ Own perms    │ │ Own perms    │
│              │◄┤►            │◄┤►            │
│  Can message │ │  Can message │ │  Can message │
│  ANY other   │ │  ANY other   │ │  ANY other   │
│  teammate    │ │  teammate    │ │  teammate    │
└──────────────┘ └──────────────┘ └──────────────┘
        ▲              ▲                  ▲
        └──────────────┼──────────────────┘
                       │
              ┌────────┴────────┐
              │   SHARED TASK   │
              │      LIST       │
              └─────────────────┘
```

### 3.2 Messaging System

- **`message`**: Send to one specific teammate (targeted)
- **`broadcast`**: Send to all teammates simultaneously (use sparingly — costs scale with team size)
- **Automatic delivery**: When teammates send messages, they're delivered automatically. The lead doesn't need to poll.
- **Idle notifications**: When a teammate finishes and stops, it automatically notifies the lead.

**Key difference from subagents:** Subagents can ONLY report back to their parent. Teammates can message ANY other teammate directly, enabling genuine collaboration — sharing findings, challenging assumptions, debating approaches.

### 3.3 Storage Layout

```
~/.claude/teams/{team-name}/config.json    # Team config with members array
~/.claude/tasks/{team-name}/               # Task list files
```

The `config.json` contains a members array with each teammate's:

- Name
- Agent ID
- Agent type

Teammates can read this file to discover other team members.

### 3.4 Context Loading

Each teammate loads the same project context as a regular session:

- **CLAUDE.md** files from working directory
- **MCP servers** configured for the project
- **Skills** (both personal and project)
- **Spawn prompt** from the lead

**Critical:** Teammates do NOT inherit the lead's conversation history. Everything task-specific must go in the spawn prompt.

### 3.5 Permissions

Teammates start with the lead's permission settings. If the lead runs with `--dangerously-skip-permissions`, ALL teammates do too. You can change individual teammate modes after spawning, but cannot set per-teammate modes at spawn time.

---

## 4. The Full Lifecycle

### 4.1 Creating a Team

Two paths:

**You request a team:** Give Claude a task that benefits from parallel work and explicitly ask for an agent team.

```
I'm designing a CLI tool that helps developers track TODO comments
across their codebase. Create an agent team to explore this from
different angles: one teammate on UX, one on technical architecture,
one playing devil's advocate.
```

**Claude proposes a team:** If Claude determines your task would benefit from parallel work, it may suggest creating a team. You confirm before it proceeds.

In both cases, **you stay in control** — Claude won't create a team without your approval.

### 4.2 Specifying Teammates and Models

Claude decides the number of teammates based on your task, or you can be explicit:

```
Create a team with 4 teammates to refactor these modules in parallel.
Use Opus for each teammate.
```

### 4.3 Task Assignment and Dependencies

The shared task list has three states: **pending → in progress → completed**

Tasks can depend on other tasks — a pending task with unresolved dependencies cannot be claimed until those dependencies complete. Auto-unblocking happens when a blocking task finishes.

Two assignment modes:

- **Lead assigns**: Tell the lead which task to give to which teammate
- **Self-claim**: After finishing a task, a teammate picks up the next unassigned, unblocked task on its own

Task claiming uses **file locking** to prevent race conditions when multiple teammates try to claim the same task simultaneously.

### 4.4 Plan Approval Workflow

For complex or risky tasks, require teammates to plan before implementing:

```
Spawn an architect teammate to refactor the authentication module.
Require plan approval before they make any changes.
```

**The flow:**

1. Teammate works in read-only plan mode
2. Teammate finishes planning → sends plan approval request to lead
3. Lead reviews the plan
4. **Approved** → Teammate exits plan mode, begins implementation
5. **Rejected with feedback** → Teammate stays in plan mode, revises, resubmits

The lead makes approval decisions autonomously. Influence its judgment through your prompt:

- "Only approve plans that include test coverage"
- "Reject plans that modify the database schema"

### 4.5 Quality Gates with Hooks

Use hooks to enforce rules when teammates finish work:

| Hook            | Trigger                         | Use Case                                             |
| --------------- | ------------------------------- | ---------------------------------------------------- |
| `TeammateIdle`  | A teammate is about to go idle  | Exit code 2 → sends feedback, keeps teammate working |
| `TaskCompleted` | A task is being marked complete | Exit code 2 → prevents completion, sends feedback    |

### 4.6 Shutdown and Cleanup

**Shut down a specific teammate:**

```
Ask the researcher teammate to shut down
```

The teammate can approve (exits gracefully) or reject with an explanation.

**Clean up the entire team:**

```
Clean up the team
```

**Critical rules:**

- Always use the LEAD to clean up (teammates' team context may not resolve correctly)
- Lead checks for active teammates — fails if any are still running
- Shut down all teammates before team cleanup

---

## 5. Display Modes

### 5.1 In-Process Mode (Default)

All teammates run inside your main terminal.

| Control         | Action                            |
| --------------- | --------------------------------- |
| `Shift+Up/Down` | Select a teammate                 |
| Type + Enter    | Send message to selected teammate |
| `Enter`         | View a teammate's session         |
| `Escape`        | Interrupt their current turn      |
| `Ctrl+T`        | Toggle the task list              |

**Pros:** Works in any terminal. No setup required.
**Cons:** Hard to monitor 5+ teammates simultaneously.

### 5.2 Split Pane Mode

Each teammate gets its own pane. You see everyone's output at once and click into a pane to interact directly.

```json
{
  "teammateMode": "tmux"
}
```

Or per-session:

```bash
claude --teammate-mode in-process
```

**Requires:** tmux or iTerm2 with `it2` CLI and Python API enabled.
**Not supported in:** VS Code integrated terminal, Windows Terminal, Ghostty.

**The "auto" default** uses split panes if you're already inside a tmux session, otherwise falls back to in-process.

### 5.3 Delegate Mode

Press `Shift+Tab` to cycle into delegate mode. Restricts the lead to **coordination-only tools**:

- Spawning teammates
- Messaging teammates
- Shutting down teammates
- Managing tasks

**No code touching.** This solves the most common agent teams problem: the lead gets distracted and starts implementing tasks itself instead of delegating.

---

## 6. Lessons from the C Compiler Project (Anthropic Engineering)

Anthropic's own stress test of agent teams: **16 parallel Claude agents built a 100,000-line Rust-based C compiler from scratch** that can compile the Linux kernel. Over 2,000 sessions and $20,000 in API costs.

### 6.1 Write Extremely High-Quality Tests

> "Claude will work autonomously to solve whatever problem I give it. So it's important that the task verifier is nearly perfect, otherwise Claude will solve the wrong problem."

Without human oversight, tests ARE the specification. The harness must:

- Be nearly perfect — flawed tests → agents solving the wrong problem
- Evolve as you identify failure modes (Claude breaking existing functionality led to building a CI pipeline)
- Enforce that new commits can't break existing code

### 6.2 Design the Environment for Claude, Not Yourself

**Context window pollution:** The test harness should not print thousands of useless bytes. At most, print a few lines of output. Log important information to a file so Claude can find it when needed. Use `ERROR` on a single line so `grep` finds it. Pre-compute aggregate summary statistics so Claude doesn't have to recompute them.

**Time blindness:** Claude can't tell time and will happily spend hours running tests instead of making progress. The harness should:

- Print incremental progress infrequently
- Include a `--fast` option running 1-10% random sample
- Make the subsample deterministic per-agent but random across agents (full coverage across the swarm, fast iteration per agent)

### 6.3 Make Parallelism Easy

When there are many distinct failing tests, parallelization is trivial — each agent picks a different failing test. But when agents converge on the same bottleneck (like compiling the Linux kernel), all 16 agents hit the same bug and overwrite each other.

**The fix:** Use an oracle (known-good compiler) to partition the problem space. Each agent works on a different partition. Apply this principle generally: **design your task decomposition so agents can work in parallel on different slices, not all attacking the same thing.**

### 6.4 Multiple Agent Roles

Parallelism enables specialization. Alongside the core implementation agents:

- One agent coalesces duplicate code
- One improves compiler performance
- One produces efficient compiled output
- One critiques design from a Rust developer perspective
- One works on documentation

**Not all agents need to do the same type of work.** Specialization within the team is powerful.

### 6.5 Synchronization via Git

The bare-bones but effective synchronization model:

1. Agent takes a "lock" on a task by writing a file to `current_tasks/`
2. If two agents claim the same task, git forces the second to pick differently
3. Agent works, pulls upstream, merges (Claude handles merge conflicts), pushes, removes lock
4. New session spawns in fresh container, cycle repeats

---

## 7. Best Practices from the Community

### 7.1 Task Sizing — The Goldilocks Zone

| Size           | Problem                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------- |
| **Too small**  | Coordination overhead exceeds the benefit                                                 |
| **Too large**  | Teammates work too long without check-ins, risking wasted effort                          |
| **Just right** | Self-contained units that produce a clear deliverable — a function, a test file, a review |

**Target: 5-6 tasks per teammate.** This keeps everyone productive and lets the lead reassign work if someone gets stuck.

### 7.2 File Ownership is Non-Negotiable

Two teammates editing the same file = overwrites. There is no file-level locking yet. You must design around this:

- Break work so each teammate owns a different set of files
- If they must touch the same file, sequence the tasks with dependencies
- Same boundary-setting you'd do with a human team to avoid merge conflicts

### 7.3 Give Teammates Rich Context

Teammates load CLAUDE.md, MCP servers, and Skills automatically but **don't inherit the lead's conversation history**. Put everything task-specific in the spawn prompt:

```
Spawn a security reviewer teammate with the prompt: "Review the
authentication module at src/auth/ for security vulnerabilities.
Focus on token handling, session management, and input validation.
The app uses JWT tokens stored in httpOnly cookies. Report any
issues with severity ratings."
```

**The more specific the brief, the better the output.** You're writing briefs for a team, not a single agent.

### 7.4 Start Read-Only

If you're new to agent teams, start with tasks that have clear boundaries and **don't require writing code**: reviewing a PR, researching a library, investigating a bug. Learn the coordination patterns before you let multiple agents write code simultaneously.

### 7.5 Monitor and Steer

Check in on teammates' progress, redirect approaches that aren't working, and synthesize findings as they come in. Letting a team run unattended for too long increases the risk of wasted effort.

### 7.6 Use Delegate Mode for Large Teams

When the lead starts coding instead of coordinating, gaps appear. For teams of 3+ teammates, delegate mode is strongly recommended.

### 7.7 The "Wait" Command

The lead sometimes starts implementing tasks itself:

```
Wait for your teammates to complete their tasks before proceeding
```

---

## 8. Patterns That Work

### 8.1 Adversarial Hypothesis Testing

The single most powerful agent teams pattern. Sequential investigation suffers from **anchoring bias** — once one theory is explored, subsequent investigation is biased toward it. Multiple independent investigators actively trying to disprove each other converge on the actual root cause far faster.

```
Users report the app exits after one message instead of staying
connected. Spawn 5 agent teammates to investigate different hypotheses.
Have them talk to each other to try to disprove each other's theories,
like a scientific debate. Update the findings doc with whatever
consensus emerges.
```

### 8.2 Multi-Lens Code Review

A single reviewer gravitates toward one type of issue at a time. Splitting review criteria into independent domains means each gets thorough attention simultaneously:

```
Create an agent team to review PR #142. Spawn three reviewers:
- One focused on security implications
- One checking performance impact
- One validating test coverage
Have them each review and report findings.
```

Each reviewer works from the same PR but applies a different filter. The lead synthesizes findings across all three.

### 8.3 Cross-Layer Feature Development

Changes that span frontend, backend, and tests — each owned by a different teammate:

```
Create an agent team to implement the user profile feature:
- Frontend teammate: React components in src/components/profile/
- Backend teammate: API endpoints in src/api/profile/
- Test teammate: Integration tests in tests/profile/

Each teammate owns their directory exclusively. Frontend teammate
should mock the API contract. Backend teammate should implement to that
contract. Test teammate writes integration tests once both are ready.
```

### 8.4 Research → Implementation Pipeline

Multiple teammates research different approaches, share findings, then one or two implement the winner:

```
Create an agent team to evaluate authentication approaches:
- Teammate 1: Research JWT-based auth (pros, cons, libraries)
- Teammate 2: Research session-based auth (pros, cons, libraries)
- Teammate 3: Research OAuth2/OIDC integration options

Have them share findings and debate. Once consensus emerges,
spawn an implementation teammate to build the chosen approach.
```

### 8.5 Plan → Work → Review → Compound Cycle

Based on the Compound Engineering Plugin philosophy (80% planning and review, 20% execution):

1. **Plan phase**: Lead (or planning teammate) creates a detailed spec
2. **Work phase**: Teammates implement in parallel, each owning a module
3. **Review phase**: Different teammates review each other's work (adversarial)
4. **Compound phase**: Document learnings so future agents benefit from past work

---

## 9. How Agent Teams Interact with Skills, Subagents, and Hooks

### 9.1 Skills in Agent Teams

Teammates load Skills automatically (both personal `~/.claude/skills/` and project `.claude/skills/`). This means:

- Your API conventions Skill is available to every teammate
- Your code review checklist Skill is available to every reviewer
- Your deployment Skill is available when a teammate reaches that phase

**Design implication:** Project Skills become the "team onboarding guide." Put team conventions, patterns, and checklists in Skills so every teammate starts with the right knowledge.

### 9.2 Subagents Within Teammates

Each teammate is a full Claude Code session — it can spawn its own subagents for focused subtasks. This creates a two-level hierarchy:

```
Team Lead
├── Teammate A (backend)
│   ├── Subagent: code reviewer (reads files, reports back)
│   └── Subagent: test writer (generates tests, reports back)
├── Teammate B (frontend)
│   └── Subagent: accessibility auditor
└── Teammate C (tests)
```

**But teammates CANNOT spawn their own teams** (no nested teams). And subagents within a teammate still follow the normal subagent rules — they report back to the teammate only, not to the wider team.

### 9.3 Hooks as Quality Gates

Hooks enforce deterministic rules regardless of what Claude thinks it should do:

```json
{
  "hooks": {
    "TeammateIdle": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/check-teammate-done.sh"
          }
        ]
      }
    ],
    "TaskCompleted": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/validate-task-output.sh"
          }
        ]
      }
    ]
  }
}
```

- **TeammateIdle**: Exit code 2 → sends feedback, keeps teammate working
- **TaskCompleted**: Exit code 2 → prevents completion, sends feedback

### 9.4 CLAUDE.md as Shared Team Knowledge

CLAUDE.md works normally in agent teams — teammates read CLAUDE.md files from their working directory. This is the right place for:

- Build commands and test commands
- Code conventions that EVERY teammate needs
- Architecture decisions that affect all work
- "Don't do X" rules that should be universal

### 9.5 The Full Ecosystem in Agent Teams

```
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE.md (always-on)                     │
│  Loaded by: Lead + ALL teammates automatically              │
│  Contains: Build commands, code style, architecture, norms  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                       AGENT TEAM                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Lead     │  │ Teammate │  │ Teammate │                  │
│  │          │◄►│ A        │◄►│ B        │  (messaging)     │
│  │ Spawns   │  │          │  │          │                  │
│  │ Assigns  │  │ Can use  │  │ Can use  │                  │
│  │ Reviews  │  │ subagents│  │ subagents│                  │
│  │ Approves │  │ & skills │  │ & skills │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│       │                                                     │
│  ┌────┴─────────────────────────────────┐                   │
│  │         SHARED TASK LIST             │                   │
│  │  pending → in_progress → completed   │                   │
│  │  Dependencies auto-unblock           │                   │
│  └──────────────────────────────────────┘                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      MCP SERVERS                            │
│  Available to: Lead + ALL teammates                         │
│  Contains: Slack, GitHub, databases, external APIs          │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                        HOOKS                                │
│  TeammateIdle: Keep teammates working if not done           │
│  TaskCompleted: Validate output before marking done         │
└─────────────────────────────────────────────────────────────┘
```

---

## 10. Token Economics

### 10.1 Cost Reality

| Configuration               | Relative Token Cost                     |
| --------------------------- | --------------------------------------- |
| Single session              | 1x (baseline)                           |
| Single session + subagents  | ~4x                                     |
| 3-teammate agent team       | ~3-5x per teammate                      |
| 5-teammate agent team       | ~5-8x per teammate                      |
| 16-agent C compiler project | 2B input + 140M output tokens, ~$20,000 |

### 10.2 When Agent Teams Are Worth It

**Worth the cost:**

- Parallel exploration where anchoring bias hurts single-agent work
- Multi-lens review where thoroughness matters
- Cross-layer work where context separation improves focus
- Research tasks where breadth of exploration is key
- Large refactoring where each module is independent

**NOT worth the cost:**

- Sequential tasks with heavy dependencies
- Same-file edits (no file locking → overwrites)
- Simple tasks where a single agent is sufficient
- Tasks where coordination overhead exceeds the benefit
- Routine, non-parallelizable work

### 10.3 Cost Optimization Strategies

- Start with 2-3 teammates, scale up only when you understand the pattern
- Use Sonnet for routine teammates, Opus only for complex reasoning
- Use delegate mode to prevent the lead from doing redundant work
- Design tasks to be truly independent (no wasted re-work)
- Set clear "done" criteria so teammates don't spin

---

## 11. Known Limitations and Workarounds

| Limitation                                          | Impact                                                                | Workaround                                               |
| --------------------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------- |
| **No session resumption** for in-process teammates  | `/resume` and `/rewind` don't restore teammates                       | Spawn fresh teammates after resuming                     |
| **Task status can lag**                             | Teammates sometimes fail to mark tasks completed, blocking dependents | Check work manually, nudge lead, or update status        |
| **Shutdown can be slow**                            | Teammates finish current request before stopping                      | Be patient; plan for cleanup time                        |
| **One team per session**                            | Can't run multiple teams from one lead                                | Clean up current team before starting new one            |
| **No nested teams**                                 | Teammates can't spawn their own teams                                 | Use subagents within teammates for sub-delegation        |
| **Lead is fixed**                                   | Can't promote a teammate or transfer leadership                       | Design the lead role carefully upfront                   |
| **Permissions set at spawn**                        | Can't set per-teammate modes at creation                              | Change individual modes after spawning                   |
| **No file-level locking**                           | Two teammates editing same file → overwrites                          | Design file ownership boundaries explicitly              |
| **Split panes require tmux/iTerm2**                 | Not available in VS Code terminal, Windows Terminal                   | Use in-process mode as fallback                          |
| **CLAUDE.md is the only shared persistent context** | No other mechanism for persistent team knowledge                      | Use CLAUDE.md liberally; use Skills for domain knowledge |

---

## 12. Troubleshooting

### Teammates not appearing

- In-process mode: they may be running but not visible. Press `Shift+Down` to cycle through.
- Check that your task was complex enough to warrant a team.
- For split panes: verify `which tmux` returns a path. For iTerm2: verify `it2` CLI is installed and Python API is enabled.

### Too many permission prompts

- Teammate permission requests bubble up to the lead, creating friction.
- Pre-approve common operations in your permission settings BEFORE spawning teammates.

### Teammates stopping on errors

- Check their output via `Shift+Up/Down` (in-process) or click the pane (split mode).
- Give them additional instructions directly, or spawn a replacement.

### Lead implementing instead of delegating

- Say: "Wait for your teammates to complete their tasks before proceeding"
- Or: Press `Shift+Tab` to enable delegate mode (coordination-only tools)

### Orphaned tmux sessions

```bash
tmux ls
tmux kill-session -t <session-name>
```

---

## 13. Practical Example: Full Agent Team Workflow

### Step 1: Enable and Start

```json
// settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Step 2: Describe the Team

```
We need to add user authentication to our Express.js API. Create an
agent team with these teammates:

1. Architecture teammate: Design the auth system (JWT vs sessions,
   middleware structure, database schema). Require plan approval.
2. Backend teammate: Implement the auth endpoints (register, login,
   logout, refresh). Owns src/api/auth/
3. Middleware teammate: Implement auth middleware and guards. Owns
   src/middleware/
4. Test teammate: Write comprehensive tests. Owns tests/auth/

Use delegate mode. Only approve plans that include test strategy
and error handling. The backend and middleware teammates should not
start until the architecture plan is approved.
```

### Step 3: The Lead Creates the Team

Claude:

- Creates a shared task list with dependency chains
- Spawns 4 teammates with specific prompts
- Architecture teammate enters plan mode
- Other teammates wait on architecture approval

### Step 4: Plan Approval

Architecture teammate submits a plan. Lead reviews against your criteria:

- Includes test strategy → proceeds
- Missing error handling → rejected with feedback → teammate revises

### Step 5: Parallel Implementation

Once architecture is approved:

- Backend teammate claims endpoint tasks
- Middleware teammate claims middleware tasks
- Test teammate starts writing test scaffolding
- They message each other to align on interfaces

### Step 6: Cross-Review

```
Have each teammate review one other teammate's work before marking
their section complete. Backend reviews middleware, middleware reviews
tests, tests review backend.
```

### Step 7: Synthesis and Cleanup

Lead synthesizes findings, creates a summary, then:

```
Shut down all teammates, then clean up the team.
```

---

## 14. Key Takeaways

1. **Agent teams are for collaboration, not just parallelism.** The defining feature is inter-agent messaging — teammates share findings, challenge each other, and self-coordinate. If workers just need to report back, use subagents instead.

2. **The lead is an engineering manager, not a developer.** Use delegate mode to enforce this. The lead's job is to break work into tasks, assign them, review plans, synthesize findings, and manage the team lifecycle.

3. **File ownership is non-negotiable.** No file-level locking exists. Design your task decomposition so each teammate owns different files. If they must touch the same file, sequence it with task dependencies.

4. **Spawn prompts ARE the onboarding brief.** Teammates don't inherit conversation history. Everything task-specific must be in the spawn prompt. The more specific the brief, the better the output.

5. **Start read-only, graduate to write.** Begin with code review and research tasks. Learn the coordination patterns before letting multiple agents write code.

6. **5-6 tasks per teammate keeps the flow.** Too few → idle time. Too many → lost context. Self-contained units with clear deliverables are the sweet spot.

7. **Adversarial patterns are the superpower.** Multiple investigators trying to disprove each other's theories converge on truth faster than sequential investigation. This is the pattern that most justifies the token cost.

8. **Tests become the specification.** In autonomous multi-agent work, the test harness IS the quality gate. Invest heavily in test quality — agents will solve whatever the tests measure.

9. **Design for Claude, not for yourself.** Minimize context pollution (short output, errors on one line, summary statistics). Account for time blindness (progress indicators, fast test modes). Make orientation easy (READMEs, progress files).

10. **The ecosystem compounds.** CLAUDE.md provides always-on context. Skills provide on-demand expertise. Subagents provide focused sub-delegation within teammates. Hooks provide deterministic quality gates. MCP provides external tool access. Agent teams orchestrate it all.

---

## Sources

- [Claude Code Agent Teams Documentation](https://code.claude.com/docs/en/agent-teams) — Official documentation
- [Anthropic Engineering: Building a C Compiler with a Team of Parallel Claudes](https://www.anthropic.com/engineering/building-c-compiler) — Nicholas Carlini's stress test with 16 agents, 2000 sessions, $20K
- [Addy Osmani: Claude Code Swarms](https://addyosmani.com/blog/claude-code-agent-teams/) — Practical analysis and management parallels
- [Claude Code Agent Teams: Setup Guide](https://www.marc0.dev/en/blog/claude-code-agent-teams-multiple-ai-agents-working-in-parallel-setup-guide-1770317684454) — Marco Patzelt's setup walkthrough
- [OpenClaw Agent Teams Guide](https://jangwook.net/en/blog/en/claude-agent-teams-guide/) — Production deployment experience
- [NxCode: Claude Opus 4.6 Agent Teams Tutorial](https://www.nxcode.io/resources/news/claude-agent-teams-parallel-ai-development-guide-2026) — Token cost analysis
- [Compound Engineering Plugin](https://github.com/EveryInc/compound-engineering-plugin) — Plan → Work → Review → Compound cycle
