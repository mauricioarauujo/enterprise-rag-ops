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
| Architecture decisions          | `docs/adr/` (ADR-0001–0003 shipped in Sprint 1) |
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

**Harness & SDD slash commands** — a sprint is wrapped by `/sprint-start` … `/sprint-close`;
each phase runs `/brainstorm` → `/define` → `/design` → `/implement` → `/review`. Plus
`/new-kb`, `/update-kb`, `/new-agent`, `/new-command`. **Full list (the SSoT) is in
`.claude/STRUCTURE_GUIDE.md` § Registries — consult it before recommending a command.**

---

## Architecture (current)

Sprint 1 (substrate) has shipped: an end-to-end RAG pipeline — deterministic ingest →
hybrid retrieval → attributed generation. `eval/` (Sprint 2) and `observability/`
(Sprint 3) are not built yet; the project's differentiator lives in those upcoming
layers (see § Project Purpose).

```
enterprise-rag-ops/
├── .claude/                       # Orchestration: agents, KB, commands, skills, hooks, SDD
├── .github/                       # CI workflows (lint + test + smoke on PR)
├── docs/                          # Public: architecture, dataset notes, ADRs (0001–0003)
├── src/enterprise_rag_ops/
│   ├── ingest/      # Phase 1: HF stream → stratified subset → Document → corpus.jsonl  (rag-ingest)
│   ├── retrieval/   # Phase 2: chunker, bm25s, BGE-M3, LanceDB, RRF fusion, HybridRetriever  (rag-index)
│   │                #          seams (Protocols): Embedder / VectorStore / Retriever  (interfaces.py)
│   ├── generation/  # Phase 3: AnswerWithSources, Generator seam, OpenAIGenerator, ContextAssembler  (rag-ask)
│   ├── eval/        # (Sprint 2) per-fact judge, retrieval metrics, multi-model runner  (rag-eval)
│   └── observability/  # (Sprint 3) tracing, failure taxonomy, dashboard
├── data/                          # (gitignored) raw + processed bench data
├── results/                       # (gitignored) eval reports
├── tests/                         # pytest, mirrors src/
├── Makefile
├── pyproject.toml
└── README.md
```

Entry points (console scripts in `pyproject.toml`): `rag-ingest` (build corpus),
`rag-index` (build BM25 + embeddings + LanceDB), `rag-ask` (end-to-end query).
Key make targets: `make build-index`, `make retrieval-smoke`, `make smoke`, `make verify`.

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

## Engineering Behavior

How to implement work in this repo. Guiding principle: **minimal scope, clean
structure** — build the smallest thing that meets the phase's acceptance criteria,
but build it well enough that it never becomes tech-debt. Scalable and maintainable
from day 0.

- **Think before coding.** Start from the SDD artifacts for the phase
  (`BRAINSTORM`/`DEFINE`/`DESIGN` under `.claude/sdd/features/{slug}/`) and the
  relevant KB domain. If requirements are ambiguous, surface options and trade-offs —
  never silently pick one.
- **Minimal scope.** Build only what the acceptance criteria require — no speculative
  features, no premature implementations. The substrate stays deliberately
  conventional (see Project Purpose).
- **Clean structure.** Structure what you _do_ build to last: name the **seams** —
  interfaces/ports where a future swap is likely — so that swap is a localized
  change, not a rewrite. A seam is justified by a _named, likely_ future change (an
  ADR that anticipates it), not by "in case." Design the seam; do not pre-build the
  implementation behind it. "Scalable from day 0" means the _shape_ is right, not
  that the production tool is wired in early.
- **Surgical edits.** Limit changes to files the task needs. Every new module gets a
  mirrored test file. Clean up only artifacts your own change introduced — not
  unrelated legacy.
- **Goal-driven validation.** Success criteria come before code (the `DEFINE.md`
  acceptance criteria). Validate smallest-first, then widen: targeted
  `uv run pytest -k`, then `make verify`. Work is done only when code _and_
  validation support the stated outcome.

---

## Testing

- Framework: pytest + pytest-cov (added in Sprint 0).
- Layout: tests mirror `src/` (`tests/test_<module>.py`).
- Run: `make test` or `uv run pytest`.
