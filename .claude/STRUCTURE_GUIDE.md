# STRUCTURE_GUIDE.md — enterprise-rag-ops

Maintenance guide for the `.claude/` orchestration layer. Read this before adding
agents, commands, KB domains, skills, or hooks.

This guide is **not** auto-loaded each turn (only `CLAUDE.md` is) — so editing it does
**not** invalidate the prompt cache. The growing registries therefore live **here**,
and `CLAUDE.md` only points to them.

---

## Layout

```
.claude/
├── STRUCTURE_GUIDE.md     ← You are here — how-to + registries
├── README.md              ← Orientation for new contributors / sessions
├── settings.json          ← Team-shared permissions + hooks (git-tracked)
├── settings.local.json    ← Personal permissions (gitignored)
├── agents/                ← Workflow + specialist agents (flat)
│   └── _specialist-template.md
├── commands/              ← Slash commands
├── skills/                ← Reference docs for tools (grow via protocol)
├── kb/                    ← Knowledge base
│   ├── _index.yaml        ← Domain registry (machine SSoT)
│   ├── _templates/        ← Scaffolding templates
│   └── _research/         ← Deep Research landing zone (pillar 3)
│       ├── README.md
│       ├── inbox/         ← Raw research dumps (gitignored)
│       └── archive/       ← Consumed research, tracked for provenance
├── hooks/                 ← PreToolUse / PostToolUse shell scripts
├── sdd/                   ← Spec-Driven Development artifacts
│   ├── README.md
│   ├── features/          ← Active specs (sprint-N/<phase-slug>/)
│   └── archive/           ← Shipped specs
├── cache/                 ← MCP caches (gitignored)
└── storage/               ← Session state (gitignored)
```

---

## Project units — Sprint / Phase

Defined in `CLAUDE.md` § Project units (the SSoT). SDD artifacts are keyed on
`sprint-N/<phase-slug>`.

---

## Registries

`CLAUDE.md` points here. `_index.yaml` is the machine SSoT for KB; these tables are the
human-readable registries. Update them when you add an artifact — cache-safe.

### Command Registry

| Command         | Purpose                                                |
| --------------- | ------------------------------------------------------ |
| `/new-kb`       | Create/extend a KB domain (kb-architect, 3-pillar)     |
| `/update-kb`    | Refresh a KB domain against the 3 pillars              |
| `/new-agent`    | Scaffold a specialist agent                            |
| `/new-command`  | Scaffold a slash command                               |
| `/sprint-start` | Open a sprint — `SPRINT.md` plan + sprint-wide KB scan |
| `/brainstorm`   | SDD Stage 0 — explore approaches                       |
| `/define`       | SDD Stage 1 — requirements + Clarity gate (≥12/15)     |
| `/design`       | SDD Stage 2 — architecture + file manifest             |
| `/implement`    | Execute implementation per the design                  |
| `/review`       | Validate a branch — checks + code review + KB loop     |
| `/sprint-close` | Close a sprint — knowledge loop + archive              |

### Agent Registry

| Agent              | Category     | Model  | Role                                      |
| ------------------ | ------------ | ------ | ----------------------------------------- |
| `kb-architect`     | meta         | sonnet | KB creation/audit, 3-pillar build         |
| `brainstorm-agent` | workflow     | sonnet | SDD Stage 0 — exploration, MoSCoW         |
| `define-agent`     | workflow     | opus   | SDD Stage 1 — requirements, Clarity gate  |
| `design-agent`     | workflow     | opus   | SDD Stage 2 — architecture, file manifest |
| `code-reviewer`    | code-quality | sonnet | Branch-diff review for `/review`          |

**Model routing:** when spawning an agent via the Agent tool, ALWAYS pass `model`
explicitly — read the agent's frontmatter `model:` field. The fallback is the parent
model (Opus), which defeats cost control.

### KB Domain Registry

Empty — domains are added on demand (see § Knowledge Base). Machine SSoT:
`.claude/kb/_index.yaml`. When a domain is created, add a row here:

| Domain          | Status | Purpose                                                           | Primary agent  |
| --------------- | ------ | ----------------------------------------------------------------- | -------------- |
| `rag-retrieval` | draft  | Hybrid BM25+dense retrieval, chunking, score fusion, eval metrics | `kb-architect` |

---

## SDD — Spec-Driven Development

A sprint runs `/sprint-start` → the per-phase SDD pipeline → `/sprint-close`:

- **Sprint level** — `/sprint-start sprint-N` writes `SPRINT.md` (goal, phase
  breakdown, sprint-wide KB/research scan). `/sprint-close sprint-N` runs the sprint
  knowledge loop and archives the whole `sprint-N/` folder.
- **Phase level** (each phase) — `/brainstorm → /define → /design → /implement →
/review`, artifacts under `.claude/sdd/features/sprint-N/<phase-slug>/`.

Three distinct units: **Sprint** (top), **Phase** (sub-unit, `sprint-N/phase-M`), and
**SDD Stage** (a step of the per-phase pipeline). The pipeline diagram and the
use-vs-skip criteria are the SSoT of `.claude/sdd/README.md`; the Clarity gate rubric
is owned by `define-agent.md`. See `sdd/README.md` before reaching for SDD.

---

## Knowledge Base

Every KB domain holds, well-separated:

- **`concepts/`** — theory, definitions, invariants, trade-offs.
- **`patterns/`** — codebase-grounded recipes from our `src/`/`eval/`.

Both are built and validated against **3 pillars** — codebase, MCP docs (Context7 +
Exa), and Gemini Deep Research. The pillar table and the agreement-analysis matrix are
the SSoT of `.claude/agents/kb-architect.md`; the numeric line budgets are the SSoT of
`.claude/kb/_index.yaml` (`limits`). Pillar 3 (Deep Research) is reserved for genuinely
complex topics — see `.claude/kb/_research/README.md`.

---

## Self-Improvement Protocol — Detail

The trigger rules live in `CLAUDE.md`. This section is the **how**.

### When to add a KB concept or pattern

**Trigger:** same domain knowledge re-derived in ≥2 sessions.
**Action:** run `/new-kb <domain>` (or `/update-kb <domain>` to extend one). The
`kb-architect` agent scaffolds, runs the 3 pillars, and updates `_index.yaml` + the KB
Domain Registry above.

### When to add an agent

**Trigger:** same specialist framing + KB reads + role recurs in ≥2 sessions, AND the
work needs an isolated context window.
**Steps:**

1. `cp .claude/agents/_specialist-template.md .claude/agents/<name>.md`.
2. Fill frontmatter (`name`, `description`, `tools`, `kb_domains`, `model`) and the 5
   sections (Identity, Mandatory Reads, Capabilities, Quality Gate, Response Format).
3. Add a row to the **Agent Registry** above. Do **not** edit `CLAUDE.md`.

### When to add a slash command

**Trigger:** same multi-step workflow run ≥2 times.
**Steps:**

1. Create `.claude/commands/<name>.md` (frontmatter `description`; sections When to
   use / Steps / Output).
2. Add a row to the **Command Registry** above. Do **not** edit `CLAUDE.md`.

### When to add a skill

**Trigger:** Claude needs a specific tool/CLI repeatedly and the usage isn't trivial.
Create `.claude/skills/<tool>.md` (frontmatter `skill`, `description`, `trigger`,
`priority`); document invocation, flags, gotchas, examples.

### When to extend `settings.json` permissions

**Trigger:** ≥3 permission prompts on the same pattern in one session. Team-shared
(read-only MCP, safe bash) → `settings.json`; destructive/env-specific →
`settings.local.json`. Prefer specific patterns over wildcards.

### When to add a hook

**Trigger:** a bug class slips through twice and is mechanically detectable. Script in
`.claude/hooks/`; wire in `settings.json`; exit 0 = allow, exit 2 = block (stderr
message must say what to run to unblock); use `$CLAUDE_PROJECT_DIR` for paths.

### When `CLAUDE.md` genuinely must change

Registries live here, so this is rare. When it is unavoidable: append the proposed
text to `docs/planning/claude-md-pending.md` and apply all pending edits in **one**
batch at end of session — never mid-session (cache invalidation).

---

## Bootstrap Order

1. **KB** — record knowledge first. Cheap, no behavior change.
2. **Skills** — document tools next.
3. **Commands** — encode workflows.
4. **Agents** — when a workflow needs an isolated context window.
5. **Hooks** — last; only when a bug class has actually bitten.
6. **SDD** — engage for phases complex enough for brainstorm → define → design.

---

## Anti-Patterns

- **Premature scaffolding.** Wait for the second occurrence.
- **Wildcard permissions.** `Bash(*)` defeats the safety model.
- **Duplicated content.** Link to code / `_index.yaml`; don't copy.
- **Editing `CLAUDE.md` mid-session.** Use the registries here; batch the rare real
  `CLAUDE.md` change.
- **Hooks that block without a remediation.** Every block message says what to run.
- **Ungrounded KB.** A pattern must trace to real `src/`/`eval/` code, not invention.

---

## Where to put what — quick map

| If you have…                      | Put it in…                                          |
| --------------------------------- | --------------------------------------------------- |
| A reusable code shape             | `.claude/kb/<domain>/patterns/<name>.md`            |
| An atomic concept or contract     | `.claude/kb/<domain>/concepts/<name>.md`            |
| A multi-step workflow             | `.claude/commands/<name>.md` + Command Registry     |
| Repeated specialist framing       | `.claude/agents/<name>.md` + Agent Registry         |
| A tool/CLI reference              | `.claude/skills/<tool>.md`                          |
| A pre-commit / pre-bash check     | `.claude/hooks/<name>.sh` + wire in `settings.json` |
| A pre-implementation spec         | `.claude/sdd/features/sprint-N/<phase-slug>/`       |
| Raw Deep Research output          | `.claude/kb/_research/inbox/`                       |
| A pointer to an external resource | Memory (`~/.claude/projects/.../memory/`)           |
