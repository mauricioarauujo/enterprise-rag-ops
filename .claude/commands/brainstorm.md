---
description: SDD Stage 0 — explore approaches for a sprint phase before requirements are firm.
---

# /brainstorm {sprint-N/phase-slug}

Collaborative exploration for work with unclear requirements or multiple plausible
designs (SDD Stage 0). See `.claude/sdd/README.md`.

## When to use

Start here when a sprint phase touches >2 modules, has competing designs, or you can't
yet articulate the success criteria. Skip SDD entirely for single-module changes and
config tweaks.

## Arguments

`$ARGUMENTS` — the feature slug `sprint-N/phase-slug` (e.g. `sprint-1/phase-1-data-ingest`).

## Steps

1. **Create the phase branch** — if on the default branch (`main`), create and switch to
   a branch named after the feature slug (`sprint-N/phase-slug`) **before** writing any
   artifacts, so the phase's SDD docs and code land on one branch → one PR. If already on
   the phase branch, continue. (Sprint 1 retro flagged phases built directly on `main`;
   this step prevents that — it is the single canonical branch-creation point of the SDD
   flow.)

2. **Read context**
   - The sprint/phase track in the Carreira repo (path in `CLAUDE.local.md`).
   - `docs/architecture/`, `docs/dataset.md`, relevant `docs/adr/`.
   - `.claude/kb/_index.yaml` — existing KB domains.

3. **Start-of-phase research & KB scan** (this is the O4 gate)
   - From the phase's topics, list which KB domains are needed.
   - For each: missing entirely, exists but thin, or sufficient.
   - Emit a **Suggested research & KB work** block: which `/new-kb` / `/update-kb` to
     run, and whether any topic is complex enough to warrant `--deep-research`.

4. **Invoke `brainstorm-agent`** — pass `model: "sonnet"`.
   - Explores 2–3 approaches with trade-offs, MoSCoW scope, open questions.

5. **Write output** → `.claude/sdd/features/{slug}/BRAINSTORM.md`.

6. **Suggest next step** → `/define {slug}` (after any KB work flagged in step 3).
