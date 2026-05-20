# Hybrid Retrieve-Fuse Pipeline

> **Purpose**: The Phase 2 build-time/query-time split — LanceDB + BM25 persisted,
> queried via `HybridRetriever`. Reflects shipping code in
> `src/enterprise_rag_ops/retrieval/`.
> **Codebase Grounded**: 2026-05-20 (Sprint 1 Phase 2 merged)

## When to Use

- Implementing or extending `HybridRetriever` and `pipeline.py`.
- Understanding the position↔chunk_id invariant across the three artifacts.
- Debugging abstention, fusion, or dedup behaviour.

## Build-Time: Encode Once, Persist Three Artifacts

`pipeline.build_index()` is the single orchestrator. All three artifacts are written
from **one ordered `list[Chunk]`** returned by `chunk_documents()`. That ordering is
the position↔chunk_id single source of truth — BM25, the `.npy` matrix, and LanceDB
rows all share it.

```python
# pipeline.py — build path (simplified)
from enterprise_rag_ops.retrieval.bm25_index import BM25Index
from enterprise_rag_ops.retrieval.embedder import BGEEmbedder
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore
from enterprise_rag_ops.retrieval.chunker import chunk_documents
from enterprise_rag_ops.retrieval import config

def build_index(force: bool = False, embedder=None) -> int:
    if config.LANCEDB_DIR.exists() and not force:
        return 0  # idempotent skip (FR-10)

    documents = list(read_corpus(config.CORPUS_PATH))
    chunks = chunk_documents(documents)          # one ordered list anchors everything

    # Artifact 1 — BM25 (position = index in chunks)
    bm25 = BM25Index.build(chunks)
    bm25.save(config.BM25_INDEX_DIR)            # saves with chunk_ids sidecar

    # Artifact 2 — Dense embeddings (encode once at build time, NFR-1)
    embedder = embedder or BGEEmbedder()
    vectors = embedder.encode([c.text for c in chunks])  # shape (N, 1024)
    np.save(config.EMBEDDINGS_PATH, vectors)

    # Artifact 3 — LanceDB (chunk_id, doc_id, source_type, text, vector)
    store = LanceDBStore(config.LANCEDB_DIR)
    doc_source_type = {doc.id: doc.source_type for doc in documents}
    store.add(
        chunks=chunks,
        vectors=vectors,
        source_types=[doc_source_type[c.doc_id] for c in chunks],
    )
    return len(chunks)
```

**Invariant**: `chunk_id = f"{doc_id}::{offset}"` where `offset` is the 0-based
position of the chunk within its source document. Deterministic; NFR-2.

## Query-Time: Load Persisted Artifacts, No Re-Encoding

`pipeline.load_retriever()` opens BM25, LanceDB, and the chunk-order sidecar from
disk. No corpus re-encoding happens at query time (NFR-1).

```python
# pipeline.py — query path (simplified)
def load_retriever(embedder=None) -> HybridRetriever:
    bm25 = BM25Index.load(config.BM25_INDEX_DIR)   # mmap=True (low RAM)
    store = LanceDBStore.open(config.LANCEDB_DIR)
    embedder = embedder or BGEEmbedder()

    # chunk_id → (doc_id, source_type) from corpus — O(corpus) once at startup
    chunk_to_doc, chunk_to_source_type = {}, {}
    for doc in read_corpus(config.CORPUS_PATH):
        for chunk in chunk_document(doc):
            chunk_to_doc[chunk.chunk_id] = doc.id
            chunk_to_source_type[chunk.chunk_id] = doc.source_type

    return HybridRetriever(
        embedder=embedder,
        vector_store=store,
        bm25_index=bm25,
        chunk_to_doc=chunk_to_doc,
        chunk_to_source_type=chunk_to_source_type,
    )
```

## `HybridRetriever.retrieve` — Full Pipeline

```python
# hybrid_retriever.py — retrieve (simplified)
def retrieve(self, query: str, top_k: int = 10,
             source_type_filter: str | None = None) -> list[tuple[str, float]]:
    over_fetch = top_k * config.OVER_FETCH     # default: 3×
    query_vector = self._embedder.encode([query])[0]

    # Dense: query persisted LanceDB table; pre-filter if source_type given (FR-7)
    dense_hits = self._vector_store.dense_search(
        query_vector=query_vector, k=over_fetch,
        source_type_filter=source_type_filter,
    )  # returns [(chunk_id, cosine_similarity), ...]

    # Abstention gate: top-1 dense cosine < 0.45 → return [] (FR-9)
    if not dense_hits or dense_hits[0][1] < self._abstention_threshold:
        return []

    # BM25: post-filter by source_type (BM25 has no native filter)
    bm25_hits = self._bm25_index.search(query, k=over_fetch)
    if source_type_filter is not None:
        bm25_hits = [
            (cid, r) for cid, r in bm25_hits
            if self._chunk_to_source_type.get(cid) == source_type_filter
        ]
        bm25_hits = [(cid, r + 1) for r, (cid, _) in enumerate(bm25_hits)]

    # RRF(k=60): rank lists → fused chunk scores
    dense_ranked = [(cid, r + 1) for r, (cid, _) in enumerate(dense_hits)]
    fused = rrf_fuse([bm25_hits, dense_ranked])          # k=60 default

    # Chunk → doc dedup (first occurrence wins) → truncate
    doc_ranked = deduplicate_to_docs(fused, self._chunk_to_doc)
    return doc_ranked[:top_k]
```

## RRF and Dedup Functions

```python
def rrf_fuse(ranked_lists: list[list[tuple[str, int]]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for chunk_id, rank in ranked:
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)

def deduplicate_to_docs(fused_chunks, chunk_to_doc) -> list[tuple[str, float]]:
    seen: set[str] = set()
    result = []
    for chunk_id, score in fused_chunks:
        doc_id = chunk_to_doc[chunk_id]
        if doc_id not in seen:
            seen.add(doc_id)
            result.append((doc_id, score))
    return result
```

## Configuration

| Setting                | Value  | Source      |
| ---------------------- | ------ | ----------- |
| `RRF_K`                | 60     | `config.py` |
| `OVER_FETCH`           | 3      | `config.py` |
| `TOP_K`                | 10     | `config.py` |
| `ABSTENTION_THRESHOLD` | 0.45   | `config.py` |
| `EMBEDDING_MODEL`      | BGE-M3 | `config.py` |
| `EMBEDDING_DIM`        | 1024   | `config.py` |
| `BM25_METHOD`          | lucene | `config.py` |
| `BM25_K1`              | 1.5    | `config.py` |
| `BM25_B`               | 0.75   | `config.py` |

## Seams (ADR-002)

- `Embedder` Protocol — swap `BGEEmbedder` for `StubEmbedder` in CI (no model download).
- `VectorStore` Protocol — `LanceDBStore` is the sole impl; seam names the LanceDB→Qdrant swap.
- `Retriever` Protocol — Phase 3 generation depends on this contract; reranker is a drop-in.
- BM25 is **not** behind a seam — `bm25s` is local, file-based, not a swap candidate.

## See Also

- [concepts/hybrid-score-fusion.md](../concepts/hybrid-score-fusion.md)
- [concepts/lexical-vs-semantic.md](../concepts/lexical-vs-semantic.md)
- [patterns/expected-doc-ids-smoke.md](expected-doc-ids-smoke.md)
- `docs/adr/0002-retrieval-architecture.md` — accepted ADR
