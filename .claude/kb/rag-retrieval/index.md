# RAG Retrieval Knowledge Base

> **Purpose**: Hybrid retrieval over the document corpus — chunking, BM25 + dense,
> score fusion, metadata filtering, vector-store choice, and retrieval evaluation
> (recall@k / precision@k / MRR / nDCG over `expected_doc_ids`).
> **Phase 2 shipped** (Sprint 1, 2026-05-19). ADR: `docs/adr/0002-retrieval-architecture.md`.
> **MCP Validated**: 2026-05-17

## Quick Navigation

### Concepts

| File                                                                     | Purpose                                                       |
| ------------------------------------------------------------------------ | ------------------------------------------------------------- |
| [concepts/chunking-strategies.md](concepts/chunking-strategies.md)       | Chunking approaches for the 9-source enterprise corpus        |
| [concepts/lexical-vs-semantic.md](concepts/lexical-vs-semantic.md)       | BM25 (lexical) vs dense embedding (semantic) trade-offs       |
| [concepts/hybrid-score-fusion.md](concepts/hybrid-score-fusion.md)       | RRF, convex combination, and DBSF fusion algorithms           |
| [concepts/metadata-filtering.md](concepts/metadata-filtering.md)         | Pre- vs post-filter mechanics per vector store                |
| [concepts/retrieval-eval-metrics.md](concepts/retrieval-eval-metrics.md) | Recall@k, Precision@k, MRR, nDCG — formulas and scope         |
| [concepts/reranking.md](concepts/reranking.md)                           | Cross-encoder reranking and when to skip it                   |
| [concepts/frontier-2026.md](concepts/frontier-2026.md)                   | Learned-sparse, ColBERT, LLM rerankers, BRIGHT — not in scope |

### Patterns

| File                                                                     | Purpose                                      |
| ------------------------------------------------------------------------ | -------------------------------------------- |
| [patterns/hybrid-retrieve-fuse.md](patterns/hybrid-retrieve-fuse.md)     | bm25s + sentence-transformers + RRF pipeline |
| [patterns/expected-doc-ids-smoke.md](patterns/expected-doc-ids-smoke.md) | Chunk-to-doc deduplication recall smoke test |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — Fast lookup tables

---

---

## Architecture Decision

- [docs/adr/0002-retrieval-architecture.md](../../../../docs/adr/0002-retrieval-architecture.md) — accepted; LanceDB + BGE-M3 + bm25s + RRF

---

## Key Invariants

- `Document.id` (= dataset `doc_id`) is the deduplication key for `expected_doc_ids` scoring.
- Evaluate at document level after dedup — never raw chunk level.
- RRF k=60 is the default smoothing constant; over-fetch 3× per retriever before fusing.
- Encode once at build time (`make build-index`); query time opens persisted artifacts (NFR-1).
- One ordered `list[Chunk]` from `chunk_documents()` anchors BM25, `.npy`, and LanceDB rows.
