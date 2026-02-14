# Multi-Turn Frontend Refactor — Verification Handoff

**Commit**: `3b1f899` on `main`
**Scope**: 27 files, 5-stage frontend refactor + backend pre-classification move

## What Changed

- `SearchProgress.tsx` split — activity detection logic → `lib/activityDetection.ts`
- Sub-LM call rendering deduplicated → `SubLMCallCard.tsx`
- Settings panel extracted → `SearchSettingsPanel.tsx`
- `useState` → `useReducer` in `useSearch.ts`, new `searchReducer.ts` (14 action types)
- `ConversationTurn` enriched with full turn state (iterations, metadata, error, etc.)
- `ConversationHistory.tsx` upgraded — expandable turns reuse `AnswerPanel`/`SourceCards`/`TracePanel`
- Citations activated — `injectCitationLinks()` replaces dead `renderCitations()`
- Scroll fix — `setTimeout` → `requestAnimationFrame` in `App.tsx`
- `.gitignore` — added `!search-app/src/lib/` negation

## Verification Checklist

- [ ] SearchProgress renders identically during live search (labels, confidence ring, sub-agent steps)
- [ ] Sub-LM cards render in both Code Execution and Sub-LM Calls tabs
- [ ] Settings panel — all 7 controls work, values persist across searches
- [ ] Input clears after submit
- [ ] Multi-turn: 2+ searches → previous turns show collapsed with snippet, source count, exec time
- [ ] Expand previous turn → Answer/Sources/Trace panels render with full data
- [ ] Error turn in history — red badge, expandable error message
- [ ] Citations — `[Source: id]` renders as clickable footnote linking to source card
- [ ] Log loading — click recent search, full state populates
- [ ] Cancel — state resets, history preserved
- [ ] New Session — conversation history clears
- [ ] Scroll-to-answer fires reliably on completion
- [ ] `cd search-app && npx tsc --noEmit` — clean
- [ ] `cd search-app && npx vite build` — clean
- [ ] `uv run pytest tests/test_search_api.py tests/test_repl_tools.py` — all pass
