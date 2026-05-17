---
description: Close a sprint — verify phases shipped, run the sprint knowledge loop, archive.
---

# /sprint-close {sprint-N}

Close a sprint: confirm every phase shipped, run the sprint-scoped knowledge-feedback
loop, and archive the sprint's SDD artifacts. The sprint-level counterpart of
`/sprint-start`. See `.claude/sdd/README.md`.

## When to use

After the last phase of a sprint has passed `/review`.

## Arguments

`$ARGUMENTS` — the sprint slug `sprint-N`.

## Steps

1. **Read context**
   - `.claude/sdd/features/sprint-N/SPRINT.md` and every phase folder under it.
   - Each phase's `REVIEW.md`.

2. **Phase completion check** — every planned phase has a `REVIEW.md` with a passing
   verdict (✅ READY). List any phase that did not ship; do **not** archive an
   incomplete sprint without confirming with the user.

3. **Sprint knowledge loop** (the aggregate of the per-phase `/review` loop)
   - **Knowledge capture** — collect the Knowledge Capture suggestions from every phase
     `REVIEW.md`, consolidate duplicates, recommend the `/new-kb` / `/update-kb` worth
     doing now.
   - **KB staleness sweep** — across all files the sprint changed, flag KB domains the
     sprint may have left outdated.
   - **ADR sweep** — list architectural decisions made during the sprint not yet
     recorded in `docs/adr/`.

4. **Retrospective** — what worked, what slipped vs the `SPRINT.md` plan, scope changes.

5. **Write output** — append `## Retrospective` + `## Sprint Close` sections to
   `SPRINT.md`; flip its `Status:` to `closed`.

6. **Archive** — move the whole sprint folder:
   `.claude/sdd/features/sprint-N/` → `.claude/sdd/archive/sprint-N/`.

7. **Reminders**
   - Update the private sprint track in the Carreira repo (path in `CLAUDE.local.md`).
   - Run the recommended `/new-kb` / `/update-kb` / ADR work before the next sprint.

## Output

Report: phases shipped vs planned, knowledge-capture actions, stale KB domains, ADRs to
write, archive confirmation.
