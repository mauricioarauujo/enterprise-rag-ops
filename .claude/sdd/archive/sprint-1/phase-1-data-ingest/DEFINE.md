# DEFINE: sprint-1/phase-1-data-ingest — Data Ingest & Document Indexing

**Sprint/Phase:** sprint-1/phase-1-data-ingest | **Date:** 2026-05-17

## Resolved Open Questions

The BRAINSTORM listed 5 open questions. They are resolved here as defined
requirements/assumptions (clarifying questions could not be raised interactively in
this run; resolutions follow the BRAINSTORM recommendations and the SPRINT plan, and
should be confirmed if the implementer disagrees):

- **Q1 — HF revision SHA.** Resolved as a requirement: pin the latest `main` commit
  SHA of `onyx-dot-app/EnterpriseRAG-Bench` as of the ingest run. The exact SHA is
  recorded in this file's Requirements section and in ADR-001/ADR-002 when written.
  Not a hard-coded SHA at define time; the implementer captures it during `/implement`.
- **Q2 — Per-source field mapping.** Resolved as an assumption: raw source field
  schemas are reverse-engineered by inspecting the dataset during `/implement`, then
  documented in `docs/dataset.md`. Tracked as a risk (adapter effort S→M).
- **Q3 — Chunking boundary.** Confirmed: "document indexing" in SPRINT.md means
  organizing raw documents into the canonical `Document` model. Chunking, BM25, and
  embeddings are all Phase 2 (BRAINSTORM Approach A). Recorded in Won't-have scope.
- **Q4 — Materialize vs stream.** Resolved: `make download-data` materializes a
  processed subset to `data/processed/corpus.jsonl`; `make check-data` validates that
  file offline with no live HF connection. Streaming is used only inside
  `download-data` to avoid loading 500K+ docs into memory.
- **Q5 — `metadata` field contents.** Resolved as an assumption: `metadata: dict`
  preserves all raw per-source fields not mapped to top-level `Document` fields, with
  `doc_id` guaranteed stable for Phase 2's `expected_doc_ids` linkage. Per-source
  typing is deferred (Won't-have).

## Requirements

### Functional

- **FR-1** — `make download-data` fetches `onyx-dot-app/EnterpriseRAG-Bench` via
  `datasets.load_dataset(..., streaming=True, revision=<SHA>)`, where `<SHA>` is a
  pinned HF commit SHA recorded in source and in `docs/dataset.md`.
- **FR-2** — A Pydantic `Document` model exists with fields `id: str`,
  `source_type: str`, `text: str`, `metadata: dict`. Construction validates types and
  rejects empty `text` and empty `id`.
- **FR-3** — One normalization adapter per source type maps raw HF records to
  `Document`. Adapters are registered in a dict keyed by `source_type` string and
  cover all source types present in the dataset (BRAINSTORM lists 9: Confluence, Jira,
  Slack, Linear, Gmail, GDrive, GitHub, HubSpot, Fireflies — actual set confirmed at
  ingest time).
- **FR-4** — Ingest produces a stratified subset: for each `source_type`, documents
  are sorted by `doc_id` and the first `DOCS_PER_SOURCE` are taken (deterministic,
  no RNG).
- **FR-5** — `DOCS_PER_SOURCE` is configurable via Makefile/env parameter; default
  is 100.
- **FR-6** — The subset is serialized to `data/processed/corpus.jsonl`, one JSON
  object per line, each a serialized `Document`.
- **FR-7** — `make check-data` runs a pytest smoke test that validates
  `corpus.jsonl` **offline** (no network) and asserts: (a) the file exists; (b) line
  count is within the expected range for the configured `DOCS_PER_SOURCE`; (c) every
  source type is represented; (d) no document has empty `text`; (e) all `id` values
  are unique.
- **FR-8** — `docs/dataset.md` is updated with field-level schema notes: the pinned
  revision SHA, the per-source raw→`Document` field mapping, and the sampling contract.

### Non-functional

- **NFR-1 (Reproducibility)** — Re-running `make download-data` at the same pinned
  SHA and `DOCS_PER_SOURCE` yields a byte-identical `corpus.jsonl` (deterministic
  sort, stable serialization, no timestamps in output).
- **NFR-2 (Memory)** — Ingest never materializes the full 500K+ document corpus in
  memory; streaming + per-source bounded `take` keeps peak memory proportional to
  `DOCS_PER_SOURCE × 9`.
- **NFR-3 (Offline validation)** — `make check-data` completes with no network
  access, so it is safe as a CI gate.
- **NFR-4 (Dependency hygiene)** — `pyproject.toml` `dependencies` gains exactly
  `datasets` and `pydantic` (version-bounded); no transitive retrieval/eval libs.
- **NFR-5 (Observability)** — The ingest script logs per-source document counts via
  the stdlib `logging` module at INFO level.
- **NFR-6 (Conventions)** — New code lives under `src/enterprise_rag_ops/ingest/`,
  has a mirrored `tests/` file, and passes `make verify` (ruff format + lint, pytest).

## Acceptance Criteria

1. Running `make download-data` on a clean checkout (deps synced) produces
   `data/processed/corpus.jsonl` and exits 0.
2. `corpus.jsonl` contains `DOCS_PER_SOURCE` documents per source type (default 100;
   fewer only if a source has fewer total documents, which is logged).
3. Running `make download-data DOCS_PER_SOURCE=10` produces a 10-per-source corpus and
   exits 0 — the parameter is honored.
4. Two consecutive `make download-data` runs at the same SHA and `DOCS_PER_SOURCE`
   produce byte-identical `corpus.jsonl` files (`diff` reports no difference).
5. `make check-data` exits 0 against a valid corpus and exits non-zero if any of:
   the file is missing, a source type is absent, a `text` field is empty, or a
   duplicate `id` exists — verified by deliberately corrupting a fixture.
6. `make check-data` completes with no outbound network connection.
7. Constructing `Document(text="")` or `Document(id="")` raises a Pydantic
   `ValidationError`.
8. Every source type present in the pinned dataset revision has a registered adapter;
   an unmapped `source_type` raises a clear error rather than silently dropping records.
9. `docs/dataset.md` records the pinned revision SHA, the per-source field mapping,
   and the deterministic sampling contract.
10. `pyproject.toml` lists `datasets` and `pydantic` as runtime dependencies with
    version bounds, and `make verify` passes.

## Clarity Score

| Dimension   | Score | Note                                                                                                          |
| ----------- | ----- | ------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit: no `src/`, no deps, Phase 2 needs a stable validated corpus; BRAINSTORM evidences it.    |
| Users       | 2     | Primary consumer is Phase 2 retrieval (named) and the project maintainer running CI; no external end user.    |
| Success     | 3     | 10 measurable, falsifiable acceptance criteria, each with a concrete pass/fail check.                         |
| Scope       | 3     | Full MoSCoW in BRAINSTORM with an explicit 6-item Won't list (chunking, embeddings, BM25, eval, full corpus). |
| Constraints | 3     | Memory, reproducibility, offline CI, dependency hygiene, conventions all named as NFRs.                       |

**Total: 14/15 — PASS (≥12).** Users scored 2: this is a substrate phase whose
"user" is the downstream phase plus the maintainer, so the workflow-impact dimension
is inherently thin — acceptable, not a blocker.

## Infrastructure Readiness

| Dependency                  | KB domain       | Specialist | Status                                                                    |
| --------------------------- | --------------- | ---------- | ------------------------------------------------------------------------- |
| HF `datasets` library       | none needed     | none       | Ready — well-trodden API; field notes go to `docs/dataset.md` per SPRINT. |
| `pydantic`                  | none needed     | none       | Ready — standard library knowledge; no KB entry warranted.                |
| EnterpriseRAG-Bench dataset | none needed     | none       | Ready — public HF dataset (MIT); revision pinned at ingest time.          |
| `rag-retrieval` knowledge   | `rag-retrieval` | (none yet) | Out of scope — Phase 2 prerequisite; `/new-kb rag-retrieval` deferred.    |

No `/new-kb` or `/new-agent` is blocking Phase 1. The only KB gap (`rag-retrieval`)
is explicitly a Phase 2 prerequisite and is already tracked in `SPRINT.md`
§ Sprint-Wide KB & Research. The KB registry (`.claude/kb/_index.yaml`) remains
empty, which is correct for this phase.

## Next Step

→ `/design sprint-1/phase-1-data-ingest`
