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

5. **Consistency self-check (when applicable)** — for non-trivial phases the agent
   cross-checks DEFINE↔DESIGN and the constitution (AGENTS.md, CLAUDE.md, ADRs, KB) in six passes
   and records a Consistency Check section in `DESIGN.md`. Skipped for single-module
   phases. Rubric: `design-agent.md` § Step 5.

6. **Suggest next step** → `/implement {slug}`. If gaps or drift were found, address
   them first. **Handoff:** the token-heavy implement stage normally runs in
   Antigravity / Gemini — `DESIGN.md` is the cross-tool contract (see § Implement
   Contract in `AGENTS.md`). Make the manifest prescriptive enough that the executor
   needs no extra context.

The phase-ordering convention and the `DESIGN.md` output format are owned by
`.claude/agents/design-agent.md` — this command only delegates.
