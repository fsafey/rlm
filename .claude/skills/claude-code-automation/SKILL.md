---
name: claude-code-automation
description: Design, evaluate, and learn about Claude Code automation primitives — Skills, subagents, and agent teams. Use when creating new primitives, evaluating existing ones, deciding between approaches, or learning about agent architecture. Triggers on "skill design", "create skill", "subagent design", "create agent", "agent architecture", "agent team", "team lead", "which primitive", "delegation", "progressive disclosure", "evaluate agent", "audit skill", "mastering subagents", "mastering skills", "mastering teams".
---

# Claude Code Automation: Skills, Subagents & Teams

## The Three Primitives

```
Skill       → what Claude knows    (on-demand knowledge, loaded into context)
Subagent    → who Claude delegates (isolated context, scoped tools, returns results)
Agent Team  → how Claudes collaborate (inter-agent messaging, shared task list)
```

## Decision Framework (apply top-down, stop at first match)

```
Single procedure, no isolation needed?
  → Skill (context: main)

Heavy exploration, results-only needed?
  → Forked Skill (context: fork)

Specialized persona, scoped tools, one focused job?
  → Subagent (.claude/agents/)

Persona + domain knowledge combined?
  → Subagent with skills: field

Multiple workers that must discuss, challenge, or self-coordinate?
  → Agent Team

Pipeline of phases, each needing a different "mind"?
  → Chained subagents (sequential) or Agent Team (parallel)

Cross-layer feature (frontend + API + DB)?
  → Agent Team with file ownership boundaries
```

## Composition Rules

1. Skills load INTO subagents via `skills:` field — eager, at spawn time
2. Skills load for ALL teammates automatically — team onboarding
3. Subagents spawn WITHIN teammates — two-level hierarchy allowed
4. Forked skills (`context: fork`) = lightweight subagent — convergence point
5. **No nesting**: subagents cannot spawn subagents; teammates cannot spawn teams
6. `context: main` (default) runs in caller's context; `context: fork` isolates
7. `disable-model-invocation: true` → user-only invocation (no auto-trigger)

## Progressive Disclosure (the core design principle)

```
Level 1: name + description     → always in system prompt (minimal cost)
Level 2: SKILL.md body          → loaded when Claude triggers it (on-demand)
Level 3: supporting files       → loaded when specific details needed (deep on-demand)
```

Token budget: SKILL.md < 500 lines. References at single depth. Never nested references.

---

## When Invoked

### Learning Mode

If the user wants to understand or learn about a primitive, load the relevant guide:

- Subagent design, configuration, patterns → Read [subagents.md](subagents.md)
- Skill design, progressive disclosure, authoring → Read [skills.md](skills.md)
- Agent team coordination, lifecycle, patterns → Read [teams.md](teams.md)

Teach from the guide. Use examples. Connect to the user's specific context.

### Evaluation Mode

If the user wants to evaluate or audit existing primitives:

1. **Inspect existing assets** before recommending anything new:
   - Project: `.claude/agents/`, `.claude/skills/`, `CLAUDE.md`
   - Don't reinvent what already exists
2. **Load the relevant guide(s)** as evaluation rubrics — only what the consultation requires
3. **Assess against anti-patterns** and quality criteria below
4. **Return findings** with specific remediation guidance

Output format for evaluations:
- Pass/fail against each anti-pattern
- Progressive disclosure compliance
- Tool minimality assessment
- Description trigger-term coverage
- Specific remediation steps

### Design Mode

If the user wants to create a new primitive:

1. **Clarify the need**: What problem is being automated? What level of coordination, isolation, and expertise is required? Ask questions, don't assume.
2. **Select primitive**: Apply the decision framework. Justify — why this and not the simpler one?
3. **Load the relevant guide** for structural patterns and best practices
4. **Return an architectural spec**, not a finished artifact:
   - Which primitive and why (with alternatives considered)
   - Structural skeleton (frontmatter shape, tool list, model choice)
   - Quality criteria the final artifact must meet
   - What domain knowledge the human must supply — use `[DOMAIN: description]` placeholders
   - Anti-patterns to watch for during implementation

---

## Anti-Patterns (evaluate every design against these)

- Building a team when subagents suffice (no inter-worker discussion needed)
- Building a subagent when a skill suffices (no isolation needed)
- Putting on-demand knowledge in CLAUDE.md (use a skill)
- Putting always-needed knowledge in a skill (use CLAUDE.md)
- Eager-loading skills via `skills:` field when lazy Read suffices
- Two teammates editing the same file (no file locking exists)
- Vague descriptions ("helps with code") — must include trigger terms
- Over 500 lines in SKILL.md — split into referenced files
- Nested file references (SKILL.md → ref.md → sub-ref.md)
- Duplicating knowledge across CLAUDE.md, skills, and agents

## Quality Criteria

- Description includes specific trigger terms (not vague)
- Tools are minimum necessary (principle of least privilege)
- Model matches task complexity (haiku=exploration, sonnet=balanced, opus=reasoning)
- No duplication with existing CLAUDE.md, skills, or agents
- Verification loop exists (gather → act → verify → repeat)
- Progressive disclosure respected (no eager-loading of large references)
- SKILL.md under 500 lines
- Subagent system prompt detailed enough for autonomous operation
- Agent team has explicit file ownership boundaries (no shared files)

## Model Selection

| Agent/Skill    | Model   | Reason                                |
| -------------- | ------- | ------------------------------------- |
| architect      | opus    | Design quality justifies cost         |
| researcher     | sonnet  | High volume, synthesis over precision |
| builder        | inherit | Matches caller's model                |
| reviewer       | inherit | Matches caller's model                |
| explorer       | haiku   | Fast, read-only, low-latency          |

## Constraints

- If the need doesn't warrant a new primitive (just add to CLAUDE.md or an existing skill), say so
- Don't over-engineer — minimum complexity for the current need
- Engage conversationally when the question is ambiguous — ask before speccing
- Domain knowledge is the human's responsibility; structural knowledge is yours
