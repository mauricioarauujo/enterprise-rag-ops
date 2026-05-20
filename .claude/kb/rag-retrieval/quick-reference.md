# RAG Retrieval Quick Reference

> Fast lookup tables. For full rationale, see linked concept files.
> **Phase 2 shipped** (Sprint 1): LanceDB embedded, BGE-M3, BM25s, RRF k=60.
> ADR: `docs/adr/0002-retrieval-architecture.md`.

## Chunking Parameters (Phase 2 — uniform fixed-size)

| Parameter         | Phase 2 Value                  | Notes                                               |
| ----------------- | ------------------------------ | --------------------------------------------------- |
| Child chunk size  | 256 chars                      | `RecursiveCharacterTextSplitter`, no per-src branch |
| Child overlap     | 32 chars (12.5%)               | Uniform across all 9 source types                   |
| Parent chunk size | Not used in Phase 2            | Escalation path if smoke gate yields Recall@10=0    |
| `chunk_id` format | `"{doc_id}::{offset}"`         | Deterministic; offset = 0-based position in doc     |
| Chunk-to-doc key  | `Chunk.doc_id` = `Document.id` | Dedup key for eval scoring                          |

## Embedding Models

| Model                 | Dims         | Context  | MTEB Retrieval | Use                               |
| --------------------- | ------------ | -------- | -------------- | --------------------------------- |
| BGE-M3 (Phase 2)      | 1024         | 8192 tok | ~63.0          | Default; 568 MB one-time download |
| nomic-embed-text-v1.5 | 64–768 (MRL) | 8192 tok | 62.39          | Fallback; CPU-friendly            |
| BGE-large-en-v1.5     | 1024         | 512 tok  | 64.11          | English-only, short docs          |

## Score Fusion

| Method         | Needs calibration | Robust to outliers | Use when                        |
| -------------- | ----------------- | ------------------ | ------------------------------- |
| RRF (k=60)     | No                | Yes                | Default — Phase 2 uses this     |
| Convex (alpha) | Yes               | No                 | Score distributions are stable  |
| DBSF           | No                | Yes                | Scores are calibrated per-query |

## Retrieval Metrics — Formulas

| Metric      | Formula (textual)                   | Primary signal     |
| ----------- | ----------------------------------- | ------------------ |
| Recall@k    | \|relevant ∩ top-k\| / \|relevant\| | Coverage           |
| Precision@k | \|relevant ∩ top-k\| / k            | Exactness          |
| MRR         | avg(1 / rank of first hit)          | First-hit position |
| nDCG@k      | DCG@k / IDCG@k (log2 discount)      | Ranking quality    |

**Evaluation depth**: k = 10 (`config.TOP_K`).
**Abstention threshold**: cosine similarity < 0.45 → return [] (FR-9, `config.ABSTENTION_THRESHOLD`).
**Smoke gate**: `make retrieval-smoke` (local-only; excluded from `make verify`).
**Rerank skip**: top-1 normalized dense similarity > 0.90 → skip reranker (effective exact match).

## Component Defaults (Phase 2 Shipped)

| Component      | Phase 2               | Swap path                                                 |
| -------------- | --------------------- | --------------------------------------------------------- |
| Score fusion   | RRF (k=60)            | DBSF (when score magnitudes are calibrated)               |
| Vector store   | LanceDB embedded      | `QdrantStore` via `VectorStore` Protocol (ADR-002)        |
| Lexical engine | bm25s (lucene method) | Not a swap candidate; no Protocol seam                    |
| Embedder       | BGEEmbedder (BGE-M3)  | `StubEmbedder` in CI; `Embedder` Protocol seam            |
| Reranker       | None (hook only)      | Cross-encoder drop-in via `HybridRetriever(reranker=...)` |

## Vector Store Decision Matrix

| Criterion      | LanceDB              | Qdrant                | pgvector                |
| -------------- | -------------------- | --------------------- | ----------------------- |
| Hybrid search  | Built-in             | Native sparse+dense   | Manual SQL union        |
| Deployment     | Embedded (no server) | Docker / cloud        | PostgreSQL extension    |
| Dev ergonomics | Excellent            | Strong SDK            | Complex SQL             |
| RAM footprint  | Low (disk-based)     | High (HNSW in RAM)    | High (vertical)         |
| Best for       | Dev / small subset   | Production / high QPS | Existing Postgres infra |

## Common Pitfalls

| Don't                                              | Do                                                   |
| -------------------------------------------------- | ---------------------------------------------------- |
| Re-encode corpus on every query call               | Encode once at build time (`make build-index`)       |
| Evaluate at chunk level against `expected_doc_ids` | Deduplicate chunk hits to `doc_id` first             |
| Post-filter metadata after vector search           | Pre-filter before scoring (LanceDB `prefilter=True`) |
| Skip over-fetch before RRF                         | Fetch `OVER_FETCH` (3×) per retriever before fusing  |

## Related Documentation

| Topic               | Path                                      |
| ------------------- | ----------------------------------------- |
| Chunking strategies | `concepts/chunking-strategies.md`         |
| Score fusion        | `concepts/hybrid-score-fusion.md`         |
| Eval metrics        | `concepts/retrieval-eval-metrics.md`      |
| Hybrid pattern      | `patterns/hybrid-retrieve-fuse.md`        |
| Smoke gate pattern  | `patterns/expected-doc-ids-smoke.md`      |
| ADR                 | `docs/adr/0002-retrieval-architecture.md` |
| Full index          | `index.md`                                |
