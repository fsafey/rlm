---
name: mastering-agent-skills
description: Comprehensive guide for designing, building, and evaluating Claude Code Skills. Use when creating new Skills, refactoring existing Skills, deciding between Skills vs subagents vs CLAUDE.md, or when the user mentions "skill design", "create skill", "skill architecture", or "progressive disclosure".
---

# Mastering Agent Skills: A Practitioner's Guide

## Synthesized from Anthropic's Official Documentation, Engineering Posts & Context Engineering Framework

---

## 1. What Agent Skills Actually Are (Mental Model)

A Skill is a **directory containing a SKILL.md file** — organized folders of instructions, scripts, and resources that agents can discover and load dynamically. Think of it as an onboarding guide for a new hire: instead of building custom agents for each use case, you capture procedural knowledge into composable, shareable capability packs.

**The key distinction from subagents:** Skills extend what Claude _knows how to do_. Subagents extend _who Claude can delegate to_. A Skill adds domain expertise to the current conversation; a subagent runs in an isolated context window with its own personality.

**The key distinction from CLAUDE.md:** CLAUDE.md is always-on persistent context loaded at session start. Skills are loaded on-demand — Claude reads them only when the task requires them.

**The key distinction from slash commands:** Slash commands were user-invoked (`/command`). Skills are **model-invoked** — Claude autonomously decides when to use them based on the task and the Skill's description. (Legacy slash commands have been merged into Skills; your existing `.claude/commands/` files still work.)

---

## 2. The Core Design Principle: Progressive Disclosure

This is the single most important concept in Skills design. It comes directly from Anthropic's engineering blog:

> "The context window is a public good. Your Skill shares it with everything else Claude needs."

Progressive disclosure works in three levels:

```
Level 1: Metadata (name + description)
    → Pre-loaded into system prompt at startup
    → Just enough for Claude to know WHEN to use the Skill
    → Cost: minimal (always present)

Level 2: SKILL.md body
    → Loaded only when Claude decides the Skill is relevant
    → Contains the actual instructions, workflows, examples
    → Cost: on-demand (only when triggered)

Level 3: Supporting files (reference.md, scripts/, templates/)
    → Loaded only when Claude needs specific details
    → Referenced by name from SKILL.md
    → Cost: deeply on-demand (only specific sections)
```

**The context window sequence:**

1. System prompt contains metadata for ALL installed Skills
2. User sends a message
3. Claude recognizes a Skill is relevant → reads SKILL.md via Bash tool
4. Claude needs specific details → reads supporting files (e.g., `forms.md`)
5. Claude proceeds with the task, now equipped with the right knowledge

**Why this matters:** Because agents have filesystem and code execution tools, they don't need to read an entire Skill into context. The amount of bundled context in a Skill is effectively unbounded — Claude navigates it like a manual, reading chapters as needed.

---

## 3. Skill Anatomy and Configuration

### 3.1 Directory Structure

```
my-skill/
├── SKILL.md              (required — the entry point)
├── reference.md          (optional — detailed documentation)
├── examples.md           (optional — concrete examples)
├── scripts/
│   └── helper.py         (optional — executable utilities)
└── templates/
    └── template.txt      (optional — output templates)
```

### 3.2 SKILL.md Format

```markdown
---
name: your-skill-name
description: Brief description of what this Skill does and when to use it
allowed-tools: Read, Grep, Glob # Optional — restrict tool access
---

# Your Skill Name

## Instructions

Provide clear, step-by-step guidance for Claude.

## Examples

Show concrete examples of using this Skill.

For advanced usage, see [reference.md](reference.md).
```

### 3.3 Frontmatter Fields

| Field                      | Required | Description                                                                          |
| -------------------------- | -------- | ------------------------------------------------------------------------------------ |
| `name`                     | Yes      | Lowercase letters, numbers, hyphens only. Max 64 chars. Becomes the `/slash-command` |
| `description`              | Yes      | What it does + when to use it. Max 1024 chars. This is what drives auto-discovery    |
| `allowed-tools`            | No       | Comma-separated tool allowlist. Without it, Claude uses standard permission model    |
| `disable-model-invocation` | No       | Set `true` to prevent auto-invocation — user must explicitly type `/skill-name`      |
| `context`                  | No       | `main` (default) or `fork`. Fork runs the skill in an isolated subagent context      |
| `agent`                    | No       | Which agent type to use when forked (e.g., `Explore`, `plan`)                        |
| `hooks`                    | No       | Skill-scoped hooks for PreToolUse, PostToolUse, Stop events                          |

### 3.4 File Locations

| Type                | Location                       | Scope                           |
| ------------------- | ------------------------------ | ------------------------------- |
| **Personal Skills** | `~/.claude/skills/skill-name/` | All your projects               |
| **Project Skills**  | `.claude/skills/skill-name/`   | Current project, shared via Git |
| **Plugin Skills**   | Plugin `skills/` directory     | Installed with plugin           |

---

## 4. How Skills Couple with Subagents

This is the critical architectural question. There are **two distinct patterns** for combining Skills and subagents, and they serve fundamentally different purposes:

### 4.1 Pattern A: Skills Field on a Subagent

In the subagent's frontmatter, the `skills` field injects Skill content into the subagent's context at startup:

```markdown
---
name: code-reviewer
description: Reviews code for quality and best practices
tools: Read, Grep, Glob, Bash
skills: api-conventions, security-checklist
---

You are a senior code reviewer...
```

**What happens:** When this subagent is invoked, the specified Skills are automatically loaded into _the subagent's_ context. The subagent controls its own system prompt and uses the Skill content as reference knowledge.

**Use case:** You want a subagent to have access to specific domain knowledge (your API conventions, your security checklist) without putting that knowledge in the subagent's system prompt directly.

**Key insight:** The subagent owns the system prompt. Skills are loaded as references within that prompt.

### 4.2 Pattern B: `context: fork` on a Skill

In the Skill's frontmatter, `context: fork` causes the Skill to execute in its own isolated subagent context:

```markdown
---
name: deep-review
description: Comprehensive code review that explores the codebase
context: fork
agent: Explore
---

When reviewing code:

1. Search for all related files...
2. Analyze patterns...
3. Return structured findings...
```

**What happens:** When this Skill is invoked (either by Claude auto-triggering it or by the user typing `/deep-review`), it spawns a subagent. The Skill content is injected into the agent's context. The parent conversation never sees the internal reasoning, tool use, or intermediate steps — only the final results.

**Use case:** You want a Skill that does heavy exploration (reading many files, running many searches) without polluting your main conversation's context window.

**Key insight:** The Skill IS the task description. It becomes a subagent constructor, not just instructions.

### 4.3 Comparison Table

| Aspect                          | Skills on Subagent (`skills:` field)       | Forked Skill (`context: fork`)                      |
| ------------------------------- | ------------------------------------------ | --------------------------------------------------- |
| **Who owns the system prompt?** | The subagent                               | The Skill content                                   |
| **Where does it run?**          | In the subagent's isolated context         | In a new isolated context spawned by the Skill      |
| **Who triggers it?**            | Claude delegates to the subagent           | Claude or user invokes the Skill                    |
| **Skill's role**                | Reference knowledge injected into subagent | The task definition itself                          |
| **Best for**                    | Subagents that need domain knowledge       | Tasks that need isolation but aren't full subagents |

### 4.4 When to Use Which

**Use Skills (inline, `context: main`)** when:

- You want reusable prompts or workflows that run in the main conversation
- The knowledge enhances Claude's current work without needing isolation
- The output is small and directly useful in the conversation
- Examples: API conventions, style guides, commit message templates

**Use Subagents with Skills (`skills:` field)** when:

- You need a specialized persona with specific domain knowledge
- The task produces verbose output you don't need in your main context
- You want to enforce specific tool restrictions
- The work is self-contained and can return a summary
- Examples: Security reviewer with security checklist Skill, data scientist with SQL conventions Skill

**Use Forked Skills (`context: fork`)** when:

- The Skill does heavy exploration (reads many files)
- You want Skill-level simplicity with subagent-level isolation
- The task is discrete and doesn't need continued interaction
- You want one-shot delegation without defining a full subagent
- Examples: Deep code review, codebase analysis, dependency audit

### 4.5 The Convergence

Skills, slash commands, and subagents are converging toward a single abstraction. As one analysis puts it:

> "Skills can now run in their own context. The `context: fork` field lets a skill run as a subagent — in its own context window. This was subagents' whole reason for existing."

The emerging unified model:

- **One primitive**: A SKILL.md (or agent .md) file
- **One switch**: `context: main` vs `context: fork` determines isolation
- **Composition through references**: Skills can reference other Skills
- **Uniform invocation**: Everything is `/skill-name` or auto-discovered

---

## 5. Skills and Code Execution

Skills can bundle executable code. This is powerful because some operations are better handled by deterministic scripts than token generation.

### 5.1 When to Use Scripts vs. Instructions

| Use Scripts For                                       | Use Instructions For            |
| ----------------------------------------------------- | ------------------------------- |
| Deterministic operations (sorting, parsing)           | Creative or reasoning tasks     |
| Performance-critical operations                       | Contextual decision-making      |
| Operations on data Claude shouldn't load into context | Workflows that need flexibility |
| Validation and verification                           | Explanation and analysis        |

### 5.2 Example: PDF Skill with Scripts

```
pdf-processing/
├── SKILL.md
├── forms.md
├── reference.md
└── scripts/
    ├── extract_fields.py    # Claude runs this without loading PDF into context
    └── fill_form.py
```

SKILL.md references the scripts:

````markdown
## Form Filling

To extract form fields from a PDF, run:

```bash
python scripts/extract_fields.py input.pdf
```
````

For detailed form-filling instructions, see [forms.md](forms.md).

````

Claude executes the script deterministically — consistent, repeatable, and token-efficient.

---

## 6. Best Practices from Anthropic

### 6.1 Core Authoring Principles

**Concise is key.** The context window is a shared resource. Challenge every piece of information:
- "Does Claude really need this explanation?"
- "Can I assume Claude already knows this?"
- "Does this paragraph justify its token cost?"

Claude is already very smart. Only add context Claude doesn't already have.

**Set appropriate degrees of freedom.** Too rigid (step-by-step scripts for every case) makes Skills brittle. Too loose (vague instructions) produces inconsistent results. Find the middle ground: provide structure and heuristics, not rigid procedures.

**Test with all models you plan to use.** Haiku, Sonnet, and Opus handle instructions differently. A Skill tuned for Opus may need simplification for Haiku.

### 6.2 Naming and Description

**Names:**
- Use gerund-style: `processing-pdfs`, `analyzing-spreadsheets`, `testing-code`
- Avoid vague names: `helper`, `utils`, `tools`
- Max 64 characters, lowercase with hyphens

**Descriptions (the most critical field):**
- Include BOTH what it does AND when to use it
- Use declarative phrasing: "Processes Excel files and generates reports"
- Avoid: "I can help you..." or "You can use this to..."
- Include specific trigger terms users would mention

```markdown
# Bad
description: Helps with documents

# Good
description: Extract text and tables from PDF files, fill forms, merge
documents. Use when working with PDF files or when the user mentions
PDFs, forms, or document extraction.
````

### 6.3 File Organization

- Keep SKILL.md **under 500 lines**
- Split content into separate files as you approach that limit
- Keep references at a **single depth level** from SKILL.md — avoid nested file references
- Use directory structure for supporting files over 100 lines
- Code can serve as both executable tools AND documentation — clarify which role each script plays

### 6.4 Progressive Disclosure Patterns

**Pattern 1: High-level guide with references**

```
SKILL.md → "For advanced PDF manipulation, see reference.md"
SKILL.md → "For form filling, see forms.md"
```

**Pattern 2: Domain-specific organization**

```
SKILL.md → overview + routing
api/rest.md → REST conventions
api/graphql.md → GraphQL conventions
api/auth.md → Authentication patterns
```

**Pattern 3: Conditional details**

```
SKILL.md → "If creating presentations, read slide-decks.md"
SKILL.md → "If creating documents, read docs.md"
```

Claude only loads the relevant branch, saving context for other things.

### 6.5 Feedback Loops and Verification

Build verification into your Skills:

```markdown
## Verification Steps

After generating the document:

1. Run `python scripts/validate.py output.pdf` to check structure
2. If validation fails, read the error output and fix the issues
3. Re-run validation until it passes
```

This mirrors the agent feedback loop: Gather Context → Take Action → Verify Work → Repeat.

---

## 7. Developing and Evaluating Skills

### 7.1 Start with Evaluation

Identify specific gaps by running your agent on representative tasks and observing where it struggles. Build Skills incrementally to address those shortcomings. Don't try to anticipate everything upfront.

### 7.2 Iterate with Claude

As you work on a task with Claude:

1. Ask Claude to capture its successful approaches into a Skill
2. Ask it to capture common mistakes as anti-patterns
3. If Claude goes off track, ask it to self-reflect on what went wrong
4. This reveals what context Claude actually needs — not what you think it needs

### 7.3 Observe How Claude Uses Skills

Monitor Claude's behavior:

- Does it trigger the Skill when expected?
- Does it read supporting files when appropriate?
- Does it follow the instructions accurately?
- Does it over-read (loading files it doesn't need)?

Use `claude --debug` to see Skill loading errors and behavior.

### 7.4 Think from Claude's Perspective

Anthropic's engineering blog emphasizes this for both Skills and subagents: build a mental model of how Claude interprets your instructions. Watch for unexpected trajectories or overreliance on certain context. Pay special attention to `name` and `description` — they're Claude's first decision point.

---

## 8. Skills in the Broader Context Engineering Framework

Anthropic's Context Engineering framework has four pillars. Skills play a specific role in each:

### 8.1 System Prompt

Skills metadata (name + description) is pre-loaded here. This is Level 1 of progressive disclosure. Keep metadata minimal and precise.

### 8.2 Tools

Skills can restrict which tools Claude uses (`allowed-tools`). Skills can also bundle executable scripts that act as deterministic tools. Tool descriptions in Skills should be self-contained and non-overlapping.

### 8.3 Data Retrieval (Just-in-Time Context)

Skills ARE the just-in-time context mechanism. Instead of pre-loading all knowledge, Skills let Claude load domain expertise only when needed. This is the paradigm shift from traditional RAG:

| Old Approach (Preload)               | New Approach (Skills)           |
| ------------------------------------ | ------------------------------- |
| Load all docs into context           | Load Skill metadata only        |
| Hope relevant info is present        | Claude discovers what it needs  |
| Context bloated with irrelevant data | Context stays lean              |
| Fixed retrieval                      | Dynamic, agent-driven retrieval |

### 8.4 Long-horizon Optimizations

For long-running tasks:

- **Compaction** summarizes intermediate steps
- **Structured memory** maintains explicit artifacts
- **Subagent architecture** decomposes into focused contexts
- **Skills feed all three**: they provide the knowledge subagents need, the structure for memory artifacts, and the procedures that survive compaction

---

## 9. The Ecosystem: How Skills, Subagents, MCP, and CLAUDE.md Work Together

```
┌─────────────────────────────────────────────────────────┐
│                    CLAUDE.md                             │
│  Always-on project context: conventions, architecture,  │
│  build commands, team norms                             │
│  (loaded at session start, always in context)           │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│                    SKILLS                                │
│  On-demand domain expertise: PDF processing, code       │
│  review checklists, API conventions, deployment steps   │
│  (loaded when relevant, progressive disclosure)         │
│                                                         │
│  Can run in main context OR fork into subagent          │
│  Can bundle scripts for deterministic execution         │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│                   SUBAGENTS                              │
│  Isolated execution contexts: code reviewer, debugger,  │
│  researcher, data scientist                             │
│  (own context window, own tools, own permissions)       │
│                                                         │
│  Can load Skills via `skills:` field                    │
│  Can have persistent memory via `memory:` field         │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│                      MCP                                │
│  External tool integrations: Slack, GitHub, Google      │
│  Drive, databases, APIs                                 │
│  (standardized protocol, tools available to all agents) │
│                                                         │
│  Skills can reference MCP tools                         │
│  Subagents inherit MCP tools (or restrict them)         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                     HOOKS                                │
│  Deterministic triggers: format on save, validate       │
│  before commit, lint after edit                         │
│  (execute regardless of what Claude thinks it should do)│
│                                                         │
│  Can be scoped to: global, project, skill, or subagent  │
└─────────────────────────────────────────────────────────┘
```

### Decision Framework: What Goes Where?

| Knowledge Type                      | Where It Goes                     | Why                                               |
| ----------------------------------- | --------------------------------- | ------------------------------------------------- |
| Build commands, code style          | **CLAUDE.md**                     | Always needed, never changes mid-session          |
| Domain procedures (PDF, Excel)      | **Skills**                        | Needed on-demand, not always                      |
| Team API conventions                | **Skills** (project)              | Shared via Git, loaded when writing APIs          |
| "You are a security expert" persona | **Subagent**                      | Needs isolated context + specific tools           |
| External service access (Slack, DB) | **MCP**                           | Standardized tool integration                     |
| "Always format after edit"          | **Hooks**                         | Deterministic, not dependent on Claude's judgment |
| Subagent + domain knowledge         | **Subagent with `skills:` field** | Persona + expertise combined                      |
| Heavy exploration task              | **Skill with `context: fork`**    | Isolation without full subagent definition        |

---

## 10. Practical Examples

### 10.1 Simple Reference Skill

```markdown
---
name: api-conventions
description: REST API design patterns for our services. Use when writing
API endpoints, reviewing API code, or designing new services.
---

When writing API endpoints:

- Use kebab-case for URL paths
- Use camelCase for JSON properties
- Always include pagination for list endpoints
- Version APIs in the URL path (/v1/, /v2/)
- Return consistent error formats: { "error": { "code": "...", "message": "..." } }
- Include request validation with descriptive error messages
```

### 10.2 Task Skill with Disabled Auto-Invocation

```markdown
---
name: fix-issue
description: Fix a GitHub issue
disable-model-invocation: true
---

Analyze and fix the GitHub issue: $ARGUMENTS.

1. Use `gh issue view` to get the issue details
2. Understand the problem described in the issue
3. Search the codebase for relevant files
4. Implement the fix
5. Run tests to verify
6. Create a commit with a descriptive message
```

User invokes explicitly: `/fix-issue 1234`

### 10.3 Multi-File Skill with Scripts

```
pdf-processing/
├── SKILL.md
├── forms.md
├── reference.md
└── scripts/
    ├── extract_fields.py
    └── validate.py
```

**SKILL.md:**

````markdown
---
name: pdf-processing
description: Extract text, fill forms, merge PDFs. Use when working with
PDF files, forms, or document extraction.
---

## Quick Start

Extract text:

```python
import pdfplumber
with pdfplumber.open("doc.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
````

For form filling, see [forms.md](forms.md).
For detailed API reference, see [reference.md](reference.md).

````

### 10.4 Forked Skill (Subagent-like Isolation)

```markdown
---
name: deep-review
description: Comprehensive code review with full codebase exploration.
Use when asked to do a thorough review or audit.
context: fork
allowed-tools: Read, Grep, Glob, Bash
---

Perform a comprehensive code review:

1. Run `git diff HEAD~1` to see recent changes
2. For each changed file, search for related files and tests
3. Analyze patterns across the codebase
4. Check for consistency with existing conventions

Output a structured report:
## Summary
[One paragraph overview]

## Issues Found
| Severity | File:Line | Issue | Suggested Fix |
|----------|-----------|-------|---------------|

## Positive Observations
[What's done well]
````

### 10.5 Subagent That Loads Skills

```markdown
---
name: security-auditor
description: Security audit specialist. Use proactively when reviewing
code that handles authentication, authorization, or user data.
tools: Read, Grep, Glob, Bash
model: opus
skills: api-conventions, security-checklist
---

You are a senior security engineer. When reviewing code:

1. Check for injection vulnerabilities (SQL, XSS, command injection)
2. Verify authentication and authorization patterns
3. Look for exposed secrets or credentials
4. Validate input handling
5. Check for proper error handling that doesn't leak internals

Reference the api-conventions Skill for expected patterns.
Reference the security-checklist Skill for comprehensive checks.

Provide findings with specific line references and severity ratings.
```

---

## 11. Anti-Patterns to Avoid

**Overloading SKILL.md.** If your SKILL.md exceeds 500 lines, Claude wastes tokens loading content it doesn't need. Split into referenced files.

**Deeply nested references.** SKILL.md → reference.md → sub-reference.md creates navigation overhead. Keep references at one level from SKILL.md.

**Vague descriptions.** "Helps with documents" tells Claude nothing. Specific trigger terms drive discovery.

**Offering too many options.** If a Skill presents five different approaches, Claude may struggle to choose. Provide a clear default path with alternatives only when needed.

**Assuming tools are installed.** List required packages in the description and include installation instructions. Don't assume the environment has everything.

**Duplicating CLAUDE.md content.** If something belongs in CLAUDE.md (always-needed context), don't also put it in a Skill. Use each mechanism for its strength.

**Using Skills for ephemeral context.** Skills are for stable, reusable knowledge. If the context changes every session, it belongs in the conversation or CLAUDE.md, not a Skill.

---

## 12. Security Considerations

Skills provide Claude with new capabilities through instructions and code. Anthropic recommends:

- **Install Skills only from trusted sources**
- **Audit Skills from less-trusted sources** before use — read all bundled files
- **Pay attention to** code dependencies, bundled resources, and network access
- **Watch for** instructions that connect to external network sources
- **Skills with hooks** carry operational semantics — a Skill can enforce behavior via PreToolUse/PostToolUse hooks

---

## 13. Key Takeaways

1. **Skills are on-demand knowledge packs** — not always-on context like CLAUDE.md
2. **Progressive disclosure is the core design principle** — metadata → SKILL.md → supporting files
3. **The description field drives everything** — it's how Claude decides to use your Skill
4. **Skills and subagents couple in two ways**: Skills loaded INTO subagents (`skills:` field), or Skills that BECOME subagents (`context: fork`)
5. **Concise is key** — the context window is a shared resource; justify every token
6. **Bundle scripts for deterministic operations** — code is cheaper and more reliable than token generation for routine tasks
7. **Version control project Skills** — they're team assets, shareable via Git
8. **Start with evaluation** — observe where Claude struggles, then build Skills to fill gaps
9. **Iterate with Claude** — let Claude help discover what context it actually needs
10. **Skills, subagents, and commands are converging** — `context: fork` is the bridge

---

## Sources

- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
- [Anthropic Engineering: Equipping Agents for the Real World with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Skill Authoring Best Practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)
- [Claude Code Subagents Documentation](https://code.claude.com/docs/en/sub-agents) — Skills/subagent coupling
- [Context Engineering from Claude (AWS re:Invent 2025 compilation)](https://01.me/en/2025/12/context-engineering-from-claude/)
- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- Claude Code 2.1 release notes — `context: fork`, skill-scoped hooks
