# Agent Delegation Guide

## Routing: Skill vs Agent vs Team

Stop at first match:

| Signal                                                   | Route          | Why                                                            |
| -------------------------------------------------------- | -------------- | -------------------------------------------------------------- |
| Procedural, in-context (`/commit`, `/release`, `/explain`) | **Skill**    | Stays in main context, fast, preserves cross-skill correlation |
| Isolated heavy work, single worker                       | **Agent**      | Compressed context, scoped tools, results-only return          |
| Workers must coordinate or challenge each other          | **Agent Team** | Shared task list + inter-agent messaging                       |

**Default to skill.** Escalate to agent when token cost or persona isolation demands it. Escalate to team only when parallel ownership is required.

## Core Pipeline

```
researcher → architect → builder → reviewer
  (Scope)     (Design)   (Impl)    (Verify)
```

Skip stages for simple tasks. Single-file bug fix → builder + reviewer. Known implementation → builder only.

### Model Economics

| Agent      | Model   | Reason                                |
| ---------- | ------- | ------------------------------------- |
| architect  | opus    | Design quality justifies cost         |
| researcher | sonnet  | High volume, synthesis over precision |
| builder    | inherit | Matches caller's model                |
| reviewer   | inherit | Matches caller's model                |

## Delegation Template

When spawning any agent, provide:

1. **Concrete objective**: Not "research sandboxes" but "compare Modal vs Prime sandbox cold start times at 100 concurrent calls"
2. **Output format**: What structure to return (findings table, design doc, diff, review report)
3. **Scope boundaries**: What's in scope, what's explicitly out
4. **Context**: Key files, recent decisions, constraints the agent needs to know

## Scaling Rules

| Complexity      | Agents                 | Example                                  |
| --------------- | ---------------------- | ---------------------------------------- |
| Trivial         | 0 (do it directly)     | Fix typo, add docstring                  |
| Simple          | 1 (builder)            | Add a new client method                  |
| Medium          | 2 (builder + reviewer) | New environment, API change              |
| Complex         | 3-4 (full pipeline)    | Cross-layer feature, protocol change     |
| Research-heavy  | researcher first       | Library eval, architecture decision      |

## Parallel vs Sequential

**Parallel** (no data dependency):

- 2 researchers: web + codebase → merge findings
- reviewer on file A + builder on file B (no overlap)

**Sequential** (output feeds input):

- architect → builder (builder needs the design)
- builder → reviewer (reviewer needs the diff)
- doc-optimizer → doc-writer (writer needs the audit report)

**Never**: Multiple builders editing overlapping files.

## Resume vs Fresh

Resume (`agentId`) when the agent accumulated diagnostic state worth keeping.

Start fresh when the prior context would be noise (new topic, different files).

## Anti-Patterns

- Spawning architect for a one-line change
- Giving builder a vague task ("make it better")
- Skipping reviewer after multi-file changes
- Running the full pipeline for every task regardless of complexity
- Using an agent when a skill does the same thing in-context
- Spawning a team for work that doesn't require inter-agent coordination
