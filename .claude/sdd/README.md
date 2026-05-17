# SDD — Spec-Driven Development

Optional pre-implementation layer for complex work. Produces structured specs before code.

**Use when:** the phase touches >2 modules, has multiple plausible designs, or you can't articulate the success criteria yet.
**Skip when:** single-module change, bug fix, or config tweak — go straight to `/implement`.

## Pipeline

```
/brainstorm sprint-N/<slug>  →  BRAINSTORM.md   (approaches, MoSCoW, research/KB scan)
    ↓
/define     sprint-N/<slug>  →  DEFINE.md       (requirements + Clarity Score ≥12/15)
    ↓
/design     sprint-N/<slug>  →  DESIGN.md       (architecture + file manifest + gaps)
    ↓
/implement  sprint-N/<slug>  →  production code
    ↓
/review     sprint-N/<slug>  →  REVIEW.md       (checks + code review + KB feedback loop)
    ↓
ship                         →  feature folder moves to archive/
```

Each command delegates to a workflow agent: `brainstorm-agent` (sonnet), `define-agent`
(opus), `design-agent` (opus), `code-reviewer` (sonnet for `/review`).

## Clarity Score Gate (Phase 1 → Phase 2)

5 dimensions scored 0–3 each (min **12/15** to proceed to design):

| Dimension   | Score 0       | Score 3                          |
| ----------- | ------------- | -------------------------------- |
| Problem     | Vague symptom | Root cause with evidence         |
| Users       | Unknown       | Named roles with workflow impact |
| Success     | No criteria   | Measurable, falsifiable          |
| Scope       | Unbounded     | MoSCoW with explicit WON'T list  |
| Constraints | Ignored       | All constraints named            |

Below 12, `define-agent` asks clarifying questions and re-scores.

## Layout

Artifacts are keyed on `sprint-N/<phase-slug>` (the project's unit hierarchy —
see `STRUCTURE_GUIDE.md` § Project units).

```
sdd/
├── README.md      ← This file
├── features/      ← Active specs
│   └── sprint-N/
│       └── <phase-slug>/
│           ├── BRAINSTORM.md
│           ├── DEFINE.md
│           ├── DESIGN.md
│           └── REVIEW.md
└── archive/       ← Shipped specs (move the sprint/phase folder here after ship)
```
