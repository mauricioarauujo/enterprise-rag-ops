# KB Research — Deep Research landing zone

Pillar 3 of the KB build model (see `.claude/STRUCTURE_GUIDE.md` § Knowledge Base).
Used for **complex** topics where the codebase (pillar 1) and MCP docs/patterns
(pillar 2, Context7 + Exa) are not enough on their own.

## Directories

| Path       | Tracked? | Holds                                                   |
| ---------- | -------- | ------------------------------------------------------- |
| `inbox/`   | no       | Raw Gemini Deep Research output, dropped in by the user |
| `archive/` | yes      | Research files already consumed into a KB — provenance  |

## Flow

```
1. /new-kb <domain> --deep-research
      Claude drafts a scoped Gemini Deep Research PROMPT.
2. User runs the prompt in Gemini → Gemini returns a research PLAN.
3. User pastes the plan back → Claude reviews it and returns feedback
      (gaps, scope creep, missing angles, suggested edits).
4. User runs the approved research → drops the output file here:
      .claude/kb/_research/inbox/<domain>-<YYYY-MM-DD>.md
5. kb-architect builds/updates the KB domain(s): the research feeds pillar 3,
      cross-checked against the codebase (pillar 1) and Context7/Exa (pillar 2).
      Output: concepts/ + patterns/, each tagged with agreement-analysis confidence.
6. Claude moves the source file: inbox/ → archive/.
7. Domain(s) registered in _index.yaml + the STRUCTURE_GUIDE KB registry.
```

## Drafting the prompt (step 1)

Every Gemini Deep Research prompt **must end with an explicit output directive**:

> Render every numeric value, parameter, threshold, and formula as plain Markdown
> text (or a Markdown table) — never as an inline image, equation object, or
> rendered graphic. Use plain ASCII for math (e.g. `k = 60`, `L = mu - 3*sigma`).

Gemini renders some numerics and formulae as inline images in its UI. Those images
are **silently dropped** when the report is exported to Markdown — they arrive as
broken `![][image]` refs, so the KB loses exactly the concrete values it needs.
The output directive prevents this at the source; do not rely on also exporting a
PDF to recover them after the fact.

## Naming

- Inbox file: `<domain>-<YYYY-MM-DD>.md` (e.g. `rag-eval-harness-2026-05-20.md`).
- One research file may feed **more than one** KB domain — that is fine.
- After consumption the file keeps its name in `archive/` for provenance.

## When NOT to use this

If Context7 + Exa + a codebase grep already answer the question, skip Deep Research —
`/new-kb <domain>` (no flag) handles it. Reserve pillar 3 for genuinely complex
synthesis (methodology surveys, design-space comparisons, unfamiliar subfields).
