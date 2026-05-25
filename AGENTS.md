# AGENTS.md — Enterprise RAG Ops

Shared, tool-agnostic instructions for any AI coding agent working in this repo
(Claude Code, Antigravity / Gemini CLI, etc.). This file is the **single source of
truth** for project facts, conventions, and the implementation contract.

- **Claude Code** imports this file from `CLAUDE.md` (`@AGENTS.md`); `CLAUDE.md` adds
  only Claude-specific orchestration (slash commands, sub-agents, hooks).
- **Antigravity / Gemini CLI** read this file natively from the workspace.

Workflow split: planning and review (brainstorm → define → design → review) run in
**Claude Code**; the token-heavy **implement** stage runs in **Antigravity / Gemini**.
The handoff between the two is the SDD design artifact — see § Implement Contract.

---

## Project Purpose

Production-grade **RAG evaluation and observability** harness over the
EnterpriseRAG-Bench dataset. The differentiator is not the RAG — it's the eval harness
and observability layer around it.

Built in sprints; the current sprint and module map are in § Architecture below.

---

## Project units — Sprint / Phase

Work is organized as **Sprints** (top-level units), each made of **Phases** (~3 per
medium sprint, 4–5 for complex). SDD artifacts are keyed on `sprint-N/<phase-slug>`
under `.claude/sdd/features/{slug}/`. Personal sprint tracking is private (see
`CLAUDE.local.md`).

---

## Commands

| Task               | Command              |
| ------------------ | -------------------- |
| Setup              | `uv sync`            |
| Format (auto-fix)  | `make format`        |
| Lint (check-only)  | `make lint`          |
| Test               | `make test`          |
| Lint + test        | `make lint test`     |
| Activate git hooks | `make install-hooks` |

Other key targets: `make build-index`, `make retrieval-smoke`, `make smoke`.

---

## Architecture (current)

Sprint 1 (substrate) has shipped: an end-to-end RAG pipeline — deterministic ingest →
hybrid retrieval → attributed generation. `eval/` (Sprint 2) and `observability/`
(Sprint 3) are in progress; the project's differentiator lives in those layers.

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

---

## Knowledge Base

Stabilized domain knowledge lives in `.claude/kb/` (index: `.claude/kb/_index.yaml`).
**Read the relevant KB domain before implementing in its area** — e.g. `rag-retrieval`,
`rag-generation`, `rag-eval`. The KB is plain markdown and readable by any tool.

---

## Conventions

- **Language for code & docs:** English.
- **Dates in docs:** YYYY-MM-DD.
- **Commit format:** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).
- **Branch naming:** `sprint-<n>/<short-slug>` for sprint work, `fix/<slug>` for one-offs.
- **Tests:** pytest. New module → new test file. No mocking the LLM API in eval tests —
  use the cassette/replay pattern (TBD ADR in Sprint 2).

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
  features, no premature implementations. The substrate stays deliberately conventional.
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
  `uv run pytest -k`, then `make lint test`. Work is done only when code _and_
  validation support the stated outcome.

---

## Testing

- Framework: pytest + pytest-cov.
- Layout: tests mirror `src/` (`tests/test_<module>.py`).
- Run: `make test` or `uv run pytest`.

---

## Implement Contract (cross-tool)

The implement stage may run in Claude Code or in Antigravity / Gemini. **The SDD design
artifact is the contract** between planning (done in Claude Code) and implementation.

To implement a phase `sprint-N/phase-slug`:

1. **Read the spec.** `.claude/sdd/features/{slug}/DESIGN.md` (file manifest + phase
   order) and `.claude/sdd/features/{slug}/DEFINE.md` (acceptance criteria). If no SDD
   artifacts exist, work from the phase track directly (SDD is opt-in).
2. **Read the relevant KB** domain(s) in `.claude/kb/` (see § Knowledge Base).
3. **Confirm the branch.** You should be on `sprint-N/phase-slug`. If on `main`, create
   it before committing any code.
4. **Implement** following the manifest's phase order. Honour § Engineering Behavior and
   § Conventions. Every new module gets a mirrored `tests/test_<module>.py`. Eval-path
   code uses the cassette/replay pattern — never a mocked LLM API.
5. **Quality pass:** run `make lint test` — the real gate (lint + test), also run in CI
   on every PR. A pre-commit hook (pre-commit framework) runs `make format` on commit
   and blocks if it changed files — re-stage (`git add -u`) and commit again. Activate
   once per clone with `make install-hooks`.
6. **Commit** in Conventional Commits format. Report files changed, tests pass/fail, and
   any infrastructure/KB gaps you hit.
