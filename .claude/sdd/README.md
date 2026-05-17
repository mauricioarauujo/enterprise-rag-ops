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
