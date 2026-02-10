# RLM Search App

Agentic search UI for querying Islamic jurisprudence collections via [Recursive Language Models](../README.md). Vite + React 19 + Tailwind CSS v4 + shadcn/ui components.

## Architecture

```
search-app/          Vite frontend (port 3002)
  src/
    App.tsx              Root layout, state wiring
    index.css            Tailwind v4 theme (oklch, @theme inline)
    lib/
      types.ts           SSE event types, RLMChatCompletion, utility fns
      useSearch.ts       SSE streaming hook
      utils.ts           cn() helper (clsx + tailwind-merge)
      parseCitations.ts  Citation extraction
    components/
      SearchInput.tsx       Query bar + model/iteration settings
      SearchProgress.tsx    Phase-aware loading indicator
      AnswerPanel.tsx       Markdown-rendered answer with citation count
      SourceCards.tsx       Grid of retrieved source documents
      TracePanel.tsx        Orchestrator: timeline + execution detail
      IterationTimeline.tsx Horizontal scrollable iteration cards
      ExecutionPanel.tsx    Tabbed code execution + sub-LM call inspector
      CodeBlock.tsx         Collapsible code block with stdout/stderr/locals
      CodeWithLineNumbers.tsx  Two-column line number + code layout
      SyntaxHighlight.tsx   Regex-based Python syntax highlighter (zero deps)
      ui/                   shadcn/ui primitives (badge, button, card, collapsible, scroll-area, tabs)
```

### Data Flow

```
POST /api/search → search_id
GET  /api/search/{id}/stream → SSE events

useSearch() hook
  ├── metadata event  → SearchInput badges (model, max iterations)
  ├── iteration events → TracePanel
  │     ├── IterationTimeline (horizontal cards, clickable)
  │     └── ExecutionPanel (selected iteration detail)
  │           ├── Code Execution tab (CodeBlock → CodeWithLineNumbers → SyntaxHighlight)
  │           └── Sub-LM Calls tab (collapsible prompt/response pairs)
  ├── done event → AnswerPanel + SourceCards
  └── error event → error banner
```

### Visualization Components

Ported from the [visualizer](../visualizer/) (Next.js trajectory viewer) with these adaptations:

| Component | What it shows |
|-----------|--------------|
| **IterationTimeline** | Horizontal scrollable row of iteration cards. Each card shows iteration number, badge indicators (FINAL/ERR), code block count, sub-LM call count, execution time, response preview, and estimated output tokens. Auto-scrolls to selected card. |
| **ExecutionPanel** | Two-tab layout for a selected iteration. "Code Execution" tab renders each code block with syntax-highlighted Python, stdout, stderr, and local variables. "Sub-LM Calls" tab shows collapsible prompt/response pairs with token counts and execution time per call. |
| **CodeBlock** | Collapsible card per code block. Color-coded border (green = success, red = error). Sections: Python code with line numbers, stdout, stderr, variables grid, and nested sub-LM call inspection. |
| **SyntaxHighlight** | Custom regex-based Python highlighter. Handles keywords, builtins, strings (including f-strings and triple-quoted), numbers, function calls, operators, and comments. Zero external dependencies. |

Key differences from the visualizer port:
- Stripped `'use client'` directives (Vite, not Next.js)
- Uses search-app's `Iteration` type instead of visualizer's `RLMIteration` (no `prompt` field — input token estimation dropped)
- `rlm_calls` typed as `RLMChatCompletion[]` instead of `unknown[]`
- TracePanel auto-selects latest iteration during live search

### Theme System

Tailwind CSS v4 with oklch color space. The `@theme inline` block in `index.css` maps semantic tokens (`--color-background`, `--color-primary`, etc.) to CSS custom properties, enabling direct utility usage (`bg-background`, `text-muted-foreground`) instead of the previous `hsl(var(--...))` pattern.

Light and dark themes use a green-tinted oklch palette matching the visualizer.

## Quick Start

```bash
# Install dependencies
npm install

# Development server (port 3002, proxies /api/* → localhost:8092)
npm run dev

# Production build
npm run build

# Preview production build
npm run preview
```

### Prerequisites

The backend must be running for the UI to function:

```bash
# From project root
uv pip install fastapi uvicorn httpx
make backend    # Starts search API on port 8092
```

The search API requires a reachable Cascade instance (default: `https://cascade.vworksflow.com`) and an `ANTHROPIC_API_KEY` environment variable.

## Dependencies

| Package | Purpose |
|---------|---------|
| `react` / `react-dom` | UI framework (v19) |
| `tailwindcss` / `@tailwindcss/vite` | Styling (v4) |
| `class-variance-authority` | Component variant system (shadcn/ui) |
| `clsx` + `tailwind-merge` | Conditional class merging |
| `@radix-ui/react-*` | Accessible primitives (collapsible, scroll-area, slot, tabs) |
| `lucide-react` | Icons |
| `react-markdown` | Answer rendering |
