# .claude/ — Orchestration Layer

The orchestration system this project was **built with** — a spec-driven, AI-assisted
engineering harness. It is tracked on purpose: alongside the RAG eval/observability product
in `src/`, this layer is the auditable record of _how_ the work was done. (See
[`README.md` § How this was built](../README.md#how-this-was-built) for the framing.)

If you only read the product code, you see the result. This folder shows the **method**:
requirements gated before design, decisions recorded at decision time, domain knowledge
distilled once and reused, and a process that improves itself.

## If you're reviewing this project

A short path through the method (the [guided tour](../README.md#how-this-was-built) links
the high-value exemplars):

1. `sdd/README.md` — the per-phase pipeline (`/brainstorm → /define → /design → /implement → /review`).
2. One exemplar phase end-to-end: `sdd/archive/sprint-2/phase-4-perfact-judge/`
   (`DEFINE → DESIGN → REVIEW`) — requirements to verification on the core eval signal.
3. `kb/` — the distilled domain knowledge (4 domains: `rag-retrieval`, `rag-generation`,
   `rag-eval`, `observability`).
4. `../docs/adr/` — the decisions, captured when the trade-off was live.

## What's here

| Dir / file           | What it is                                                                                      |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| `sdd/`               | Spec-Driven Development artifacts — 18 archived phases across 6 sprints, plus the pipeline docs |
| `kb/`                | 3-pillar knowledge base (codebase + official docs + deep research); 4 stabilized domains        |
| `commands/`          | 12 slash commands — the SDD pipeline + harness-maintenance commands                             |
| `agents/`            | Specialist + workflow agents (e.g. `kb-architect`, reviewers)                                   |
| `skills/`            | Reusable task skills                                                                            |
| `hooks/`             | Git/quality hooks (format-on-commit, gates)                                                     |
| `STRUCTURE_GUIDE.md` | Registries (commands, agents, KB domains) + the Self-Improvement Protocol                       |
| `settings.json`      | Team-shared permissions and hooks                                                               |

The harness grows on demand, not speculatively: repeated reasoning → a KB entry; a repeated
workflow → a command; a recurring specialist context → an agent (the Self-Improvement
Protocol in `../CLAUDE.md`).

---

## Maintaining this layer

**Reading order for contributors:**

1. `../CLAUDE.md` — project SSoT (auto-loaded every turn anyway)
2. `STRUCTURE_GUIDE.md` — how to add/change agents, KB, commands, skills, hooks
3. `kb/_index.yaml` — domain registry (4 domains registered)
4. `sdd/README.md` — Spec-Driven Development pipeline (use for complex tasks; skip for one-offs)

**Safe to edit by hand:** `settings.json` · `kb/_index.yaml` · any `*.md` in `agents/`,
`commands/`, `skills/`, `kb/` · `sdd/features/*` and `sdd/archive/*`.

**Do _not_ edit by hand:** `kb/_templates/*.template` (copy from, don't edit) · `hooks/*.sh`
(exit codes are a contract) · `cache/`, `storage/`, `hooks/.gates/` (runtime state, gitignored).
