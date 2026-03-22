# Handoff: Create "Analogical Diagnostic Analysis" Skill

## What to Build

A full Claude Code skill at `~/.claude/skills/analogical-diagnostic-analysis/SKILL.md` that packages a 3-step diagnostic prompt chain for codebase evaluation.

## The Discovery (Context)

Over a multi-hour session, the user applied a 3-prompt chain to evaluate `rlm_search/` against the core `rlm/` engine. The chain produced a comprehensive architectural diagnosis that identified 5 systemic problems, 6 missing capabilities, and 3 redesign approaches — all emerging organically from the analogy, not from direct code review.

The user recognized this as a **repeatable, transferable method** and wants it packaged as a skill.

## The Three-Step Chain

```
Step 1: MAP THE TERRITORY (consumer/application layer)
  "Imagine [system] were a [human organization].
   Map every component to a role, with diagrams showing
   the full journey from [entry point] to [final output]."

  → Forces exhaustive reading (can't skip files when every component needs a role)
  → Creates relational understanding (who talks to whom, not just what exists)
  → Produces shared vocabulary for later discussion

Step 2: MAP THE FOUNDATION (provider/engine layer)
  "Now do the same for [underlying system/platform]."

  → CRITICAL: Always map consumer BEFORE provider
  → Gap map emerges from holding both maps simultaneously
  → Reveals leverage gaps (what app assumes vs what core provides)

Step 3: EVALUATE AGAINST BOTH MAPS
  "Send consultants to evaluate [application layer]
   and produce a system built on better [principles]."

  → Multi-perspective audit (architect, researcher, explorer)
  → Analogy carries the evaluation method naturally
  → Findings expressed as organizational absurdities ("the receptionist
     breaks into the lab") — immediately actionable
```

## Why It Works (Three Cognitive Principles)

1. **Analogy-as-forced-completeness**: Every file must have a role. Every data flow must be a relationship. Defeats tendency to summarize and skip.

2. **Consumer-before-provider ordering**: Reading the app layer first builds assumptions/needs. Reading the core second reveals what's available. The delta = leverage gaps. Reversing order produces worse results (you rationalize how the app uses the core instead of seeing what it fails to use).

3. **Vocabulary transfer**: By evaluation time, there's shared language ("The Mail Room", "The Scribe"). Findings land instantly because the reader has the org model loaded.

## Analogy Selection Table

| System type               | Good analogy         | Why                                    |
|---------------------------|----------------------|----------------------------------------|
| Request-response pipeline | Consulting firm      | Client → specialists → curated answer  |
| Processing pipeline       | Refinery             | Raw input → sequential stages → product|
| Event-driven system       | Newsroom             | Sources → editorial → published story  |
| Build/deploy pipeline     | Factory floor        | Raw materials → assembly → shipping    |
| Real-time collaboration   | Orchestra            | Instruments → conductor → performance  |
| Data pipeline             | Refinery             | Crude → processing stages → refined    |

Key constraint: analogy must have **roles with relationships**, not just labels.

## Skill Requirements

Per the user's choice of "Full diagnostic skill":
- Complete 4-phase process (analogy selection, territory mapping, foundation mapping, gap diagnosis)
- Optional consultant dispatch (Step 3 with parallel agents)
- Task tracking integration
- Usable on ANY codebase pair (not RLM-specific)
- Should leverage the Task tool for dispatching parallel consultant agents

## Proven Results

Applied to `rlm_search/` → `rlm/` core, the chain produced:
- **5 systemic problems**: Follow-up hack, shadow client, god object, dual-channel scribe, prompt-code duplication
- **6 missing capabilities**: Prompt caching, critique→confidence loop, corpus-gap detection, SSE reconnection, Cascade timeout handling, missing stdout tag
- **3 redesign approaches**: "Sharpen the Blade" (recommended), "New Departments", "Outside-In"

Applied to `7_RLM_ENRICH/w3/` pipeline, the chain immediately surfaced the core tension: "Why is the refinery hiring a researcher to run an assembly line?" — exposing that the W3 pipeline uses a $15/search autonomous reasoning engine to call 4 functions in a predetermined order.

## Files to Reference

- Memory file with pattern summary: `/Users/farieds/.claude/projects/-Users-farieds-projects-rlm/memory/diagnostic-prompt-chain.md`
- The skill writing guide is available via: `Skill tool → superpowers:writing-skills`
- Skill should be created at: `~/.claude/skills/analogical-diagnostic-analysis/SKILL.md`

## User Preferences

- Senior AI Systems Architect — skip beginner explanations
- Concise, high-signal responses
- Uses `uv` (never `python3` or `pip`)
- Conventional commits
- The user explicitly chose "Full diagnostic skill" (not lightweight or with memory template)
- The user values the evaluatory style and wants it repeatable and adaptable

## TDD Guidance (for writing-skills compliance)

The `writing-skills` skill demands RED-GREEN-REFACTOR. For a diagnostic methodology skill (not a discipline/rules skill), the valid test approach is:

**RED (baseline)**: Give a subagent a codebase pair and ask "evaluate this application layer against its foundation." WITHOUT the skill. Document: Does the agent read exhaustively? Does it create relational understanding? Does it surface leverage gaps? (It won't — it'll produce a surface-level summary.)

**GREEN**: Same task WITH the skill loaded. The agent should: select an analogy, map territory exhaustively, map foundation independently, overlay and diagnose. Output should contain organizational absurdities, not just code observations.

**REFACTOR**: Check if the agent skipped analogy selection, mapped provider before consumer, or produced flat descriptions instead of relational maps. Plug those holes.

This is a **technique skill** (not discipline), so test for correct application, not rule compliance under pressure.

## The Evaluatory Voice (Critical)

The user explicitly valued the TONE of the analysis. The skill must produce:

- **Findings as organizational absurdities**: "The receptionist breaks into the lab's private office and rewires the phone" — not "api.py:353 accesses _persistent_env"
- **Tensions as questions**: "Why is the refinery hiring a researcher to run an assembly line?" — not "The W3 pipeline may be over-engineered"
- **Diagram-heavy presentation**: ASCII org charts, data flow diagrams, journey maps — not just prose
- **The gap map as a side-by-side table**: "What X assumes" vs "What Y provides" — leverage gaps emerge visually

This voice is what makes findings *land*. Without it, the skill produces correct but inert analysis.

## Consultant Brief Templates (for Step 3)

When dispatching parallel agents in Step 3, each gets a specific lens:

**Architect consultant**: Structural violations, complexity hotspots, state management (god objects), leverage gaps between layers. Cites file:line. Produces dependency maps.

**Researcher consultant**: Benchmarks against industry best practices (2025-2026). Searches for patterns in tool composition, streaming, quality control, cost optimization. Returns concrete recommendations with effort/impact ratings.

**Explorer consultant**: Friction audit — redundancy, error paths, token waste, frontend-backend contract fragility, test coverage gaps. Maps every point where the same concept is defined in multiple places or where errors are silently swallowed.

Each consultant should receive: (1) the territory map from Step 1, (2) the foundation map from Step 2, (3) their specific audit brief above.

## What NOT to Do

- Don't re-derive the pattern — it's fully specified above
- Don't create documentation files beyond the skill itself
- Don't skip the TDD process required by `superpowers:writing-skills`
- Don't make it RLM-specific — it must work on any codebase pair
