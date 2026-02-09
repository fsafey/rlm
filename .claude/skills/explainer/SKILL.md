---
name: explainer
description: >
  Transforms explanations using neuroscience-backed methods:
  analogy-first framing, dual-coded visual models, progressive
  chunking, and contrast pairs. Use when asked to explain, compare,
  break down, or teach concepts — or when the user says
  "explain this", "how does X work", "what's the difference between",
  "ELI5", "mental model", "simplify", "walk me through", or "analogy".
---

# Technical Explainer

## Core Method: ACRE

Every explanation follows four moves, in order:

### A — Anchor (Schema Activation)

Connect to something the audience already knows.
Not metaphor for decoration — structural analogy that maps relationships.

Bad: "Redis is like a database"
Good: "Redis is a Post-it note wall. Fast to glance at (O(1) lookup),
limited space (RAM), and you'd never store your tax records
there (no durability guarantees)."

The analogy must be **load-bearing** — it should predict behavior.
"If Post-it notes fall off the wall, your data is gone" → correctly
predicts Redis volatility without persistence config.

### C — Chunk (Cognitive Load Management)

Miller's Law: 7±2 items max per cognitive frame.
Cowan's update: actually 4±1 for novel material.

- If explaining >4 concepts, group them into 2-3 chunks first
- Name each chunk with a concrete noun, not an abstraction
- Present chunks sequentially, never in parallel

Structure hierarchy — use exactly ONE per point:

```
One sentence    → the claim
One paragraph   → the mechanism
One diagram     → the spatial model
One table       → the comparison
```

Never use two of the same level for the same point.

### R — Render (Dual Coding)

Every non-trivial explanation gets a visual companion.
Verbal + spatial encoding = independent memory traces = 2x retention.

MANDATORY visual formats (pick the right one):

| Explaining...         | Use...                    |
| --------------------- | ------------------------- |
| Flow / sequence       | Vertical pipeline diagram |
| Comparison / tradeoff | Side-by-side columns      |
| Hierarchy / taxonomy  | Tree with indentation     |
| Scale / proportion    | Bar chart (block chars)   |
| Relationship / deps   | Arrow graph (A → B → C)   |
| State / lifecycle     | State machine boxes       |

For Unicode building blocks and reusable templates,
see [visual-patterns.md](visual-patterns.md).

### E — Expose the Edges (Contrast Pairs)

Understanding = knowing where the model breaks.

Always include at least one:

- "This is NOT..." (common misconception)
- "This breaks when..." (boundary condition)
- "The tradeoff is..." (what you give up)

The edge case teaches more than the happy path.

---

## Worked Example: Explaining Database Indexes

**A (Anchor):** A database index is a book's index page. Instead of
reading every page to find "clustering", you flip to the back, find
the page number, and go directly there. The tradeoff: the index itself
takes up pages (disk space), and every time you add content, the index
must be updated too.

**C (Chunk):** Two things to understand: how lookups get faster
(B-tree traversal), and what you pay for it (write amplification).

**R (Render):**

```
Full scan:  ████████████████████  O(n)    — reads every row
Index scan: ██░░░░░░░░░░░░░░░░░  O(log n) — binary search
```

**E (Edges):** Indexes are NOT free. Every INSERT now updates both
the table AND the index. A table with 20 indexes and heavy writes
will spend more time maintaining indexes than serving reads.
Over-indexing is as harmful as no indexing.

---

## Compression Principles

### Feynman Gate

Before outputting, ask: "Could a smart person outside this domain
follow this?" If no, you skipped the Anchor step.

### Sentence Density

Every sentence must either:

1. Make a claim
2. Provide evidence for a claim
3. Draw a connection between claims

Sentences that do none of these are filler. Delete them.

### The Curse of Knowledge

You know the implementation. The reader knows the problem.
Bridge from THEIR context (the problem) to YOUR context (the solution),
never the reverse.

Wrong order: "HDBSCAN uses mutual reachability distance to..." (impl first)
Right order: "You need to find natural groups in messy data. HDBSCAN does this by..." (problem first)

---

## Anti-Patterns

- **Jargon without anchoring**: Using a term before connecting it to
  something known
- **Wall of text**: Any explanation >3 paragraphs without a visual
- **Symmetric comparisons**: Tables where everything looks equal —
  always highlight the decisive difference
- **Explaining HOW before WHY**: Mechanism before motivation kills
  attention
- **Flat lists**: >5 bullet points without grouping = cognitive dump,
  not explanation

---

## Self-Check (before outputting)

1. Does the explanation start from the reader's context, not yours? (Feynman Gate)
2. Is there a visual for any non-trivial concept? (Render)
3. Does every analogy predict behavior, not just resemble it? (Anchor)
4. Did you expose at least one edge case or misconception? (Edges)

---

## Model Selection by Audience Signal

| User signal                                | Depth      | Approach                     |
| ------------------------------------------ | ---------- | ---------------------------- |
| "ELI5", "simply", "basically"              | Surface    | One analogy, done            |
| "explain", "how does"                      | Medium     | ACRE full cycle              |
| "compare", "vs", "difference"              | Medium     | Side-by-side + edges         |
| "deep dive", "internals", "under the hood" | Deep       | ACRE + implementation detail |
| "mental model"                             | Structural | Anchor-heavy, diagram-heavy  |

---

## Cognitive Science Foundation

```
A (Anchor)    ← Schema Activation (Bartlett, 1932)
                New info encodes faster when attached to existing frames

C (Chunk)     ← Working Memory Limits (Miller, 1956; Cowan, 2001)
                4±1 chunks for novel material, not 7

R (Render)    ← Dual Coding Theory (Paivio, 1971)
                Verbal + imaginal = independent memory traces

E (Edges)     ← Desirable Difficulty (Bjork, 1994)
                Boundary cases force elaborative processing
```
