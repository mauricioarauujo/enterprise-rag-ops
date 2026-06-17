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

3. **Sprint knowledge loop** (backstop for the per-phase `/review` loop — most KB/ADR
   work is already applied on each phase branch; this catches only what slipped through)
   - **Knowledge capture** — collect the Knowledge Capture entries from every phase
     `REVIEW.md`; for any marked **Deferred**, apply the `/new-kb` / `/update-kb` now.
   - **KB staleness sweep** — across all files the sprint changed, flag (and fix) any KB
     domain a phase left outdated despite its `/review`.
   - **ADR sweep** — list architectural decisions made during the sprint not yet
     recorded in `docs/adr/`.

4. **Backlog harvest** — reconcile `docs/planning/backlog/index.md` with what the sprint did:
   - **Capture** new ideas / deferred work surfaced in the phase `REVIEW.md` files (and the
     retro) as new `B-NN-<slug>.md` items (Status `idea`), and add an index row each.
   - **Close** any backlog item the sprint completed: flip Status → `done` and move its row to
     the index's _Recently shipped_ table.

5. **Retrospective** — what worked, what slipped vs the `SPRINT.md` plan, scope changes.

6. **Write output** — append `## Retrospective` + `## Sprint Close` sections to
   `SPRINT.md`; flip its `Status:` to `closed`.

7. **Archive** — move the whole sprint folder:
   `.claude/sdd/features/sprint-N/` → `.claude/sdd/archive/sprint-N/`.

8. **Reminders**
   - Update the private sprint track in the Carreira repo (path in `CLAUDE.local.md`).
   - Run any **Deferred** `/new-kb` / `/update-kb` / ADR work before the next sprint
     (per-phase items already landed on their branches).

9. **Hand off** — invoke the **`handoff`** skill to capture the sprint outcome and the
   entry point for the next sprint (the recommended KB/ADR work + the next sprint to open).

## Output

Report: phases shipped vs planned, knowledge-capture actions, stale KB domains, ADRs to
write, backlog items harvested/closed, archive confirmation.
