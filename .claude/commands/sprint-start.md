---
description: Open a sprint — distil a high-level plan and the sprint-wide KB/research scan.
---

# /sprint-start {sprint-N}

Open a sprint: turn the private sprint track into a public, system-level plan and scan
the KB/research work the whole sprint will need. Sits one level **above** the per-phase
SDD pipeline (`/brainstorm → … → /review`). See `.claude/sdd/README.md`.

## When to use

At the start of every sprint, before any `/brainstorm`. Produces the high-level "what"
so each phase can later refine the "how".

## Arguments

`$ARGUMENTS` — the sprint slug `sprint-N` (e.g. `sprint-1`).

## Steps

1. **Read context**
   - The sprint track in the Carreira repo (path in `CLAUDE.local.md`) — the private SSoT.
   - `docs/architecture/`, `docs/dataset.md`, relevant `docs/adr/`.
   - `.claude/kb/_index.yaml` — existing KB domains.
   - The previous sprint's `SPRINT.md` in `.claude/sdd/archive/`, if any.

2. **Distil the sprint goal** — the high-level problem the sprint solves, in 2–3
   sentences. System-level only.

3. **Break into phases** — ~3 phases (4–5 if complex), each with a one-line intent and
   a `phase-M-<slug>`. This is the planned breakdown, not a contract — phases refine on
   `/brainstorm`.

4. **Sprint-wide research & KB scan** (the sprint half of decision O4) — across all
   phases, classify each KB domain the sprint will touch: missing / thin / sufficient.
   Flag which need `/new-kb`, `/update-kb`, or `--deep-research`, and when in the sprint.

5. **Write output** → `.claude/sdd/features/sprint-N/SPRINT.md`.

6. **Stranger test** — `SPRINT.md` is git-tracked. It carries only system content: no
   budget, no career framing, no Carreira-repo references.

7. **Suggest next step** → `/brainstorm sprint-N/phase-1-<slug>`.

## Output

`SPRINT.md` shape:

```markdown
# SPRINT N: {Title}

**Sprint:** sprint-N | **Date:** {date} | **Status:** active

## Goal

{2–3 sentences — the high-level "what".}

## Phase Breakdown

| Phase | Intent | Slug        |
| ----- | ------ | ----------- |
| 1     | …      | `phase-1-…` |

## Sprint-Wide KB & Research

{Per domain: missing/thin/sufficient → action + timing. Or "None — coverage holds."}

## Success Criteria

{Measurable, sprint-level.}

## Risks

{What could derail the sprint.}
```

Report: sprint goal, phase count, KB/research actions flagged.
