---
name: handoff
description: >-
  This skill should be used when ending a working session or compacting context in
  enterprise-rag-ops — e.g. the user says "hand off", "create a handoff", "wrap up the
  session", "I'm out of context", "summarize this session for next time", or before
  running /clear with work unfinished. Produces a structured, terse handoff (state +
  exact next action) so the next session or agent resumes without re-deriving context.
  Adapted from mattpocock/skills `handoff` (MIT).
---

# Handoff — compact a session for the next one

Produce a structured handoff so the next session (or agent) resumes cold without
re-deriving context. Capture _state and the next action_, not a transcript.

## When to use

At the end of a working session, before `/clear`, or when context is about to
compact and work is unfinished. Also invoked automatically as the final step of
`/review` (phase boundary) and `/sprint-close` (sprint boundary).

## Steps

1. Determine the current sprint/phase and SDD stage from the branch name and
   `.claude/sdd/features/`.
2. Create `docs/planning/handoffs/` if absent (`mkdir -p`) — it is a gitignored
   working-notes zone (see CLAUDE.local.md).
3. Write `docs/planning/handoffs/<YYYY-MM-DDTHHMM>.md` with the sections below, each
   kept terse.
4. Report the path and the single next action to the user.

## Handoff contents

- **Phase & stage** — `sprint-N/phase-slug`, which SDD stage, branch.
- **Done this session** — bullets, each naming the artifact or file touched.
- **In flight** — what is half-done, and the _exact_ next action to take.
- **Decisions** — each choice with a one-line rationale, so it is not relitigated.
- **Open questions** — anything blocked on the user.
- **Validation state** — what passed (`make verify`, `uv run pytest -k …`) and what
  is still pending.
- **Pointers** — relevant SDD artifacts, changed files, the mapped KB domain.

## Rules

- Summarize, do not transcribe — the next reader wants state plus the next move.
- Apply the stranger test even here: keep the file about the _work_, not personal or
  career context, despite the directory being gitignored.
- Do not duplicate durable facts that belong in memory
  (`~/.claude/projects/.../memory/`) or a KB — link to them instead.
