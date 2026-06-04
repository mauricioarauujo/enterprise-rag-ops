# SDD — Spec-Driven Development

Structured specs before code. A **sprint** is wrapped by `/sprint-start` and
`/sprint-close`; inside it, each **phase** runs the per-phase SDD pipeline. An SDD
**Stage** is one step of that pipeline — three distinct units, three distinct words.

**Use the per-phase pipeline when:** the phase touches >2 modules, has multiple
plausible designs, or you can't articulate the success criteria yet.
**Skip when:** single-module change, bug fix, or config tweak — go straight to `/implement`.

## Pipeline

```
/sprint-start sprint-N            →  SPRINT.md   (goal, phase breakdown, sprint KB scan)
    │
    │   ┌─ per phase ──────────────────────────────────────────────────────────┐
    └─► │ /brainstorm sprint-N/<phase>  →  BRAINSTORM.md  (approaches, MoSCoW)   │
        │ /define    sprint-N/<phase>  →  DEFINE.md      (requirements + Clarity)│
        │ /design    sprint-N/<phase>  →  DESIGN.md      (architecture + manifest)│
        │ /implement sprint-N/<phase>  →  production code                       │
        │ /review    sprint-N/<phase>  →  REVIEW.md      (checks + KB loop)      │
        └───────────────────────────────────────────────────────────────────────┘
    │
/sprint-close sprint-N            →  retro + knowledge loop + archive sprint-N/
```

The five per-phase commands delegate to a workflow agent: `brainstorm-agent` (sonnet),
`define-agent` (opus), `design-agent` (opus), `code-reviewer` (sonnet for `/review`).
`/sprint-start` and `/sprint-close` run inline — no agent.

`/design` ends with an **automatic consistency self-check** (when the phase is
non-trivial): the design-agent cross-checks DEFINE↔DESIGN against each other and the
"constitution" (CLAUDE.md, ADRs, KB) and records findings in `DESIGN.md` §
Consistency Check. No separate command — the rubric lives in `design-agent.md`.

## Clarity Score Gate (`/define` → `/design`)

`/define` scores 5 dimensions — Problem, Users, Success, Scope, Constraints — 0–3 each;
**12/15 minimum** to proceed to design. Below 12, `define-agent` asks clarifying
questions and re-scores. Full 0/3 rubric: `.claude/agents/define-agent.md` § Step 3
(the SSoT — the agent executes the gate).

## Layout

Phase artifacts are keyed on `sprint-N/<phase-slug>`; `SPRINT.md` sits at the sprint
root (unit hierarchy — see `CLAUDE.md` § Project units).

```
sdd/
├── README.md      ← This file
├── features/      ← Active specs
│   └── sprint-N/
│       ├── SPRINT.md          ← /sprint-start; closed by /sprint-close
│       └── <phase-slug>/
│           ├── BRAINSTORM.md
│           ├── DEFINE.md
│           ├── DESIGN.md
│           └── REVIEW.md
└── archive/       ← /sprint-close moves the whole sprint-N/ folder here
```

## Exemplar phases (start here)

The `archive/` holds 18 shipped phases across 6 sprints. If you're reviewing the method
rather than maintaining it, don't read all of them — read **one** end-to-end, then sample:

- **[`sprint-2/phase-4-perfact-judge`](archive/sprint-2/phase-4-perfact-judge/)** — the core
  eval signal (per-fact LLM-as-judge). Best single walk of `DEFINE → DESIGN → REVIEW`:
  requirements gated, the judge contract designed, then verified.
- **[`sprint-3/phase-8-failure-taxonomy`](archive/sprint-3/phase-8-failure-taxonomy/)** — the
  observability differentiator (rule-based failure classifier). Shows a design with a clean
  diagnostic taxonomy and a real consistency self-check.

Both are linked from the [README guided tour](../../README.md#how-this-was-built).
