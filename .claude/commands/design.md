---
description: SDD Stage 2 — produce the architecture and file manifest.
---

# /design {sprint-N/phase-slug}

Create the technical architecture and file manifest (SDD Stage 2).
See `.claude/sdd/README.md`.

## Arguments

`$ARGUMENTS` — the feature slug `sprint-N/phase-slug`.

## Steps

1. **Read context**
   - `.claude/sdd/features/{slug}/DEFINE.md`.
   - Relevant KB domains and existing code in the affected modules.

2. **Invoke `design-agent`** — pass `model: "opus"`.
   - Maps requirements to modules across `src/` / `eval/` / `observability/`.
   - Produces a file manifest: every file → the specialist agent that owns it, or
     "direct" if no specialist exists yet.
   - Plans implementation phase ordering.

3. **Write output** → `.claude/sdd/features/{slug}/DESIGN.md`.

4. **Gap detection (deep)** — the agent runs the three-layer infrastructure-gap check
   (domain existence, concept coverage, agent alignment) and reports it as an
   Infrastructure Gaps table in `DESIGN.md`. Rubric + table format: `design-agent.md`.

5. **Suggest next step** → `/implement {slug}`. If gaps were found, address them first.

The phase-ordering convention and the `DESIGN.md` output format are owned by
`.claude/agents/design-agent.md` — this command only delegates.
