# Lexical vs Semantic Retrieval

> **Purpose**: BM25 vs dense embedding — when each wins and why hybrid is required.
> **Confidence**: HIGH — research, bm25s docs (pillar 2), and sentence-transformers
> docs agree on the core trade-offs. BM25 k1/b defaults confirmed by bm25s library docs.
> **MCP Validated**: 2026-05-17

## Overview

Neither BM25 nor dense retrieval alone is sufficient for the 9-source enterprise
corpus. BM25 fails on vocabulary mismatch (synonym queries miss exact-term docs);
dense retrieval fails on exact identifiers (Jira keys, error codes, acronyms). Hybrid
is the canonical baseline.

## BM25 — Lexical

BM25 scores relevance by term frequency (TF) with saturation and document length
normalization. Key parameters (confirmed by bm25s library docs):

| Parameter | Default                   | Effect                                          |
| --------- | ------------------------- | ----------------------------------------------- |
| `k1`      | 1.2–2.0 (1.5 recommended) | TF saturation: lower = softer saturation        |
| `b`       | 0.75                      | Length normalization: 0 = none, 1 = full        |
| `method`  | `lucene` in bm25s         | Scoring variant; Robertson is IR-book canonical |

**Wins**: exact jargon, identifiers (`PROJ-104`), product names, error codes.
**Fails**: paraphrase queries ("vacation" vs "PTO"), cross-lingual synonymy.

## Dense Embedding — Semantic

Dense retrieval maps text to a continuous vector; similarity is cosine or dot product.
Recommended models for this project (confidence: HIGH from research + MTEB):

| Model                 | Dims         | Context  | MTEB Retrieval | Notes                            |
| --------------------- | ------------ | -------- | -------------- | -------------------------------- |
| **BGE-M3**            | 1024         | 8192 tok | ~63.0          | Default; multi-source robustness |
| nomic-embed-text-v1.5 | 64–768 (MRL) | 8192 tok | 62.39          | Fallback; CPU-friendly           |

BGE-M3 is preferred because the corpus spans radically different styles (code,
chat, formal docs) and BGE-M3 is specifically trained for multi-task / multi-domain
transfer robustness.

**Wins**: semantic synonymy, paraphrase, cross-source concept matching.
**Fails**: rare exact identifiers with no semantic neighborhood in the embedding space.

## Matryoshka Representation Learning (MRL)

Models like nomic-embed-text-v1.5 support truncating the output vector (e.g., 768 →
64 dims) while preserving most retrieval recall. Useful for reducing index size on a
hardware-constrained dev machine. BGE-M3 does not natively support MRL.

## Library Selection — bm25s vs rank_bm25

| Aspect        | bm25s                                        | rank_bm25          |
| ------------- | -------------------------------------------- | ------------------ |
| Speed         | Up to ~500× faster (confirmed by bm25s docs) | Baseline           |
| RAM           | Memory-mapped (low)                          | In-memory (higher) |
| Serialization | SciPy sparse matrix on disk + mmap reload    | In-memory pickle   |
| API           | `bm25s.BM25`, `bm25s.tokenize`               | `BM25Okapi` etc.   |

**Use bm25s** for Phase 2. Its `mmap=True` load path is critical for keeping a
large index off RAM on dev hardware.

## Related

- [hybrid-score-fusion.md](hybrid-score-fusion.md)
- [patterns/hybrid-retrieve-fuse.md](../patterns/hybrid-retrieve-fuse.md)
