---
name: mastering-subagents
description: Comprehensive guide for designing, configuring, and evaluating Claude Code subagents. Use when creating new subagents, optimizing existing agents, planning multi-agent workflows, or when the user mentions "subagent design", "create agent", "agent architecture", "delegation", or "multi-agent".
---

# Mastering Subagents: A Practitioner's Guide

## Synthesized from Anthropic's Official Documentation, Engineering Posts & Boris Cherny's Workflow

---

## 1. What Subagents Actually Are (Mental Model)

A subagent is **not** a separate chatbot. It's a pre-configured AI personality that runs in **its own isolated context window** with a custom system prompt, a scoped set of tools, and an independent permission model. When the orchestrating agent (the "lead" or "main" agent) encounters a task matching a subagent's expertise, it delegates that task. The subagent works independently and returns only the relevant results — not its full context.

**Boris Cherny's framing:** "Agents are not 'one big agent.' They're modular roles. Reliability comes from specialization plus constraint." He treats subagents like slash commands — each one owns a phase of the development lifecycle.

**The core insight from Anthropic's multi-agent research system:** Subagents facilitate _compression_. They operate in parallel with their own context windows, exploring different aspects simultaneously, then condense the most important tokens back to the lead agent. This is why multi-agent systems outperform single agents by 90%+ on breadth-heavy tasks.

---

## 2. Why Subagents Work: The Four Benefits

### 2.1 Context Preservation

Each subagent operates in its own context window. This prevents pollution of the main conversation and keeps it focused on high-level objectives. For long-running sessions, this is critical — the main agent's context stays clean while subagents handle the information-heavy lifting.

### 2.2 Specialized Expertise

A subagent fine-tuned with detailed instructions for a specific domain achieves higher success rates than a generalist agent attempting the same task. The system prompt becomes the subagent's "personality and expertise."

### 2.3 Reusability

Once created, subagents can be version-controlled, shared with your team, and reused across projects. Anthropic's teams check their `.claude/agents/` directory into Git.

### 2.4 Flexible Permissions

Each subagent gets only the tools necessary for its purpose. A code reviewer gets `Read, Grep, Glob, Bash` — not `Edit` or `Write`. This improves both security and focus.

---

## 3. Architecture: How Subagents Fit Into the System

### 3.1 The Orchestrator-Worker Pattern

Anthropic's multi-agent research system uses this pattern:

```
User Query
    ↓
Lead Agent (Orchestrator)
    ├── Plans & decomposes the task
    ├── Spawns Subagent 1 → (parallel search/analysis) → returns findings
    ├── Spawns Subagent 2 → (parallel search/analysis) → returns findings
    ├── Spawns Subagent 3 → (parallel search/analysis) → returns findings
    ↓
Lead Agent synthesizes results
    ↓
Optional: Citation Agent / Verification Agent
    ↓
Final Output to User
```

### 3.2 The Agent Feedback Loop (Claude Agent SDK)

Every agent (including subagents) operates in a loop:

```
Gather Context → Take Action → Verify Work → Repeat
```

This is the fundamental pattern. Your subagents should be designed with this loop in mind — each one needs tools for gathering context, tools for acting, and a way to verify its own output.

### 3.3 Critical Constraint: No Nested Spawning

**Subagents cannot spawn other subagents.** If your workflow requires nested delegation, you must chain subagents from the main conversation or use Skills instead.

---

## 4. Configuration: The Anatomy of a Subagent

### 4.1 File Format

Subagents are Markdown files with YAML frontmatter:

```markdown
---
name: your-subagent-name
description: Description of when this subagent should be invoked
tools: tool1, tool2, tool3 # Optional - inherits all tools if omitted
model: sonnet # Optional - sonnet, opus, haiku, or inherit
permissionMode: default # Optional - controls permission handling
skills: skill1, skill2 # Optional - skills to auto-load
---

Your subagent's system prompt goes here. This is where the magic happens.
Multiple paragraphs, specific instructions, examples, constraints.
```

### 4.2 File Locations

| Type                  | Location             | Scope                | Priority |
| --------------------- | -------------------- | -------------------- | -------- |
| **Project subagents** | `.claude/agents/`    | Current project only | Highest  |
| **CLI subagents**     | `--agents` flag      | Session only         | Medium   |
| **User subagents**    | `~/.claude/agents/`  | All projects         | Lower    |
| **Plugin subagents**  | Plugin `agents/` dir | Plugin scope         | Lowest   |

Project-level subagents take precedence when names conflict.

### 4.3 Configuration Fields Reference

| Field            | Required | Description                                                     |
| ---------------- | -------- | --------------------------------------------------------------- |
| `name`           | Yes      | Lowercase letters and hyphens only                              |
| `description`    | Yes      | Natural language — this is what triggers automatic delegation   |
| `tools`          | No       | Comma-separated list. Omit to inherit all tools                 |
| `model`          | No       | `sonnet` (default), `opus`, `haiku`, or `inherit`               |
| `permissionMode` | No       | `default`, `acceptEdits`, `bypassPermissions`, `plan`, `ignore` |
| `skills`         | No       | Comma-separated skill names to auto-load                        |

### 4.4 Model Selection Strategy

Boris Cherny uses Opus 4.6 with thinking for everything — his rationale is that superior comprehension leads to fewer mistakes and less rework, saving time overall despite slower speed. "Less babysitting, more shipping."

For subagents specifically:

- **Opus**: Complex reasoning, multi-step analysis, code review that requires deep understanding
- **Sonnet** (default): Good balance for most tasks — the built-in general-purpose and plan subagents use Sonnet
- **Haiku**: Fast, lightweight tasks like file discovery and code exploration (the built-in Explore subagent uses Haiku)
- **`inherit`**: Matches the main conversation's model — useful for consistency

---

## 5. The Built-in Subagents (Study These First)

### 5.1 General-Purpose Subagent

- **Model**: Sonnet
- **Tools**: All tools
- **Mode**: Read AND write — can modify files and execute commands
- **When used**: Complex tasks requiring both exploration and modification, multi-step operations with dependencies

### 5.2 Plan Subagent

- **Model**: Sonnet
- **Tools**: Read, Glob, Grep, Bash (exploration only)
- **Purpose**: Research during plan mode — gathers context before presenting a plan
- **Key insight**: Prevents infinite nesting (subagents can't spawn subagents)

### 5.3 Explore Subagent

- **Model**: Haiku (fast, low-latency)
- **Mode**: Strictly read-only
- **Tools**: Glob, Grep, Read, Bash (read-only commands: ls, git status, find, cat, head, tail)
- **Thoroughness levels**: Quick → Medium → Very thorough

The Explore subagent exemplifies a key design principle: **constrain to the minimum capability needed.** It can't write or edit — that's the point. Its read-only constraint makes it fast, safe, and focused.

---

## 6. Best Practices: What Actually Works

### 6.1 From the Official Documentation

**Start with Claude-generated agents, then customize.** Use `/agents` → Create New Agent → let Claude generate the initial subagent, then iterate. This gives you a solid foundation.

**Design focused subagents.** Single, clear responsibility per subagent. Don't build one subagent that does everything. This improves performance and predictability.

**Write detailed prompts.** Include specific instructions, examples, and constraints. The more guidance, the better. The system prompt IS the subagent's expertise.

**Limit tool access.** Only grant tools necessary for the subagent's purpose. Security + focus.

**Version control everything.** Check `.claude/agents/` into Git. The team benefits and improves collaboratively.

### 6.2 From Boris Cherny's Workflow

**Coding is a pipeline of phases, each needing a different "mind":**

```
Spec → Draft → Simplify → Verify
```

Cherny uses dedicated subagents for each phase:

- **code-simplifier**: Cleans up architecture after main work is done
- **verify-app**: Runs end-to-end tests before anything ships

**The adversarial review pattern:**
Cherny's code review command spawns several subagents at once:

1. First wave: One checks style guidelines, another combs project history, another flags bugs
2. Second wave: Five more subagents specifically tasked with poking holes in the first wave's findings
3. Result: "Finds all the real issues without the false ones"

**Give subagents verification loops.** The single most impactful tip: give the AI a way to verify its own work — running bash commands, test suites, or browser automation. This improves quality by 2-3x.

### 6.3 From Anthropic's Multi-Agent Research System

**Teach the orchestrator how to delegate.** Each subagent needs:

- A concrete **objective**
- An **output format**
- Guidance on **tools and sources to use**
- Clear **task boundaries**

Without detailed task descriptions, subagents duplicate work, leave gaps, or fail to find necessary information. Vague instructions like "research the semiconductor shortage" lead to duplicated effort and misinterpretation.

**Scale effort to query complexity.** Embed scaling rules:

- Simple fact-finding: 1 agent, 3-10 tool calls
- Direct comparisons: 2-4 subagents, 10-15 calls each
- Complex research: 10+ subagents with clearly divided responsibilities

**Start wide, then narrow.** Search strategy should mirror expert human research — explore the landscape before drilling into specifics. Agents default to overly specific queries.

**Let agents improve themselves.** Claude 4 models can diagnose why an agent is failing and suggest prompt improvements. Anthropic's tool-testing agent rewrites tool descriptions after testing them dozens of times, resulting in a 40% decrease in task completion time.

---

## 7. Prompt Engineering for Subagents

The system prompt is your primary lever. Here's a framework:

### 7.1 Structure Template

```markdown
---
name: [name]
description:
  [
    When and why to invoke — use "PROACTIVELY" or "MUST BE USED" for automatic triggering,
  ]
tools: [Minimum necessary tools]
model: [Choose based on task complexity]
---

## Role

You are a [specific expertise]. Your purpose is [concrete objective].

## When Invoked

1. [First action — usually gather context]
2. [Second action — analysis/processing]
3. [Third action — take action or produce output]
4. [Fourth action — verify results]

## Process / Checklist

- [Specific criteria 1]
- [Specific criteria 2]
- [Specific criteria 3]

## Output Format

Provide findings organized by:

- [Category 1] (with examples of what belongs here)
- [Category 2] (with examples)

## Constraints

- [What NOT to do]
- [Boundaries]
- [When to escalate back to main agent]
```

### 7.2 Key Prompting Principles

**Think like your agents.** Build a mental model of how the agent will interpret your prompt. Use Anthropic's Console to simulate step-by-step execution.

**Guide the thinking process.** Extended thinking serves as a controllable scratchpad. The lead agent uses thinking to plan; subagents use interleaved thinking after tool results to evaluate quality and identify gaps.

**Instill heuristics, not rigid rules.** Encode expert strategies: decompose difficult questions, evaluate source quality, adjust approach based on new information, recognize when to go deep vs. broad.

**Proactively mitigate unintended side effects.** Set explicit guardrails. Early agents at Anthropic spawned 50 subagents for simple queries and searched the web endlessly. Guardrails prevent spiral behavior.

---

## 8. Advanced Patterns

### 8.1 Chaining Subagents

For complex workflows, chain multiple subagents sequentially:

```
> First use the code-analyzer subagent to find performance issues,
  then use the optimizer subagent to fix them
```

Or pipeline-style:

```
analyst → architect → implementer → tester → security audit
```

### 8.2 Parallel Subagents

Run subagents in parallel when dependencies are low:

```
┌─ UI subagent
├─ API subagent      (all running simultaneously)
└─ DB subagent
```

Anthropic's research system spins up 3-5 subagents in parallel, each using 3+ tools in parallel. This cut research time by up to 90%.

### 8.3 Adversarial Subagent Chains (Cherny Pattern)

```
Wave 1: Multiple subagents each check different aspects
Wave 2: Multiple subagents challenge Wave 1's findings
Final: Only real issues survive
```

### 8.4 Resumable Subagents

Each subagent execution gets a unique `agentId`. You can resume a previous subagent to continue its conversation with full context:

```
> Resume agent abc123 and now analyze the authorization logic as well
```

Use cases: Long-running research across sessions, iterative refinement, multi-step workflows with maintained context.

### 8.5 The Two-Claude Planning Pattern

One engineer on Anthropic's team runs two Claude instances for complex tasks:

1. First Claude writes the plan
2. Second Claude reviews the plan as a staff engineer would
3. Only then does implementation begin

This adversarial review catches logical gaps and architectural issues before any code is written.

---

## 9. Practical Examples

### 9.1 Code Reviewer (from official docs)

```markdown
---
name: code-reviewer
description: Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code.
tools: Read, Grep, Glob, Bash
model: inherit
---

You are a senior code reviewer ensuring high standards of code quality and security.

When invoked:

1. Run git diff to see recent changes
2. Focus on modified files
3. Begin review immediately

Review checklist:

- Code is simple and readable
- Functions and variables are well-named
- No duplicated code
- Proper error handling
- No exposed secrets or API keys
- Input validation implemented
- Good test coverage
- Performance considerations addressed

Provide feedback organized by priority:

- Critical issues (must fix)
- Warnings (should fix)
- Suggestions (consider improving)

Include specific examples of how to fix issues.
```

### 9.2 Debugger (from official docs)

```markdown
---
name: debugger
description: Debugging specialist for errors, test failures, and unexpected behavior. Use proactively when encountering any issues.
tools: Read, Edit, Bash, Grep, Glob
---

You are an expert debugger specializing in root cause analysis.

When invoked:

1. Capture error message and stack trace
2. Identify reproduction steps
3. Isolate the failure location
4. Implement minimal fix
5. Verify solution works

Debugging process:

- Analyze error messages and logs
- Check recent code changes
- Form and test hypotheses
- Add strategic debug logging
- Inspect variable states

For each issue, provide:

- Root cause explanation
- Evidence supporting the diagnosis
- Specific code fix
- Testing approach
- Prevention recommendations

Focus on fixing the underlying issue, not just symptoms.
```

### 9.3 Data Scientist (from official docs)

```markdown
---
name: data-scientist
description: Data analysis expert for SQL queries, BigQuery operations, and data insights. Use proactively for data analysis tasks and queries.
tools: Bash, Read, Write
model: sonnet
---

You are a data scientist specializing in SQL and BigQuery analysis.

When invoked:

1. Understand the data analysis requirement
2. Write efficient SQL queries
3. Use BigQuery command line tools (bq) when appropriate
4. Analyze and summarize results
5. Present findings clearly

Key practices:

- Write optimized SQL queries with proper filters
- Use appropriate aggregations and joins
- Include comments explaining complex logic
- Format results for readability
- Provide data-driven recommendations

For each analysis:

- Explain the query approach
- Document any assumptions
- Highlight key findings
- Suggest next steps based on data

Always ensure queries are efficient and cost-effective.
```

---

## 10. Evaluation: How to Know Your Subagents Work

### 10.1 Start Small, Start Now

Don't wait for a large eval suite. Start with ~20 representative queries. In early development, a prompt tweak might boost success from 30% to 80% — you can spot this with small samples.

### 10.2 LLM-as-Judge

Use an LLM to evaluate outputs against a rubric:

- **Factual accuracy**: Do claims match sources?
- **Completeness**: Are all requested aspects covered?
- **Source quality**: Primary sources over secondary?
- **Tool efficiency**: Right tools, reasonable number of times?
- **Output format**: Did it follow the specified structure?

Anthropic found a single LLM call with scores from 0.0-1.0 was most consistent.

### 10.3 Human Evaluation

People catch what automation misses: hallucinated answers on unusual queries, system failures, subtle source selection biases. Anthropic's testers caught agents consistently choosing SEO-optimized content farms over authoritative sources.

### 10.4 Observability

Minor changes in agentic systems cascade into large behavioral changes. Debugging happens on the fly. Monitor agent decision patterns and interactions. Capture traces for prompts, tool invocations, token usage, and orchestration steps.

---

## 11. Cost & Performance Considerations

### Token Economics

- Standard chat: baseline tokens
- Single agent: ~4x more tokens than chat
- Multi-agent system: ~15x more tokens than chat

**Implication**: Multi-agent systems require tasks where the value justifies the cost. They excel at valuable tasks with heavy parallelization and information that exceeds single context windows.

### What Explains Performance

Anthropic's analysis of BrowseComp evaluation:

- **Token usage alone**: explains 80% of performance variance
- **Number of tool calls**: additional factor
- **Model choice**: additional factor (upgrading model > doubling token budget)

### Context Efficiency

Subagents help preserve the main agent's context, enabling longer overall sessions. The tradeoff: subagents start fresh each time and may add latency while gathering the context they need.

---

## 12. Key Takeaways

1. **Subagents are about specialization + constraint**, not complexity
2. **The description field drives automatic delegation** — make it specific and action-oriented
3. **Each subagent needs: objective, output format, tool guidance, task boundaries**
4. **Start with Claude-generated subagents**, then customize
5. **Version control your subagents** — they're team assets
6. **Give every subagent a verification loop** — this is the single biggest quality multiplier
7. **Chain and parallelize** for complex workflows, but remember: no nested spawning
8. **Scale effort to complexity** — don't over-invest in simple tasks
9. **Think like your agents** — simulate step-by-step to find failure modes
10. **Evaluate early and often** — 20 test cases beats 0 test cases every time

---

## Sources

- [Claude Code Subagents Documentation](https://code.claude.com/docs/en/sub-agents)
- [Anthropic Engineering: How We Built Our Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic Engineering: Building Agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- Boris Cherny's workflow (X thread, January 2026) — via VentureBeat, InfoQ, DEV Community analysis
