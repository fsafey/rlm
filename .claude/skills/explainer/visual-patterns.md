# Visual Patterns Reference

Reusable Unicode/ASCII building blocks for the Render step.
Pick the pattern that matches the concept type, then adapt.

---

## 1. Pipeline / Flow

Use for: sequential processes, data flow, request lifecycle.

```
Input
  │
  ▼
┌──────────┐
│ Stage 1  │  annotation
└────┬─────┘
     ▼
┌──────────┐
│ Stage 2  │  annotation
└────┬─────┘
     ▼
  Output
```

Branching variant:

```
     Input
       │
       ▼
   ┌───┴───┐
   ▼       ▼
┌─────┐ ┌─────┐
│  A  │ │  B  │
└──┬──┘ └──┬──┘
   └───┬───┘
       ▼
    Merged
```

---

## 2. Side-by-Side Comparison

Use for: tradeoffs, alternatives, before/after.

```
    Option A                          Option B

┌──────────────────┐          ┌──────────────────┐
│ characteristic   │          │ characteristic   │
│ characteristic   │          │ characteristic   │
│ characteristic   │          │ characteristic   │
└──────────────────┘          └──────────────────┘
   ▲ decisive difference         ▲ decisive difference
```

Always call out the deciding factor below each column.

---

## 3. Bar / Scale Chart

Use for: proportions, distributions, relative size.

```
Category A  ████████████████████  85%
Category B  ███████████░░░░░░░░░  55%
Category C  █████░░░░░░░░░░░░░░░  25%
Category D  ██░░░░░░░░░░░░░░░░░░  10%
```

Characters: `█` filled, `░` empty, `▓` partial/in-progress.

---

## 4. Tree / Hierarchy

Use for: taxonomy, file structure, inheritance, containment.

```
Root
├── Branch A
│   ├── Leaf 1
│   └── Leaf 2
├── Branch B
│   ├── Leaf 3
│   └── Leaf 4
└── Branch C
    └── Leaf 5
```

Characters: `├──` sibling, `└──` last child, `│` continuation.

---

## 5. State Machine

Use for: lifecycle, status transitions, finite states.

```
┌─────────┐    event    ┌─────────┐    event    ┌─────────┐
│  State A │───────────▶│  State B │───────────▶│  State C │
└─────────┘             └────┬────┘             └─────────┘
                             │ error
                             ▼
                        ┌─────────┐
                        │  Failed │
                        └─────────┘
```

---

## 6. Dependency / Relationship Graph

Use for: service dependencies, data flow between components.

```
┌───────┐         ┌───────┐
│   A   │────────▶│   B   │
└───┬───┘         └───┬───┘
    │                 │
    ▼                 ▼
┌───────┐         ┌───────┐
│   C   │◀────────│   D   │
└───────┘         └───────┘
```

Arrow types: `──▶` depends on, `──▷` optional, `◀──▶` bidirectional.

---

## 7. Timeline / Sequence

Use for: event ordering, request-response, protocol exchanges.

```
Client              Server              Database
  │                   │                    │
  │── GET /api ──────▶│                    │
  │                   │── SELECT ─────────▶│
  │                   │◀── rows ──────────│
  │◀── 200 JSON ─────│                    │
  │                   │                    │
```

---

## 8. Containment / Layer Diagram

Use for: architecture layers, nesting, scope boundaries.

```
┌─────────────────────────────────────┐
│  Outer Layer                        │
│  ┌─────────────────────────────┐    │
│  │  Middle Layer               │    │
│  │  ┌─────────────────────┐    │    │
│  │  │  Inner Layer        │    │    │
│  │  └─────────────────────┘    │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

---

## Box-Drawing Character Reference

```
Corners:  ┌ ┐ └ ┘
Lines:    │ ─
Joins:    ├ ┤ ┬ ┴ ┼
Arrows:   → ← ↑ ↓ ▶ ◀ ▲ ▼ ──▶ ◀──
Bullets:  • ◦ ▪ ▫
Bars:     █ ▓ ░
Checks:   ✓ ✗
Dividers: ─── ═══ ··· ┄┄┄
```

---

## Composition Rules

1. **One diagram per concept** — don't overload a single visual
2. **Label everything** — unlabeled boxes are cognitive debt
3. **Left-to-right or top-to-bottom** — never bottom-to-top
4. **Max width: 70 chars** — fits terminals and markdown renderers
5. **Whitespace is structure** — use alignment to show relationships
6. **Annotate beside, not inside** — keep boxes clean, put details to the right
