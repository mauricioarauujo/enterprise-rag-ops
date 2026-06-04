---
name: agy
description: >-
  Delegate the token-heavy implement stage (and other mechanical, bulky grunt work) to the
  Antigravity CLI (`agy`, which runs Gemini) instead of spending Claude tokens on it. The
  canonical use is running a phase's `/implement` against its `DESIGN.md` contract — see
  AGENTS.md § Implement Contract, which already routes implement to Antigravity / Gemini.
  Also covers bulk file conversion, reformatting, or large-but-routine transforms. Trigger
  when the user says "use agy", "delegate to agy", "implement with agy", "run implement in
  Antigravity/Gemini", or "don't burn Claude tokens on this". Claude stays the orchestrator
  and reviewer; `agy` does the heavy lifting.
compatibility: Requires the `agy` binary on PATH (Antigravity CLI). Run `which agy` to confirm.
---

# agy — delegate grunt work, stay the orchestrator

## The principle

Claude (Opus/Sonnet) tokens are best spent on **planning, review, and judgment**: the SDD
stages (`/brainstorm → /define → /design`), code review, and **judging** whether an output is
correct. `agy` runs Gemini and is cheap — push **token-heavy, mechanical** work to it.

This repo's workflow split already says so: planning and review run in Claude Code; the
token-heavy **implement** stage runs in **Antigravity / Gemini** against the `DESIGN.md`
contract (AGENTS.md § Implement Contract). `agy` is the binary that drives that handoff
headlessly, so you don't have to switch tools by hand.

| Do in Claude (orchestrate + judge)              | Delegate to `agy` (execute)                  |
| ----------------------------------------------- | -------------------------------------------- |
| `/brainstorm`, `/define`, `/design`, `/review`  | `/implement` a phase against its `DESIGN.md` |
| Code review; judge an `agy` output for fidelity | Bulk file conversion / reformatting          |
| Anything that shapes the design or acceptance   | Mechanical, repetitive, low-judgment passes  |

When delegating, **act only as the orchestrator**: prepare a precise instruction, hand it to
`agy`, then review the result. Do not re-do the work yourself.

## Step 1 — locate the binary

`agy` may live at a different path per machine. Resolve it first:

```bash
which agy        # -> use this path to invoke
agy --version    # confirm it runs
pwd              # confirm you are at the repo root (so agy's workspace is correct)
```

Expect the harness's auto-mode classifier to block `--dangerously-skip-permissions`
(Step 2) until an explicit allowlist entry exists. Add this once per clone to
`.claude/settings.local.json` (gitignored) — `Bash(agy -p *)` alone is not enough:

```json
"Bash(agy -p * --dangerously-skip-permissions *)"
```

## Step 2 — invoke non-interactively

`agy` has a headless/print mode (it behaves much like Claude Code):

```bash
agy -p "<the task instruction>" \
  --add-dir "$(pwd)" \
  --dangerously-skip-permissions \
  --print-timeout 15m
```

- `-p` / `--print` / `--prompt` — run a single prompt non-interactively and print the result.
- `--add-dir "$(pwd)"` — give `agy` the repo as its workspace so it can read/write files.
- `--dangerously-skip-permissions` — let `agy` perform file writes unattended (auto-approve
  its tool permission requests). In `-p` mode there is no TTY for `agy` to prompt on, so this
  is what makes the handoff truly headless. Scope the task tightly (specific contract +
  paths) so this stays safe; add `--sandbox` to restrict the terminal if you want a tighter
  blast radius. This is the deliberate trade-off — the safety net is Step 4 (Claude reviews
  every change). (Older `agy` versions exposed this as `--yolo`; v1.0.2+ uses the explicit
  name.)
- `--print-timeout` — raise it for long implement runs (default 5m); implement is multi-file.
  Because this can exceed Claude Code's foreground Bash cap (10m), invoke `agy` with
  `run_in_background: true` so the harness re-invokes you when it exits, rather than the
  Bash tool timing out mid-run.

## Step 3 — the canonical delegation: implement a phase

Hand `agy` the SDD contract and let it implement. The instruction must point it at the
Implement Contract and the phase artifacts so it follows the same rules Claude would:

```bash
agy -p "Implement the phase sprint-N/phase-slug. Follow AGENTS.md section 'Implement \
Contract' exactly: read .claude/sdd/features/sprint-N/phase-slug/DESIGN.md (file manifest + \
phase order) and DEFINE.md (acceptance criteria), then read the relevant KB domain(s) under \
.claude/kb/. Implement following the manifest's phase order; honour Engineering Behavior and \
Conventions. Every new module gets a mirrored tests/test_<module>.py. Eval-path code uses the \
cassette/replay pattern — never a mocked LLM API. Then run 'make lint test' and report files \
changed, tests pass/fail, and any infra/KB gaps. Do NOT commit — Claude reviews and commits." \
  --add-dir "$(pwd)" --dangerously-skip-permissions --print-timeout 15m
```

Confirm the branch (`sprint-N/phase-slug`) **before** delegating — `agy` writes into the
working tree, so you want it on the phase branch, not `main`.

## Step 4 — review (this stays with Claude)

After `agy` finishes, **Claude reviews** — don't trust blindly. This is the part that
protects quality, so spend the tokens here:

- Re-run the gate yourself: `make lint test`. Don't take `agy`'s word that it passed.
- Check the diff against the `DESIGN.md` manifest (right files, no scope creep) and against
  `DEFINE.md` acceptance criteria.
- Verify Conventions held: mirrored test per new module, cassette/replay (no mocked LLM)
  on eval-path code, Conventional Commits, English.
- If something is wrong, fix the specific defect or re-delegate with a sharper instruction —
  don't silently re-implement the whole phase.
- Commit (Conventional Commits) only after review passes. Suggest next step → `/review {slug}`.

## Research / web-search mode — disable Claude Code auto mode FIRST

`agy` (Gemini) can also do **web search / research**, but the rules are the **opposite** of the
implement flow above:

- **Before delegating any research/web-search task to `agy`, remind the user to turn OFF
  Claude Code "auto mode" first — and wait for confirmation before invoking.** With auto mode
  on, `agy` runs autonomously and **ignores the research prompt entirely**: asked for a
  literature survey (sprint-7 phase-1), it instead modified production files, wrote an ADR
  marked "accepted" with non-reconciling numbers, and ran the test suite — all reverted.
- **Do NOT pass `--dangerously-skip-permissions` for research.** That flag is exactly what
  lets `agy` go autonomous and implement instead of research.
- If auto mode can't be disabled, **fall back to parallel Sonnet sub-agents** here in Claude
  Code (the Agent tool, `model: sonnet`) — that fallback delivered 6 cited micro-researches in
  ~3 min when `agy` went rogue.

`agy` is fundamentally an autonomous **implementer**; research is the off-label use that needs
this guard. (Project memory: `agy-research-needs-auto-mode-off`.)

## When NOT to delegate

Keep in Claude: the SDD planning stages, code review, and the judgment in Step 4. Delegation
is for volume and mechanical execution, not for decisions or for anything that shapes the
design or the acceptance criteria.
