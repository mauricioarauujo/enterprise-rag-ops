# Hybrid Retrieve-Fuse Pipeline

> **Purpose**: bm25s + sentence-transformers + RRF — the Phase 2 retriever skeleton.
> **MCP Validated**: 2026-05-17

## When to Use

- Phase 2 retrieval module needs a concrete implementation starting point.
- Query contains mixed signals (exact Jira keys AND semantic intent).
- You need a retriever that works on the stratified corpus subset without a server.

## Implementation

```python
"""hybrid_retriever.py — Phase 2 skeleton.

Inputs:  list of Chunk (child) objects, each with .text and .doc_id
Outputs: ranked list of (doc_id, rrf_score) after deduplication
"""
from __future__ import annotations

import bm25s
from sentence_transformers import SentenceTransformer
import numpy as np
from dataclasses import dataclass
from typing import Sequence


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str          # = Document.id from schema.py — the dedup key
    text: str


def build_bm25_index(chunks: Sequence[Chunk]) -> tuple[bm25s.BM25, list[str]]:
    """Tokenize and index chunk texts. Save with mmap for RAM efficiency."""
    texts = [c.text for c in chunks]
    tokens = bm25s.tokenize(texts, stopwords="en")
    retriever = bm25s.BM25(method="lucene", k1=1.5, b=0.75)
    retriever.index(tokens)
    return retriever, texts


def bm25_retrieve(
    bm25: bm25s.BM25,
    query: str,
    chunks: Sequence[Chunk],
    top_n: int,
) -> list[tuple[str, int]]:
    """Return (chunk_id, rank) pairs — 1-indexed, best = 1."""
    q_tokens = bm25s.tokenize([query], stopwords="en")
    results, _ = bm25.retrieve(q_tokens, k=top_n)
    # results[0] = array of corpus positions
    return [(chunks[pos].chunk_id, rank + 1) for rank, pos in enumerate(results[0])]


def dense_retrieve(
    model: SentenceTransformer,
    query: str,
    chunks: Sequence[Chunk],
    top_n: int,
) -> list[tuple[str, int]]:
    """Encode corpus + query, return (chunk_id, rank) pairs."""
    corpus_embs = model.encode([c.text for c in chunks], normalize_embeddings=True)
    q_emb = model.encode([query], normalize_embeddings=True)
    sims = (q_emb @ corpus_embs.T)[0]          # cosine via dot product (normalized)
    top_indices = np.argsort(sims)[::-1][:top_n]
    return [(chunks[i].chunk_id, rank + 1) for rank, i in enumerate(top_indices)]


def rrf_fuse(
    ranked_lists: list[list[tuple[str, int]]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. k=60 is the industry-standard smoothing constant."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for chunk_id, rank in ranked:
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def deduplicate_to_docs(
    fused_chunks: list[tuple[str, float]],
    chunk_to_doc: dict[str, str],
) -> list[tuple[str, float]]:
    """Map chunk IDs -> doc IDs, keep first occurrence per doc (preserves rank)."""
    seen: set[str] = set()
    result: list[tuple[str, float]] = []
    for chunk_id, score in fused_chunks:
        doc_id = chunk_to_doc[chunk_id]
        if doc_id not in seen:
            seen.add(doc_id)
            result.append((doc_id, score))
    return result


def hybrid_retrieve(
    query: str,
    chunks: Sequence[Chunk],
    bm25: bm25s.BM25,
    model: SentenceTransformer,
    top_k: int = 10,
    over_fetch: int = 3,
) -> list[tuple[str, float]]:
    """Full pipeline: BM25 + dense -> RRF -> doc-level dedup.

    over_fetch: each retriever returns top_k * over_fetch candidates before RRF
    to ensure sufficient candidate overlap.
    """
    n = top_k * over_fetch
    bm25_ranked = bm25_retrieve(bm25, query, chunks, n)
    dense_ranked = dense_retrieve(model, query, chunks, n)
    fused = rrf_fuse([bm25_ranked, dense_ranked], k=60)
    chunk_to_doc = {c.chunk_id: c.doc_id for c in chunks}
    doc_ranked = deduplicate_to_docs(fused, chunk_to_doc)
    return doc_ranked[:top_k]
```

## Configuration

| Setting      | Default | Description                               |
| ------------ | ------- | ----------------------------------------- |
| `k1`         | 1.5     | BM25 TF saturation (IR book: 1.2–2.0)     |
| `b`          | 0.75    | BM25 length normalization                 |
| `k` (RRF)    | 60      | RRF smoothing constant; industry standard |
| `over_fetch` | 3       | Multiplier for pre-fusion candidate pool  |
| `top_k`      | 10      | Final returned doc count                  |

## Example Usage

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-m3")
bm25, texts = build_bm25_index(chunks)

results = hybrid_retrieve(
    query="What is the PTO policy?",
    chunks=chunks,
    bm25=bm25,
    model=model,
    top_k=10,
)
# results: [(doc_id, rrf_score), ...] — 10 unique Document.id values
```

## See Also

- [concepts/hybrid-score-fusion.md](../concepts/hybrid-score-fusion.md)
- [concepts/lexical-vs-semantic.md](../concepts/lexical-vs-semantic.md)
- [patterns/expected-doc-ids-smoke.md](expected-doc-ids-smoke.md)
