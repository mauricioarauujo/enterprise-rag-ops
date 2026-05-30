---
description: Execute implementation by delegating to the Antigravity CLI (agy/Gemini), with Claude reviewing.
---

# /implement-agy {sprint-N/phase-slug}

Same flow as `/implement`, but the **Execute** step is delegated to the Antigravity CLI
(`agy`, which runs Gemini) instead of being done in Claude. This realises the repo's
workflow split — the token-heavy implement stage runs in Antigravity / Gemini against the
`DESIGN.md` contract (AGENTS.md § Implement Contract). Claude stays the orchestrator and the
reviewer. Follows the **`agy` skill** (`.claude/skills/agy/SKILL.md`).

## Arguments

`$ARGUMENTS` — the feature slug `sprint-N/phase-slug`.

## Steps

1. **Read context**
   - `.claude/sdd/features/{slug}/DESIGN.md` (if it exists) — the file manifest + phase order.
   - `.claude/sdd/features/{slug}/DEFINE.md` for acceptance criteria.
   - If no SDD artifacts: read the sprint/phase track directly.

2. **Pre-flight gap check**
   - Scan the manifest for technology areas without KB coverage in `_index.yaml`.
   - Report gaps (missing domain / concept / specialist) and recommend `/new-kb` etc.
   - Report and proceed — do not block.

3. **Confirm the branch & binary**
   - You should be on `sprint-N/phase-slug` (created at `/brainstorm`). If you're on the
     default branch (`main`), create it now — `agy` writes into the working tree.
   - `which agy && agy --version` — confirm the CLI is on PATH (see the `agy` skill, Step 1).

4. **Delegate execute to `agy`** — follow the `agy` skill, Steps 2–3:
   - Build a precise instruction that points `agy` at AGENTS.md § Implement Contract, the
     phase's `DESIGN.md` + `DEFINE.md`, and the relevant KB domain(s).
   - Invoke headless: `agy -p "…" --add-dir "$(pwd)" --yolo --print-timeout 15m`.
   - Tell `agy` to run `make lint test` and **not** to commit — Claude reviews and commits.

5. **Review (stays with Claude)** — `agy` skill, Step 4:
   - Re-run `make lint test` yourself; don't trust `agy`'s report.
   - Check the diff against the manifest (right files, no scope creep) and against the
     `DEFINE.md` acceptance criteria.
   - Verify § Conventions: mirrored test per new module, cassette/replay (no mocked LLM) on
     eval-path code, English.
   - Fix specific defects or re-delegate with a sharper instruction — don't re-implement the
     whole phase by hand.

6. **Commit & report** — commit in Conventional Commits format only after review passes.
   Report files changed, tests passed/failed, and gaps flagged. Suggest next → `/review {slug}`.
