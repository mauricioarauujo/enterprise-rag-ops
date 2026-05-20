# DESIGN: sprint-1/phase-2-retrieval — Hybrid Retrieval

**Sprint/Phase:** sprint-1/phase-2-retrieval | **Date:** 2026-05-18

## Architecture

Phase 2 adds a `retrieval` package alongside the existing `ingest` package, consuming
`data/processed/corpus.jsonl` (Phase 1 output) and producing three persisted index
artifacts plus a query-time `HybridRetriever`. There are two distinct paths.

### Index-build path (`make build-index` → `rag-index` CLI)

```
corpus.jsonl ──► chunker ──► list[Chunk]
                                │
              ┌─────────────────┼──────────────────────┐
              ▼                 ▼                       ▼
        BM25 index        Embedder.encode()        LanceDB table
   bm25_index/ (bm25s   embeddings.npy + chunk   lancedb/ (chunk_id,
   .save, mmap reload)   order sidecar (.json)    doc_id, source_type,
                                                  text, vector)
```

The build is orchestrated by `pipeline.py::build_index(...)`, mirroring
`ingest/cli.py::run`. It is idempotent: it returns early if `data/processed/lancedb/`
exists, unless `force=True` (the `make rebuild-index` path, which deletes all three
artifacts first). Per-source chunk-count distribution is logged at INFO via stdlib
`logging` (NFR-6), mirroring `ingest/cli.py`'s per-source document logging.

### Query path (`HybridRetriever.retrieve`)

```
query ──► Embedder.encode(query) ──┐
          │                        ▼
          │              VectorStore.dense_search()  ─┐
          ▼                                            ├─► RRF(k=60) ─► chunk→doc_id
   BM25Index.search()  ──────────────────────────────┘    fuse        dedup (first
   (over-fetch 3×k each)                                                rank wins)
                                                                          │
                                              abstention gate ◄───────────┤
                                       (top-1 dense cosine < 0.45 → [])    ▼
                                                              top-k (doc_id, score)
```

A fresh process loads the three persisted artifacts and serves queries with no
re-indexing or re-encoding (NFR-1).

### The three seams (NFR-4 — the central architectural decision)

Three small Protocols in `interfaces.py` isolate every swappable dependency. Each is a
named seam justified by a _likely_ future change recorded in ADR-002 — we design the
boundary, we do **not** pre-build alternative implementations behind it.

1. **`Embedder`** — `encode(texts: Sequence[str]) -> np.ndarray`, `dim: int`. Phase 2
   ships `BGEEmbedder` (BGE-M3 via `sentence-transformers`) and `StubEmbedder`
   (deterministic hash-based fixed-dim vectors, RQ-5). The stub is a drop-in: it
   satisfies the same Protocol, so the CI pipeline-contract test injects it with zero
   production-code branches and no model download (NFR-3). The embedder is _injected_,
   never imported, by `HybridRetriever` and the build pipeline.

2. **`VectorStore`** — `add(records)`, `dense_search(query_vector, k, source_type_filter)`,
   `open(path)`. `LanceDBStore` is the only implementation in Phase 2. All
   LanceDB-specific code (schema construction, `.where()` pre-filter syntax, table
   open) lives behind this Protocol, so the anticipated LanceDB→Qdrant swap (ADR-002)
   is a new file implementing the same Protocol — a localized change, not a rewrite.

3. **`Retriever`** — `retrieve(query, top_k, source_type_filter) -> list[tuple[str, float]]`.
   `HybridRetriever` is the only implementation; the Protocol names the contract Phase 3
   generation depends on, so a future reranking or graph retriever is a drop-in.

`HybridRetriever.__init__` takes `Embedder`, `VectorStore`, `BM25Index`, and
`reranker=None` (FR-8 composability hook — a parameter only, no implementation). The
BM25 lexical index is _not_ behind a seam: `bm25s` is local, file-based, and not a
candidate for the documented Qdrant swap — adding a Protocol there would be a seam "in
case", which the engineering guidance rejects.

## File Manifest

| File                                                   | Change  | Owner  | Phase order |
| ------------------------------------------------------ | ------- | ------ | ----------- |
| `src/enterprise_rag_ops/retrieval/__init__.py`         | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/schema.py`           | created | direct | 1           |
| `src/enterprise_rag_ops/retrieval/config.py`           | created | direct | 2           |
| `src/enterprise_rag_ops/retrieval/interfaces.py`       | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/chunker.py`          | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/embedder.py`         | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/bm25_index.py`       | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/vector_store.py`     | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/hybrid_retriever.py` | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/pipeline.py`         | created | direct | 3           |
| `src/enterprise_rag_ops/retrieval/cli.py`              | created | direct | 3           |
| `tests/retrieval/__init__.py`                          | created | direct | 4           |
| `tests/retrieval/conftest.py`                          | created | direct | 4           |
| `tests/retrieval/test_schema.py`                       | created | direct | 4           |
| `tests/retrieval/test_chunker.py`                      | created | direct | 4           |
| `tests/retrieval/test_embedder.py`                     | created | direct | 4           |
| `tests/retrieval/test_bm25_index.py`                   | created | direct | 4           |
| `tests/retrieval/test_vector_store.py`                 | created | direct | 4           |
| `tests/retrieval/test_hybrid_retriever.py`             | created | direct | 4           |
| `tests/retrieval/test_pipeline_contract.py`            | created | direct | 4           |
| `tests/retrieval/test_retrieval_smoke.py`              | created | direct | 4           |
| `pyproject.toml`                                       | changed | direct | 2           |
| `Makefile`                                             | changed | direct | 3           |
| `docs/adr/0002-retrieval-architecture.md`              | created | direct | 5           |
| `docs/adr/0001-eval-framework.md`                      | created | direct | 5           |
| `docs/adr/README.md`                                   | changed | direct | 5           |

Owner is `direct` for every file: no retrieval specialist agent exists, and DEFINE
confirmed none is required for Phase 2 (the `rag-retrieval` KB plus the two patterns
give `/implement` sufficient grounding).

### Module responsibilities

- **`schema.py`** — `Chunk` dataclass (`chunk_id`, `doc_id`, `text`); FR-1 invariant
  `Chunk.doc_id == Document.id`. Mirrors `ingest/schema.py` as the package contract.
- **`config.py`** — chunking params (256/32), BM25 params (`k1=1.5`, `b=0.75`,
  `method="lucene"`), `RRF_K=60`, `OVER_FETCH=3`, `TOP_K=10`, `ABSTENTION_THRESHOLD=0.45`,
  `EMBEDDING_MODEL="BAAI/bge-m3"`, `EMBEDDING_DIM=1024`, and artifact paths
  (`BM25_INDEX_DIR`, `EMBEDDINGS_PATH`, `LANCEDB_DIR`). Mirrors `ingest/config.py`.
- **`interfaces.py`** — the three `Protocol` seams (`Embedder`, `VectorStore`,
  `Retriever`); no logic.
- **`chunker.py`** — `chunk_document(doc) -> list[Chunk]` via
  `RecursiveCharacterTextSplitter`; deterministic `chunk_id = f"{doc.id}::{offset}"`;
  uniform, no per-source branching (FR-2).
- **`embedder.py`** — `BGEEmbedder` and `StubEmbedder`, both satisfying `Embedder` (FR-4, RQ-5).
- **`bm25_index.py`** — `BM25Index` wrapping `bm25s` build/`save`/`load(mmap=True)`/
  `search` (FR-3).
- **`vector_store.py`** — `LanceDBStore` implementing `VectorStore`; schema with
  `source_type` as a pre-filterable column (FR-5, FR-7).
- **`hybrid_retriever.py`** — `HybridRetriever` implementing `Retriever`: over-fetch,
  RRF fusion, doc-level dedup, `source_type_filter`, `reranker=None`, abstention
  (FR-6 – FR-9). RRF/dedup logic follows `patterns/hybrid-retrieve-fuse.md`.
- **`pipeline.py`** — `build_index(force=False)` orchestrator; idempotency skip,
  per-source logging (FR-10, NFR-1, NFR-2, NFR-6).
- **`cli.py`** — `rag-index` entrypoint (argparse, `--force` flag); registered under
  `[project.scripts]`. Mirrors `ingest/cli.py`.

## Implementation Phases

Ordered per the harness convention (schema → config → core src → tests → docs/ADR;
no `eval/` or `observability/` work is in this phase's scope).

1. **Data schema** — `retrieval/schema.py`: the `Chunk` dataclass and the
   `Chunk.doc_id == Document.id` invariant (AC-1).
2. **Config** — `pyproject.toml`: add the four version-bounded runtime deps
   (`bm25s`, `sentence-transformers`, `lancedb`, `langchain-text-splitters`) and the
   `rag-index` script entry; add a `smoke` pytest marker for the local-only smoke
   test (NFR-5, AC-14). Then `retrieval/config.py` with all tunable parameters.
3. **Core module logic (`src/`)** — `interfaces.py` (seams) first, then `chunker.py`,
   `embedder.py`, `bm25_index.py`, `vector_store.py`, `hybrid_retriever.py`,
   `pipeline.py`, `cli.py`. `Makefile`: add `build-index`, `rebuild-index`,
   `retrieval-smoke` targets (FR-10, FR-12).
4. **Tests (`tests/retrieval/`)** — one mirrored file per module. `conftest.py` holds
   the tiny synthetic fixture corpus and the `StubEmbedder` fixture.
   `test_pipeline_contract.py` is the offline wiring gate run by `make verify`
   (FR-11, AC-11). `test_retrieval_smoke.py` is marked `smoke`, BGE-M3 real-model,
   local-only via `make retrieval-smoke`, excluded from `make verify` (FR-12, AC-12) —
   its first `/implement` step is the streamed `questions`-config inspection to pick
   3–5 questions with verified `expected_doc_ids` (RQ-2).
5. **Docs + ADR** — `docs/adr/0002-retrieval-architecture.md` (accepted; FR-13),
   `docs/adr/0001-eval-framework.md` (short "deferred to Sprint 2" stub; RQ-1),
   `docs/adr/README.md` index updated to list both and correct the "first ADR lands
   in Sprint 2" line.

Validation order per the Engineering Behavior guidance: smallest-first
(`uv run pytest tests/retrieval -m "not smoke"`), then `make verify`, then the
local-only `make build-index` + `make retrieval-smoke` on a real checkout.

## Infrastructure Gaps

All three gap layers checked at design-level detail. DEFINE found no blocking gaps;
this design confirms that finding and refines two non-blocking observations.

| Gap Type           | Area               | Detail                                                                                                                                                                              | Recommendation                                                                                                                                            |
| ------------------ | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Missing domain     | retrieval          | None. Every technology area in this design — chunking, bm25s, BGE-M3, LanceDB, RRF fusion, metadata filtering, recall@k smoke — maps to the existing `rag-retrieval` domain.        | None — `_index.yaml` coverage is complete.                                                                                                                |
| Missing concept    | rag-retrieval      | None blocking. The seam/`VectorStore`-Protocol abstraction this design centers on is an architectural pattern, not retrieval domain knowledge — it is owned by ADR-002, not the KB. | Non-blocking: `/update-kb rag-retrieval` refocus pass post-ADR-002 (already SPRINT-scoped, out of this phase).                                            |
| Missing specialist | retrieval-engineer | None blocking. No specialist agent has `kb_domains: [rag-retrieval]`; all five existing agents are workflow agents with `kb_domains: []`. `/implement` runs with KB + patterns.     | Non-blocking. If `/implement` shows repeated retrieval-context loading, raise a post-phase `**Harness suggestion:**` for `/new-agent retrieval-engineer`. |

- **Domain existence** — pass. `rag-retrieval` exists and its 7 concepts + 2 patterns
  cover every Phase 2 technology.
- **Concept coverage** — pass. `chunking-strategies`, `lexical-vs-semantic`,
  `hybrid-score-fusion`, `metadata-filtering`, `retrieval-eval-metrics`, `reranking`
  cover all FRs; `patterns/hybrid-retrieve-fuse.md` and
  `patterns/expected-doc-ids-smoke.md` are near-exact skeletons for `hybrid_retriever.py`
  and `test_retrieval_smoke.py`. One mismatch worth flagging to `/implement`, not a KB
  gap: the `hybrid-retrieve-fuse` pattern re-encodes the whole corpus on every
  `dense_retrieve` call — Phase 2 must instead encode once at build time and
  dense-search the persisted LanceDB index (NFR-1). The pattern is a _fusion-logic_
  reference, not a persistence reference.
- **Agent alignment** — pass with a noted absence. No retrieval specialist exists;
  DEFINE already accepted `direct` ownership for Phase 2. Confirmed at design level:
  the manifest assigns every file to `direct`.

## Risks & Trade-offs

What ADR-002 must capture:

- **Vector store choice** — LanceDB embedded over Qdrant/pgvector. Rationale: no
  server, disk-backed, native pre-filter, scale is ~3–5k chunks. ADR-002 must
  explicitly name the **anticipated LanceDB→Qdrant swap** as the future change that
  justifies the `VectorStore` seam — the seam is legitimate only because this named
  change is recorded.
- **Chunking strategy** — uniform fixed-size (256/32), no per-source branching, no
  parent-child. ADR-002 records the escalation trigger: if the smoke gate yields
  `Recall@10 == 0` on any question, escalate to parent-child before Phase 3.
- **Fusion algorithm** — RRF(k=60), no calibration. ADR-002 notes convex-combination
  / DBSF were rejected for lack of tuning data; tuning is Sprint 2's job.
- **Embedding model & dim** — BGE-M3, 1024-dim. ADR-002 records the 568 MB one-time
  download cost and the CI consequence: the stub embedder behind the `Embedder` seam.

Design risks for `/implement`:

- **bm25s position↔chunk_id mapping** — `bm25s.retrieve` returns corpus positions;
  the chunk-order sidecar must be the single source of truth shared by the `.npy`
  matrix, the BM25 index, and the LanceDB rows, or RRF fuses mismatched IDs. Build all
  three from one ordered `list[Chunk]` in `pipeline.py`.
- **Abstention vs filter interaction** — abstention reads top-1 _dense cosine_; when a
  `source_type_filter` empties the candidate set, `retrieve()` must return `[]`
  cleanly rather than erroring (AC-8 + AC-9 must both hold).
- **Stub embedder fidelity** — `StubEmbedder` must emit normalized fixed-`dim` vectors
  so cosine math and the abstention path exercise the same code as BGE-M3; a
  degenerate stub would let the contract test pass while masking a real bug.
- **`make build-index` idempotency granularity** — the skip checks only
  `data/processed/lancedb/`; a partial/crashed build leaving `lancedb/` but no `.npy`
  would wrongly skip. Acceptable for Phase 2 (documented); `rebuild-index` is the
  escape hatch.

## Next Step

→ `/implement sprint-1/phase-2-retrieval` — no infrastructure gaps to address first;
proceed directly. First implementation step is the streamed `questions`-config
inspection to fix the 3–5 smoke questions (RQ-2).
