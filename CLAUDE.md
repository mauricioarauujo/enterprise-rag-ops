# CLAUDE.md — Enterprise RAG Ops

Project instructions auto-loaded every turn. Single source of truth for how Claude Code operates in this repo.

---

## Project Purpose

Production-grade **RAG evaluation and observability** harness over the EnterpriseRAG-Bench dataset. The differentiator is not the RAG — it's the eval harness and observability layer around it.

Built in phases; the current phase and module map are in § Architecture below.

---

## Quick Navigation

| What                      | Where                                           |
| ------------------------- | ----------------------------------------------- |
| Spec / architecture       | `docs/architecture/`                            |
| Dataset notes             | `docs/dataset.md`                               |
| Architecture decisions    | `docs/adr/` (first ADR in Phase 1)              |
| Harness maintenance       | `.claude/STRUCTURE_GUIDE.md`                    |
| Self-improvement protocol | `.claude/STRUCTURE_GUIDE.md` § Self-Improvement |
| KB registry               | `.claude/kb/_index.yaml`                        |
| Agent registry            | see § Agents below                              |
| Commands                  | `.claude/commands/`                             |
| Skills (tool reference)   | `.claude/skills/`                               |
| SDD layer (specs)         | `.claude/sdd/README.md`                         |

---

## Commands

| Task              | Command       |
| ----------------- | ------------- |
| Setup             | `uv sync`     |
| Format            | `make format` |
| Lint              | `make lint`   |
| Test              | `make test`   |
| Full quality pass | `make verify` |

**Harness slash commands** — scaffold the orchestration layer per the Self-Improvement protocol:

| Command        | Purpose                                 |
| -------------- | --------------------------------------- |
| `/new-kb`      | Scaffold a KB domain or concept/pattern |
| `/update-kb`   | Refresh a KB domain against code + docs |
| `/new-agent`   | Scaffold a specialist agent             |
| `/new-command` | Scaffold a slash command                |

---

## Architecture (current)

Repo is in Phase 0 — only tooling and harness exist. No `src/` yet. The target architecture will land in Phase 1 (substrate) and Phase 2 (eval harness). When code arrives, update this section with a module map.

```
enterprise-rag-ops/
├── .claude/         # Orchestration: agents, KB, commands, skills, hooks, SDD
├── .github/         # CI workflows
├── docs/            # Public-facing: architecture, dataset notes, ADRs
├── src/             # (Phase 1+) RAG, retrieval, generation modules
├── eval/            # (Phase 2+) Eval harness, per-fact judge, multi-model runner
├── observability/   # (Phase 3+) Tracing, failure taxonomy, dashboard
├── data/            # (gitignored) Raw + processed bench data
├── results/         # (gitignored) Eval reports
├── tests/           # Pytest
├── Makefile
├── pyproject.toml
└── README.md
```

---

## Agents

Empty registry — agents live flat in `.claude/agents/<name>.md` and are added as concrete needs surface (see Self-Improvement protocol below). Template: `.claude/agents/_specialist-template.md`. Scaffold with `/new-agent`. Likely first agents: `rag-eval`, `retrieval`, `observability` (Phase 1+).

---

## Knowledge Base

Empty — KB domains are added when content stabilizes (typically after Phase 1 retrieval or Phase 2 eval design lands). Registry: `.claude/kb/_index.yaml`. Templates: `.claude/kb/_templates/`.

**Line budgets:** concept ≤ 150, pattern ≤ 200, quick-reference ≤ 100.

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
- **Branch naming:** `phase-<n>/<short-slug>` for phase work, `fix/<slug>` for one-offs.
- **Tests:** pytest. New module → new test file. No mocking the LLM API in eval tests — use the cassette/replay pattern (TBD ADR in Phase 2).
- **No edits to `CLAUDE.md` mid-session** — invalidates prompt cache. Batch CLAUDE.md changes.

---

## Testing

- Framework: pytest + pytest-cov (added in Phase 0).
- Layout: tests mirror `src/` (`tests/test_<module>.py`).
- Run: `make test` or `uv run pytest`.
