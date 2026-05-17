# CLAUDE.md — Enterprise RAG Ops

Project instructions auto-loaded every turn. Single source of truth for how Claude Code operates in this repo.

Registries (commands, agents, KB domains) live in `.claude/STRUCTURE_GUIDE.md` — it is
not auto-loaded, so editing it is cache-safe. Keep `CLAUDE.md` edits rare and batched.

---

## Project Purpose

Production-grade **RAG evaluation and observability** harness over the EnterpriseRAG-Bench dataset. The differentiator is not the RAG — it's the eval harness and observability layer around it.

Built in sprints; the current sprint and module map are in § Architecture below.

---

## Project units — Sprint / Phase

Work is organized as **Sprints** (top-level units), each made of **Phases** (~3 per
medium sprint, 4–5 for complex). SDD artifacts are keyed on `sprint-N/<phase-slug>`.
Personal sprint tracking is private (see `CLAUDE.local.md`).

---

## Quick Navigation

| What                            | Where                                           |
| ------------------------------- | ----------------------------------------------- |
| Spec / architecture             | `docs/architecture/`                            |
| Dataset notes                   | `docs/dataset.md`                               |
| Architecture decisions          | `docs/adr/` (first ADR in Sprint 2)             |
| Harness maintenance             | `.claude/STRUCTURE_GUIDE.md`                    |
| Self-improvement protocol       | `.claude/STRUCTURE_GUIDE.md` § Self-Improvement |
| Command / agent / KB registries | `.claude/STRUCTURE_GUIDE.md` § Registries       |
| KB registry (machine-readable)  | `.claude/kb/_index.yaml`                        |
| SDD layer (specs)               | `.claude/sdd/README.md`                         |

---

## Commands

| Task              | Command       |
| ----------------- | ------------- |
| Setup             | `uv sync`     |
| Format            | `make format` |
| Lint              | `make lint`   |
| Test              | `make test`   |
| Full quality pass | `make verify` |

**Harness & SDD slash commands** (`/new-kb`, `/brainstorm`, `/define`, `/design`,
`/implement`, `/review`, …) — full list in `.claude/STRUCTURE_GUIDE.md` § Registries.

---

## Architecture (current)

Repo is in Sprint 0 — only tooling and harness exist. No `src/` yet. The target architecture will land in Sprint 1 (substrate) and Sprint 2 (eval harness). When code arrives, update this section with a module map.

```
enterprise-rag-ops/
├── .claude/         # Orchestration: agents, KB, commands, skills, hooks, SDD
├── .github/         # CI workflows
├── docs/            # Public-facing: architecture, dataset notes, ADRs
├── src/             # (Sprint 1+) RAG, retrieval, generation modules
├── eval/            # (Sprint 2+) Eval harness, per-fact judge, multi-model runner
├── observability/   # (Sprint 3+) Tracing, failure taxonomy, dashboard
├── data/            # (gitignored) Raw + processed bench data
├── results/         # (gitignored) Eval reports
├── tests/           # Pytest
├── Makefile
├── pyproject.toml
└── README.md
```

---

## Agents

Workflow and specialist agents live flat in `.claude/agents/<name>.md`, added as
concrete needs surface (see Self-Improvement protocol). Full registry:
`.claude/STRUCTURE_GUIDE.md` § Agent Registry. Template: `_specialist-template.md`.
Scaffold with `/new-agent`. When spawning an agent, always pass `model` explicitly.

---

## Knowledge Base

KB domains are added on demand via the **3-pillar build** (codebase + MCP docs +
Gemini Deep Research) — see `.claude/STRUCTURE_GUIDE.md` § Knowledge Base. Machine
registry: `.claude/kb/_index.yaml`. Templates: `.claude/kb/_templates/`.

**Line budgets** are SSoT'd in `.claude/kb/_index.yaml` (`limits`).

---

## Self-Improvement Protocol (mandatory)

This harness is designed to grow. **Claude must proactively propose harness changes** when patterns emerge — don't wait to be asked.

**Trigger and suggest a harness change when any of the following holds:**

1. **Repeated reasoning** — Same domain knowledge re-derived in ≥2 sessions → propose a KB concept or pattern.
2. **Repeated workflow** — Same multi-step bash/edit sequence run ≥2 times → propose a slash command.
3. **Repeated specialist context** — Same set of files/KB reads + role framing happens ≥2 times → propose an agent.
4. **Repeated tool-usage friction** — Permission prompts on the same command pattern ≥3 times → propose adding to `.claude/settings.json`.
5. **Drift between code and KB/CLAUDE.md** — Code reality contradicts a documented pattern → propose an update.
6. **Missing quality gate** — A class of bug slips through twice → propose a hook or CI check.

**How to propose (don't unilaterally create):**

End the relevant turn with a `**Harness suggestion:**` block stating: (a) the trigger, (b) what to add/change, (c) where it goes, (d) one-line cost/benefit. Wait for user approval before scaffolding.

Use `/new-kb`, `/update-kb`, `/new-agent`, `/new-command` — see `.claude/STRUCTURE_GUIDE.md` for the bootstrap order.

---

## Conventions

- **Language for code & docs:** English.
- **Dates in docs:** YYYY-MM-DD.
- **Commit format:** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).
- **Branch naming:** `sprint-<n>/<short-slug>` for sprint work, `fix/<slug>` for one-offs.
- **Tests:** pytest. New module → new test file. No mocking the LLM API in eval tests — use the cassette/replay pattern (TBD ADR in Sprint 2).
- **No edits to `CLAUDE.md` mid-session** — invalidates prompt cache. Batch CLAUDE.md changes; prefer the `STRUCTURE_GUIDE.md` registries, which are cache-safe.

---

## Testing

- Framework: pytest + pytest-cov (added in Sprint 0).
- Layout: tests mirror `src/` (`tests/test_<module>.py`).
- Run: `make test` or `uv run pytest`.
