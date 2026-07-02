---
description: Validate branch readiness — checks, code review, and the KB knowledge loop.
---

# /review [sprint-N/phase-slug]

Validate branch readiness: mechanical checks, code review, and the knowledge-feedback
loop that keeps the KB in sync with the code. Works before or after a PR exists.

## Tone

Write like a teammate doing a real review — lead with the verdict, list only real
issues, give every issue a `file:line` and a fix.

## Steps

### 1. Gather context

- `git diff origin/main...HEAD` — the full diff. **If that range is empty** (the phase
  reached `/review` before any commit — common in SDD), fall back to the working tree:
  `git diff HEAD` for modified/staged files **plus** the untracked files listed by
  `git status --short` (read each in full). Tell the code-reviewer which scope you used.
- Read every changed file in full.
- Load `DEFINE.md` / `DESIGN.md` from `.claude/sdd/features/{slug}/` if they exist.

### 2. Mechanical checks

```bash
make lint test   # lint + test (formatting is auto-applied by the pre-commit hook)
```

Any failure is blocking. Record results for the report.

### 3. Code review

Invoke the **`code-reviewer`** agent — pass `model: "sonnet"`. It checks RAG-eval
correctness, test coverage, the cassette/replay rule for eval code, and the stranger
test (no personal/career context in tracked files).

### 4. Knowledge-feedback loop

**KB sync is on-branch phase work, not a post-merge chore.** Any KB update or staleness
fix this phase drives is **applied now, on the current branch, and committed with the
phase** — never deferred to "after the PR merges" or punted to `/sprint-close`. The KB
must land in lockstep with the code it documents. Sub-sections below mark each item
**Applied** (done on this branch) vs **Deferred** (with a reason — e.g. needs research,
or is a separate-sprint concern).

**4a. Knowledge capture** — did this work surface knowledge not in any KB (new
technique, library, integration, hard-won operational detail)? If yes, **apply it now**
for an existing domain (invoke `/update-kb {domain}` / the `kb-architect` agent on this
branch); only a brand-new domain (`/new-kb`) may be Deferred if it needs a full 3-pillar
build. Record what you did:

```markdown
## Knowledge Capture

| What was learned | KB domain | Action taken                         |
| ---------------- | --------- | ------------------------------------ |
| {description}    | {domain}  | Applied on branch / Deferred ({why}) |
```

**4b. KB staleness** — map changed files to KB domains via `_index.yaml`. For each
mapped domain, read the relevant concept/pattern and check whether the diff changed an
API, enum, or constraint the KB documents. If stale, **fix it now on this branch** and
record it:

```markdown
## KB Staleness

| KB File | What Changed | Impact   | Action taken                         |
| ------- | ------------ | -------- | ------------------------------------ |
| {file}  | {what}       | {impact} | Applied on branch / Deferred ({why}) |
```

**4c. ADR check** — did this work make an architectural decision not recorded in
`docs/adr/`? If yes, **write the ADR on this branch** (it ships with the phase); Defer
only if the decision is still genuinely open.

Skip any sub-section with nothing to report. After applying, re-stage the KB/ADR/code
edits so they are part of the phase commit.

### 5. Write the report

Save to `.claude/sdd/features/{slug}/REVIEW.md`.

### 6. Hand off

Invoke the **`kbind:handoff`** skill to capture session state and the next action (usually the
next phase, or opening the PR). Skip only if clearly continuing in the same session.

## Output Format

```markdown
# Review: {slug} — {title}

**Branch:** `{branch}` | **Date:** {date} | **Verdict:** {✅ READY | 🟡 ALMOST | 🔴 NOT READY}

## Summary

{2–3 sentences.}

## Mechanical Checks

| Step   | Status | Notes |
| ------ | ------ | ----- |
| Format | PASS   |       |
| Lint   | PASS   |       |
| Tests  | PASS   |       |

## Issues

{One <details> block per issue — ⚠️ non-blocking, 🔴 blocking. file:line + fix.}

## Acceptance Criteria

{Table vs DEFINE.md, if it exists.}

## Knowledge Capture

{Section 4a — Applied/Deferred — or omit.}

## KB Staleness

{Section 4b — Applied/Deferred — or omit.}

## ADR

{Section 4c — or omit.}

## Suggested Next Steps

{What to do after the review. KB/ADR sync is already applied on this branch (Section 4),
so this is usually: commit the phase (code + tests + KB/ADR together) and open the PR.}
```
