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

- `git diff origin/main...HEAD` — the full diff.
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

**4a. Knowledge capture** — did this work surface knowledge not in any KB (new
technique, library, integration, hard-won operational detail)? If yes:

```markdown
## Knowledge Capture Suggestions

| What was learned | Suggested KB domain | Action                            |
| ---------------- | ------------------- | --------------------------------- |
| {description}    | {domain}            | `/new-kb {domain}` / `/update-kb` |
```

**4b. KB staleness** — map changed files to KB domains via `_index.yaml`. For each
mapped domain, read the relevant concept/pattern and check whether the diff changed an
API, enum, or constraint the KB documents. If stale:

```markdown
## KB Staleness

| KB File | What Changed | Impact | Action |
| ------- | ------------ | ------ | ------ |
```

**4c. ADR check** — did this work make an architectural decision not recorded in
`docs/adr/`? If yes, recommend writing the ADR.

Skip any sub-section with nothing to report.

### 5. Write the report

Save to `.claude/sdd/features/{slug}/REVIEW.md`.

### 6. Hand off

Invoke the **`handoff`** skill to capture session state and the next action (usually the
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

## Knowledge Capture Suggestions

{Section 4a — or omit.}

## KB Staleness

{Section 4b — or omit.}

## ADR

{Section 4c — or omit.}

## Suggested Next Steps

{What to do after the review.}
```
