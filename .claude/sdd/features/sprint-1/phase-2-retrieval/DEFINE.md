# DEFINE: sprint-1/phase-2-retrieval — Hybrid Retrieval

**Sprint/Phase:** sprint-1/phase-2-retrieval | **Date:** 2026-05-18

## Resolved Open Questions

The BRAINSTORM listed 5 open questions; all are resolved as confirmed inputs to this
phase (the "Resolved (2026-05-18)" section plus one decision pinned by the user on the
same date). They are recorded here so `/design` and `/implement` treat them as fixed —
do **not** re-open them.

- **RQ-1 — ADR-001 (eval framework).** Deferred to Sprint 2. Phase 2 writes only a
  short "deferred to Sprint 2" stub in `docs/adr/` (Could-have); the full
  RAGAs / DeepEval / custom-judge decision is made when the eval harness exists and
  produces empirical signal. ADR-002 (retrieval architecture + vector store) **is**
  written this phase.
- **RQ-2 — Smoke-gate question selection.** The 3–5 fixed smoke questions with verified
  `expected_doc_ids` are selected during `/implement` as its first step — a streamed
  inspection of the dataset `questions` config at the pinned SHA
  (`69916e31c68aa5963c00248fd7f0bc12d04fd235`, `QUESTIONS_CONFIG = "questions"`). No
  separate manual pre-run is required.
- **RQ-3 — Text splitter library.** Use the standalone `langchain-text-splitters`
  package (not the full `langchain` meta-package), pinned in `pyproject.toml`. A
  battle-tested `RecursiveCharacterTextSplitter` is less custom code to own than a
  bespoke splitter — lower long-term debt.
- **RQ-4 — Retrieval testing tiers.** Two-tier. A fast **pipeline-contract** test runs
  in `make verify` / CI; a real-model **Recall@k** smoke (BGE-M3 over the corpus
  subset) runs local-only via `make retrieval-smoke`. The 568 MB cost is the embedding
  model, not the input data.
- **RQ-5 — CI embedder (pinned by user, 2026-05-18).** The CI pipeline-contract test
  uses a **pure stub embedder** — a deterministic fake embedder (e.g. hash-based
  fixed-dimension vectors) injected through the Retriever/embedder seam. No model
  download in CI. BGE-M3 Recall@k testing stays local via `make retrieval-smoke`.
- **RQ-6 — `make build-index` idempotency.** `make build-index` is idempotent — it
  skips if `data/processed/lancedb/` already exists. `make rebuild-index` forces a
  clean rebuild.

These were resolved against the BRAINSTORM and SPRINT track without an interactive
`AskUserQuestion` round (this ran as a subagent). RQ-1 through RQ-6 are confirmed
inputs, not unconfirmed assumptions — no orchestrator re-confirmation is needed before
`/design`.

## Requirements

### Functional

- **FR-1 (Chunk model)** — A `Chunk` dataclass exists with fields `chunk_id: str`,
  `doc_id: str`, `text: str`. The invariant `Chunk.doc_id == Document.id` holds; the
  smoke gate deduplicates retrieved chunks to `doc_id` before scoring recall.
- **FR-2 (Chunker)** — A chunker splits each `Document` in `data/processed/corpus.jsonl`
  with uniform fixed-size chunking (256-token child window, 32-token overlap) using
  `langchain_text_splitters.RecursiveCharacterTextSplitter`. The same strategy applies
  to all source types — no per-source branching. `chunk_id` is derived deterministically
  from `Document.id` plus the chunk offset index.
- **FR-3 (BM25 index)** — A lexical index is built via `bm25s`
  (`method="lucene"`, `k1=1.5`, `b=0.75`) over chunk texts and persisted to
  `data/processed/bm25_index/` via `bm25s.save()`; it reloads with `mmap=True`.
- **FR-4 (Dense embeddings)** — Chunk texts are encoded once with BGE-M3
  (`BAAI/bge-m3`, 1024-dim) via `sentence-transformers`; the corpus matrix is saved to
  `data/processed/embeddings.npy` with chunk ordering persisted alongside so it maps
  back to `chunk_id`.
- **FR-5 (Vector store)** — A LanceDB embedded index is created at
  `data/processed/lancedb/` with a schema containing `chunk_id`, `doc_id`,
  `source_type`, `text`, and the dense vector. `source_type` is a pre-filterable
  column.
- **FR-6 (Hybrid retriever)** — A `HybridRetriever` runs BM25 + dense retrieval with
  3× over-fetch per retriever, fuses with RRF (`k=60`), deduplicates chunk hits to
  `doc_id` (first occurrence preserves rank), and returns the top-k `(doc_id, score)`
  list with no duplicate `doc_id`.
- **FR-7 (Metadata filter)** — `HybridRetriever.retrieve()` accepts an optional
  `source_type_filter: str | None = None` parameter; when set, retrieval is restricted
  to chunks of that `source_type` via the LanceDB pre-filterable column.
- **FR-8 (Reranker hook)** — `HybridRetriever` exposes a `reranker=None` parameter as a
  composability placeholder; no reranker is implemented in Phase 2.
- **FR-9 (Abstention)** — If the top-1 dense cosine similarity is below `0.45`, the
  retriever returns an empty list.
- **FR-10 (`make build-index`)** — A `make build-index` target runs chunking → BM25
  index → embedding → LanceDB indexing end-to-end. It is idempotent: it skips when
  `data/processed/lancedb/` already exists. `make rebuild-index` forces a clean rebuild.
- **FR-11 (Pipeline-contract test)** — A fast pipeline-contract test runs in
  `make verify` / CI using a tiny synthetic fixture corpus and a pure deterministic
  stub embedder injected via the embedder seam. It asserts the wiring: chunk → BM25 +
  dense → RRF fusion → chunk→`doc_id` dedup → ranked top-k, with no duplicate `doc_id`.
  No model download occurs in CI.
- **FR-12 (Recall@k smoke)** — A `make retrieval-smoke` target runs a real-model smoke
  test (BGE-M3 over the corpus subset) on 3–5 fixed questions with verified
  `expected_doc_ids`, asserting `Recall@10 > 0` per question and unique `doc_id` in
  retriever output. This target is local-only and not part of `make verify`.
- **FR-13 (ADR-002)** — `docs/adr/` gains ADR-002 recording the retrieval architecture:
  LanceDB embedded vector store, BGE-M3 dense embeddings, `bm25s` lexical index, RRF
  (k=60) fusion, uniform fixed-size chunking, and the `VectorStore`/`Retriever`
  interface seam.

### Non-functional

- **NFR-1 (Index persistence)** — BM25 index, embedding matrix, and LanceDB table are
  all persisted to `data/processed/`; no index is rebuilt or re-encoded on a retrieval
  call. A fresh process loads the persisted artifacts and serves queries.
- **NFR-2 (Reproducibility)** — Re-running `make build-index` (after a forced rebuild)
  on the same `corpus.jsonl` and the same parameters produces a functionally
  equivalent index — deterministic chunking, stable chunk ordering, no RNG.
- **NFR-3 (CI offline / no large download)** — `make verify` runs the
  pipeline-contract test with the stub embedder and no network access; no 568 MB model
  is downloaded in CI.
- **NFR-4 (Interface seam)** — A clean `VectorStore` / `Retriever` interface boundary
  isolates the LanceDB-specific code, so the anticipated LanceDB→Qdrant swap
  (ADR-002) is a localized change rather than a rewrite. The embedder is injected
  through this seam so the stub embedder is a drop-in for BGE-M3.
- **NFR-5 (Dependency hygiene)** — `pyproject.toml` `dependencies` gains exactly
  `bm25s`, `sentence-transformers`, `lancedb`, and `langchain-text-splitters`, each
  version-bounded. No eval/observability libraries are added.
- **NFR-6 (Observability)** — The index build logs per-source chunk-count distribution
  via the stdlib `logging` module at INFO level (mirrors Phase 1's per-source document
  logging).
- **NFR-7 (Conventions)** — New code lives under `src/enterprise_rag_ops/retrieval/`
  with mirrored tests under `tests/retrieval/`; `make verify` (ruff format + lint +
  pytest) passes.

## Acceptance Criteria

1. A `Chunk` dataclass exists with `chunk_id`, `doc_id`, `text`; constructing a `Chunk`
   from a `Document` yields `chunk.doc_id == document.id`.
2. The chunker splits `corpus.jsonl` into 256-token chunks with 32-token overlap via
   `RecursiveCharacterTextSplitter`; a single-source vs multi-source corpus produces
   chunks with no per-source code path difference.
3. `make build-index` on a clean checkout (deps synced, `corpus.jsonl` present)
   produces `data/processed/bm25_index/`, `data/processed/embeddings.npy`, and
   `data/processed/lancedb/`, and exits 0.
4. Running `make build-index` a second time with `data/processed/lancedb/` present
   skips the rebuild and exits 0 (idempotent); `make rebuild-index` deletes and
   regenerates all three artifacts.
5. The BM25 index is reloadable from disk with `mmap=True` without re-indexing; the
   embedding matrix is reloadable from `.npy` without re-encoding.
6. The LanceDB schema includes `chunk_id`, `doc_id`, `source_type`, `text`, and the
   dense vector; `source_type` is usable as a pre-filter.
7. `HybridRetriever.retrieve(query, top_k=10)` returns at most 10 `(doc_id, score)`
   pairs with no duplicate `doc_id`, after BM25 + dense → RRF(k=60) → doc-level dedup.
8. `HybridRetriever.retrieve(query, source_type_filter="slack")` returns only docs
   whose `source_type == "slack"`.
9. When the top-1 dense cosine similarity is below 0.45, `retrieve()` returns an empty
   list — verified with a fixture query unrelated to the corpus.
10. `HybridRetriever` accepts a `reranker=None` parameter; passing `reranker=None`
    is the default path and changes no output.
11. The pipeline-contract test runs under `make verify` with a deterministic stub
    embedder, performs no network I/O, and asserts the full
    chunk → BM25 + dense → RRF → dedup → top-k wiring with unique `doc_id` output.
12. `make retrieval-smoke` runs the BGE-M3 real-model smoke on 3–5 fixed questions and
    asserts `Recall@10 > 0` per question and unique `doc_id` per result; it is not
    invoked by `make verify`.
13. `docs/adr/` contains ADR-002 (retrieval architecture + vector store, accepted) and
    a short ADR-001 "deferred to Sprint 2" stub.
14. `pyproject.toml` lists `bm25s`, `sentence-transformers`, `lancedb`, and
    `langchain-text-splitters` as version-bounded runtime dependencies, and
    `make verify` passes with new modules under `src/enterprise_rag_ops/retrieval/`
    and mirrored tests under `tests/retrieval/`.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                      |
| ----------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit: Phase 1's validated `corpus.jsonl` exists but nothing retrieves over it; Phase 3 needs a working retriever. Evidenced by BRAINSTORM + SPRINT.                        |
| Users       | 2     | Consumers are the downstream Phase 3 generation layer (named) and the maintainer running CI/smoke. Substrate phase — no external end user; workflow-impact dimension is inherently thin.  |
| Success     | 3     | 14 numbered, falsifiable acceptance criteria, each with a concrete pass/fail check.                                                                                                       |
| Scope       | 3     | Full MoSCoW in BRAINSTORM with an explicit 8-item Won't list (reranker, ADR-001, per-source chunking, parent-child, full questions load, frontier techniques, server stores, alt fusion). |
| Constraints | 3     | Persistence, reproducibility, offline CI, the LanceDB→Qdrant interface seam, dependency hygiene, and conventions all named as NFRs.                                                       |

**Total: 14/15 — PASS (≥12).** Users scored 2: this is a substrate phase whose
"user" is the downstream phase plus the maintainer, so the workflow-impact dimension is
inherently thin — acceptable, not a blocker (consistent with Phase 1's DEFINE).

## Infrastructure Readiness

| Dependency                       | KB domain       | Specialist | Status                                                                                                            |
| -------------------------------- | --------------- | ---------- | ----------------------------------------------------------------------------------------------------------------- |
| `corpus.jsonl` (Phase 1 output)  | none needed     | none       | Ready — Phase 1 merged (commit `cdec9d7`); `Document` schema and stratified subset are validated.                 |
| `rag-retrieval` KB               | `rag-retrieval` | none       | Ready — built via 3-pillar Deep Research; covers all Phase 2 topics (chunking, fusion, smoke, metrics).           |
| `bm25s`                          | `rag-retrieval` | none       | Ready — KB-recommended; `concepts/lexical-vs-semantic.md` + `patterns/hybrid-retrieve-fuse.md` cover it. New dep. |
| `sentence-transformers` / BGE-M3 | `rag-retrieval` | none       | Ready — KB default; 568 MB one-time download, local-only via `make retrieval-smoke`. New dep.                     |
| `lancedb`                        | `rag-retrieval` | none       | Ready — KB decision matrix covers it; ADR-002 records the choice. New dep.                                        |
| `langchain-text-splitters`       | `rag-retrieval` | none       | Ready — `concepts/chunking-strategies.md` covers fixed-size defaults; RQ-3 pins the package. New dep.             |
| HF dataset `questions` config    | none needed     | none       | Ready — same pinned SHA as Phase 1; inspected via streaming during `/implement` (RQ-2).                           |

No `/new-kb` or `/new-agent` is blocking Phase 2. The `rag-retrieval` KB is the
single domain in scope and is already built; per SPRINT.md it gets an
`/update-kb rag-retrieval` refocus pass _after_ ADR-002 (out of this phase's scope).
No specialist agent exists for retrieval yet — none is required: the `rag-retrieval`
KB plus the `hybrid-retrieve-fuse` / `expected-doc-ids-smoke` patterns give
`/implement` sufficient grounding. If Phase 2 implementation surfaces repeated
retrieval-specific context loading, that would be a post-phase
`**Harness suggestion:**` for a `/new-agent retrieval-engineer`, not a Phase 2 blocker.

## Next Step

→ `/design sprint-1/phase-2-retrieval`
