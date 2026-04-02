# draft_answer() Prompt Separation — Design Spec

## Problem

`draft_answer()` in `composite_tools.py:616-683` has a monolithic prompt string that mixes voice/tone, length rules, structural guidance, and output format template. The same voice rules are duplicated in the revision prompts (lines 765-773, 786-809). None of this is overridable per deployment — it's hardcoded in Python.

## Design

Separate the synthesis prompt into two prompt layer files, loaded at call time. Three consumers (synthesis, cosmetic revision, substantive revision) share the same sources.

### New Files

**`rlm_search/prompt_layers/_voice.md`**

Editorial policy — *how* to write across all sections. Shared by synthesis and revision prompts.

Contents (extracted from current lines 627-643):
- Tone: declarative rulings, no hedging ("The ruling is..." not "It may be...")
- Framing: voice of I.M.A.M. scholarly corpus, not AI's own analysis
- Language: clear English, define Arabic/fiqhi terms parenthetically on first use
- Scope: present rulings as stated in sources, no external positions
- Opening: start directly with the ruling, no preamble

**`rlm_search/prompt_layers/_answer_format.md`**

Output shape — *what* the user sees. Section definitions, length budgets, citation style, spacing.

Contents (extracted from current lines 644-683):

```
FORMAT:

## Answer
Grounded answer with [Source: <id>] citations after each claim.

Use paragraph breaks between distinct conditions or aspects of the ruling.
Bold key rulings and important distinctions for scannability.

Length by complexity:
- Single ruling: 150-250 words
- Ruling with conditions/exceptions: 300-450 words
- Multi-part or complex fiqhi question: up to 600 words
- Never pad with summary paragraphs that restate the opening ruling

## Sources Consulted
One line per source cited: [Source: id] — original question topic in 5-8 words.
No paraphrase of rulings — the ruling is already in ## Answer.

## Confidence Assessment
- **High**: 3+ scholar answers consistently agree on the ruling.
- **Medium**: 1-2 sources directly address the question.
- **Low**: No direct match; answer extrapolated from related rulings.
Note which aspects have direct corpus coverage vs. extrapolation.

Only cite IDs from the evidence. Flag gaps explicitly.
```

Structure guidance (extracted from lines 651-658):
- Lead with the direct ruling
- Follow with conditions, exceptions, practical guidance
- Consensus: state once with all citations
- Different conditions: organize by condition
- Double-space between sections, new paragraphs for distinct topics

### Loading Mechanism

Use `prompt_loader.load_preamble()` pattern — same as `_preamble.md`. Both files use underscore prefix (excluded from system prompt assembly). Both support `PROMPT_LAYERS_DIR` override.

Add to `prompt_loader.py`:
```python
def load_layer_file(name: str, layers_dir=None, override_dir=None) -> str:
    """Load a single named layer file. Override dir checked first."""
```

### Consumer Changes

**Synthesis prompt** (`composite_tools.py:616-683`):
- Replace hardcoded voice block with `load_layer_file("_voice.md")` content
- Replace hardcoded format block with `load_layer_file("_answer_format.md")` content
- Keep dynamic parts inline: `DOMAIN_PREAMBLE`, `must_cite`, question, evidence, instructions

**Cosmetic revision prompt** (lines 765-773):
- Load `_voice.md` instead of "Fix ONLY the following voice/structure issues"
- Reference format: "Return ONLY the fixed answer. Preserve the original format."

**Substantive revision prompt** (lines 786-809):
- Load `_voice.md` instead of inline compressed voice copy (lines 797-803)
- Load `_answer_format.md` for format reference instead of "Start directly with ## Answer"
- Keep critique, completeness detail, evidence inline (dynamic)

### Caching

Layer files loaded once at module level (same as `DOMAIN_PREAMBLE`):
```python
_VOICE = load_layer_file("_voice.md")
_ANSWER_FORMAT = load_layer_file("_answer_format.md")
```

No per-call disk reads. Restart to pick up changes (consistent with existing behavior).

### What Doesn't Change

- `draft_answer()` function signature
- Return value shape (`{"answer", "critique", "passed", "revised"}`)
- Critique tier logic (strong/medium/weak)
- `_verify_citations()` behavior
- `build_must_cite_brief()` behavior
- System prompt layers (20-tools.md etc.)
- Test interfaces

### Spacing Rules (in `_answer_format.md`)

- Double newline (`\n\n`) between `## Answer`, `## Sources Consulted`, `## Confidence Assessment`
- New paragraph for each distinct condition or aspect within `## Answer`
- Bold (`**...**`) for key rulings and important distinctions
- Single newline between source lines in `## Sources Consulted`

## Testing

- Existing `draft_answer` tests continue to pass (format unchanged)
- New test: `_voice.md` and `_answer_format.md` load correctly
- New test: `PROMPT_LAYERS_DIR` override works for both files
- New test: synthesis prompt contains voice + format content
