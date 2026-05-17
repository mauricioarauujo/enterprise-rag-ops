# SDD — Spec-Driven Development

Optional pre-implementation layer for complex tasks. Produces structured specs before code.

**Use when:** the task touches >2 modules, has multiple plausible designs, or you can't articulate the success criteria yet.
**Skip when:** single-module change, bug fix, or config tweak — go straight to implementation.

## Pipeline

```
/brainstorm → BRAINSTORM_*.md   (approach comparison)
    ↓
/define     → DEFINE_*.md       (requirements + Clarity Score ≥12/15)
    ↓
/design     → DESIGN_*.md       (architecture + file manifest)
    ↓
/implement  → production code
    ↓
complete    → archive/
```

The corresponding slash commands (`/brainstorm`, `/define`, `/design`, `/implement`) are **not yet scaffolded** in this repo. Add them via the Self-Improvement protocol when the first complex task arrives (likely Phase 2 eval harness design).

## Clarity Score Gate (Phase 1 → Phase 2)

5 dimensions scored 0–3 each (min **12/15** to proceed to design):

| Dimension   | Score 0       | Score 3                          |
| ----------- | ------------- | -------------------------------- |
| Problem     | Vague symptom | Root cause with evidence         |
| Users       | Unknown       | Named roles with workflow impact |
| Success     | No criteria   | Measurable, falsifiable          |
| Scope       | Unbounded     | MoSCoW with explicit WON'T list  |
| Constraints | Ignored       | All constraints named            |

## Layout

```
sdd/
├── README.md      ← This file
├── features/      ← Active specs, one folder per feature
│   └── <feature-slug>/
│       ├── BRAINSTORM.md
│       ├── DEFINE.md
│       └── DESIGN.md
└── archive/       ← Completed specs (move feature folder here after ship)
```
