# ADR-0002: Retrieval Architecture — Hybrid BM25 + Dense over LanceDB

**Status:** accepted
**Date:** 2026-05-18

## Context

Sprint 1 Phase 2 needs a retriever over the ingested corpus
(`data/processed/corpus.jsonl`, ~900 documents in the default subset, ~3–5k
chunks after splitting). Phase 3 will consume it for generation; Sprint 2 will
evaluate it. The decision space we faced — chunking, lexical vs dense, fusion,
vector store, and the interface seam — is captured here in one place rather than
spread across module docstrings.

Constraints:

- This is a substrate sprint — the retriever must work and be maintainable, not exotic.
- Stratified subset is small enough that a server-based vector store is
  over-engineered; an embedded one is enough.
- CI must run offline — no 568 MB model download on every `make test`.
- The retrieval layer is _substrate_: Sprint 2 will sweep parameters, Sprint 3
  will instrument it. Today's choices must not be obstacles to that work.

## Decision

A hybrid retriever with five components:

1. **Chunking** — `langchain-text-splitters.RecursiveCharacterTextSplitter`,
   uniform 256-token windows with 32-token overlap, no per-source branching.
2. **Lexical index** — `bm25s` (`method="lucene"`, `k1=1.5`, `b=0.75`), persisted
   to `data/processed/bm25_index/`, reloaded with `mmap=True`.
3. **Dense embeddings** — BGE-M3 (`BAAI/bge-m3`, 1024-dim) via
   `sentence-transformers`. Encoded once at build time, persisted as
   `embeddings.npy` plus a `chunk_ids` sidecar.
4. **Vector store** — LanceDB embedded, at `data/processed/lancedb/`, schema
   `(chunk_id, doc_id, source_type, text, vector)`; `source_type` is a
   pre-filterable column.
5. **Fusion** — Reciprocal Rank Fusion (RRF) with `k=60` over BM25 + dense
   results (each over-fetched 3× before fusion), then dedup chunks to docs
   (first occurrence preserves rank). Abstention fires when the top-1 dense
   cosine similarity is below `0.45`.

The implementation hides every swappable dependency behind three small
`Protocol`s in `retrieval/interfaces.py`:

- **`Embedder`** — `BGEEmbedder` for production; `StubEmbedder` (hash-based
  deterministic vectors) injected into the CI pipeline-contract test so
  `make test` runs offline.
- **`VectorStore`** — `LanceDBStore` is the only implementation; the seam exists
  for the anticipated LanceDB→Qdrant swap (see _Consequences_).
- **`Retriever`** — `HybridRetriever` is the only implementation; the seam names
  the contract Phase 3 generation will depend on.

BM25 is intentionally **not** behind a seam — `bm25s` is local, file-based, and
not a documented swap candidate; a Protocol there would be a seam "in case",
which our engineering guidance rejects.

## Consequences

### What we accept

- **One-time 568 MB BGE-M3 download** on the first `make build-index` /
  `make retrieval-smoke`. CI uses the stub embedder behind the `Embedder` seam,
  so `make test` stays offline (NFR-3).
- **Uniform chunking** likely under-serves long structured docs (Confluence
  pages, Jira issues with long descriptions). The Phase 2 smoke gate is the
  early-warning mechanism: if any smoke query yields `Recall@10 == 0`, the
  escalation is parent-child chunking before Phase 3.
- **RRF (k=60), no calibration**. Convex-combination or DBSF were rejected for
  lack of tuning data — Sprint 2's eval harness produces the signal that would
  justify them; doing it now is premature optimization.

### What changes when it changes

- **LanceDB → Qdrant** is the named, anticipated future change behind the
  `VectorStore` seam. Trigger: corpus scale grows past LanceDB embedded's sweet
  spot (~10k+ chunks with active concurrent writers), or Sprint 3 needs OTel
  spans from a server-side store. The swap is a new `QdrantStore` implementing
  `VectorStore` and a one-line wiring change in `pipeline.load_retriever()`.
- **Reranking** is a composability hook today (`HybridRetriever(reranker=...)`)
  with no implementation. A Sprint 2 cross-encoder would be a drop-in: same
  `Retriever` Protocol, same call sites.

### Build-time invariants

- The ordered chunk list produced by `chunker.chunk_documents()` is the **single
  source of truth** for position↔chunk_id mapping across the BM25 index, the
  `.npy` matrix, and the LanceDB rows. They are written from one ordered list in
  `pipeline.build_index()`; never from three independent passes.
- `make build-index` is idempotent — it skips if `data/processed/lancedb/`
  exists. `make rebuild-index` is the escape hatch when something has changed
  underneath (corpus regeneration, chunker tweak).
- The chunker's `chunk_id = f"{doc_id}::{offset}"` is deterministic, so the
  index is reproducible (NFR-2).

### Abstention Calibration (Sprint 2 Calibration)

- A threshold sweep (0.30 - 0.65, step 0.05) run over the 500-question eval set confirmed that the current `0.45` threshold serves as a high-precision, zero-false-positive operating point (preventing any incorrect abstentions on answerable questions, though yielding 0.0 recall on unanswerable ones). Raising the threshold (e.g. to `0.55` or `0.60`) increases recall (detecting unanswerable questions) at the cost of a high False Positive rate due to the dense model's uncalibrated score distribution.

## Alternatives Considered

| Choice           | Picked               | Rejected                        | Why                                                                                                                                      |
| ---------------- | -------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Vector store     | LanceDB (embedded)   | Qdrant, pgvector, FAISS         | No server to run, native pre-filter, scale matches the subset. Qdrant becomes attractive at production scale — seam keeps the door open. |
| Chunking         | Fixed 256/32 uniform | Parent-child, semantic, per-src | Smallest thing that works; smoke gate escalates if Recall@10 == 0.                                                                       |
| Fusion           | RRF (k=60)           | Convex combination, DBSF        | RRF needs no calibration; the others need Sprint 2 eval signal first.                                                                    |
| Embedding model  | BGE-M3 (1024-dim)    | bge-base, OpenAI text-embed     | Multilingual, strong on the MTEB English subset, fits on a laptop, free.                                                                 |
| CI test embedder | StubEmbedder (hash)  | Tiny real model in CI           | Stub satisfies the same Protocol with no model download; same code path exercised.                                                       |

## References

- `.claude/kb/rag-retrieval/` — concepts and patterns this decision draws on.
- `.claude/sdd/features/sprint-1/phase-2-retrieval/` — BRAINSTORM, DEFINE, DESIGN.
- ADR-0001 — eval framework (deferred to Sprint 2).
