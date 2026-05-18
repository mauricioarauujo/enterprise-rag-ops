# RAG Retrieval Quick Reference

> Fast lookup tables. For full rationale, see linked concept files.

## Chunking Parameters

| Parameter         | Default                         | Fallback                           | Notes                                    |
| ----------------- | ------------------------------- | ---------------------------------- | ---------------------------------------- |
| Child chunk size  | 256 tokens                      | 512 tokens                         | Fallback only for narrative-heavy docs   |
| Child overlap     | 32 tokens (12.5%)               | 50 tokens (10%)                    | Always align to sentence/struct boundary |
| Parent chunk size | 1024 tokens or section boundary | 800–1200 tokens (complete section) | Email threads, Jira tickets, Confluence  |
| Chunk-to-doc key  | `Document.id` (= `doc_id`)      | —                                  | Codebase contract: `schema.py`           |

## Embedding Models

| Model                 | Dims         | Context  | MTEB Retrieval | Use                              |
| --------------------- | ------------ | -------- | -------------- | -------------------------------- |
| BGE-M3                | 1024         | 8192 tok | ~63.0          | Default; multi-source robustness |
| nomic-embed-text-v1.5 | 64–768 (MRL) | 8192 tok | 62.39          | Fallback; CPU-friendly           |
| BGE-large-en-v1.5     | 1024         | 512 tok  | 64.11          | English-only, short docs         |

## Score Fusion

| Method         | Needs calibration | Robust to outliers | Use when                        |
| -------------- | ----------------- | ------------------ | ------------------------------- |
| RRF (k=60)     | No                | Yes                | Default — no tuning available   |
| Convex (alpha) | Yes               | No                 | Score distributions are stable  |
| DBSF           | No                | Yes                | Scores are calibrated per-query |

## Retrieval Metrics — Formulas

| Metric      | Formula (textual)                   | Primary signal     |
| ----------- | ----------------------------------- | ------------------ |
| Recall@k    | \|relevant ∩ top-k\| / \|relevant\| | Coverage           |
| Precision@k | \|relevant ∩ top-k\| / k            | Exactness          |
| MRR         | avg(1 / rank of first hit)          | First-hit position |
| nDCG@k      | DCG@k / IDCG@k (log2 discount)      | Ranking quality    |

**Evaluation depth**: k = 10 (effective proxy for standard LLM context limits).
**Abstention threshold**: cosine similarity < 0.45 → return empty list (reject as unanswerable).
**Rerank skip**: top-1 normalized dense similarity > 0.90 → skip reranker (effective exact match).

## Component Defaults (Consolidated)

| Component      | Primary              | Fallback                                    |
| -------------- | -------------------- | ------------------------------------------- |
| Score fusion   | RRF (k=60)           | DBSF                                        |
| Vector store   | LanceDB (in-process) | Qdrant (when vector count exceeds ~1M)      |
| Lexical engine | bm25s                | Qdrant sparse vectors                       |
| Reranker       | BGE Reranker v2-m3   | ms-marco-MiniLM-L-6-v2 (CPU / tight budget) |

## Vector Store Decision Matrix (ADR-002 input)

| Criterion      | LanceDB              | Qdrant                | pgvector                |
| -------------- | -------------------- | --------------------- | ----------------------- |
| Hybrid search  | Built-in             | Native sparse+dense   | Manual SQL union        |
| Deployment     | Embedded (no server) | Docker / cloud        | PostgreSQL extension    |
| Dev ergonomics | Excellent            | Strong SDK            | Complex SQL             |
| RAM footprint  | Low (disk-based)     | High (HNSW in RAM)    | High (vertical)         |
| Best for       | Dev / small subset   | Production / high QPS | Existing Postgres infra |

## Common Pitfalls

| Don't                                              | Do                                               |
| -------------------------------------------------- | ------------------------------------------------ |
| Evaluate at chunk level against `expected_doc_ids` | Deduplicate chunk hits to `doc_id` first         |
| Post-filter metadata after vector search           | Pre-filter before scoring to guarantee k results |
| Copy broken `![][imageN]` refs from research       | Use qualitative bounds; flag as unrecovered      |
| Skip over-fetch before RRF                         | Fetch 3–5× target k per retriever before fusing  |

## Related Documentation

| Topic               | Path                                 |
| ------------------- | ------------------------------------ |
| Chunking strategies | `concepts/chunking-strategies.md`    |
| Score fusion        | `concepts/hybrid-score-fusion.md`    |
| Eval metrics        | `concepts/retrieval-eval-metrics.md` |
| Full index          | `index.md`                           |
