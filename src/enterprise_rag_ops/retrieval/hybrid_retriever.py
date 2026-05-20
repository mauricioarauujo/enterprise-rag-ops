"""Hybrid retriever: BM25 + dense → RRF → doc-level dedup → abstention.

Implements the `Retriever` Protocol. Composition is by injection — every
swappable dependency (`Embedder`, `VectorStore`) is a constructor parameter, so
the CI pipeline-contract test wires a stub embedder + an in-memory vector store
through the same path the production build uses (FR-11, NFR-4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.bm25_index import BM25Index
from enterprise_rag_ops.retrieval.interfaces import Embedder, VectorStore


def rrf_fuse(
    ranked_lists: list[list[tuple[str, int]]],
    k: int = config.RRF_K,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over `[(chunk_id, rank)]` lists.

    Score for each chunk = sum of `1 / (k + rank)` across lists. `k=60` is the
    Cormack et al. default — see `kb/rag-retrieval/concepts/hybrid-score-fusion.md`.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for chunk_id, rank in ranked:
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def deduplicate_to_docs(
    fused_chunks: list[tuple[str, float]],
    chunk_to_doc: Mapping[str, str],
) -> list[tuple[str, float]]:
    """Collapse a ranked chunk list to a ranked unique-doc list (first wins).

    First occurrence preserves rank — required by FR-6 and the smoke gate's
    `Recall@k` definition.
    """
    seen: set[str] = set()
    result: list[tuple[str, float]] = []
    for chunk_id, score in fused_chunks:
        doc_id = chunk_to_doc[chunk_id]
        if doc_id not in seen:
            seen.add(doc_id)
            result.append((doc_id, score))
    return result


class HybridRetriever:
    """`Retriever` implementation — BM25 + dense, RRF-fused, doc-deduplicated.

    `reranker` is a composability placeholder (FR-8) — Phase 2 ships no
    reranker; a Sprint 2 cross-encoder is a drop-in.
    """

    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        bm25_index: BM25Index,
        chunk_to_doc: Mapping[str, str],
        chunk_to_source_type: Mapping[str, str],
        reranker: Any = None,
        abstention_threshold: float = config.ABSTENTION_THRESHOLD,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._bm25_index = bm25_index
        self._chunk_to_doc = chunk_to_doc
        self._chunk_to_source_type = chunk_to_source_type
        self._reranker = reranker
        self._abstention_threshold = abstention_threshold

    def retrieve(
        self,
        query: str,
        top_k: int = config.TOP_K,
        source_type_filter: str | None = None,
    ) -> list[tuple[str, float]]:
        """Run the full hybrid pipeline; return up to `top_k` `(doc_id, score)`.

        Order of operations:
          1. Over-fetch from BM25 + dense (each fetches `top_k * OVER_FETCH`).
             Dense applies the source-type pre-filter inside LanceDB (FR-7);
             BM25 has no native filter, so we post-filter via `chunk_to_source_type`.
          2. Abstention gate on the top-1 *dense cosine* (FR-9): if the gate
             fires (no dense hits OR best < threshold), return [].
          3. RRF-fuse (k=60).
          4. Dedup chunks to docs (first occurrence wins).
          5. Truncate to `top_k`.
        """
        over_fetch = top_k * config.OVER_FETCH
        query_vector = self._embedder.encode([query])[0]

        dense_hits = self._vector_store.dense_search(
            query_vector=query_vector,
            k=over_fetch,
            source_type_filter=source_type_filter,
        )
        # FR-9: top-1 dense cosine drives abstention. An empty filtered set is
        # treated as "no confident match" — return [] (DESIGN risk: AC-8 + AC-9
        # must both hold when a filter empties the candidate set).
        if not dense_hits or dense_hits[0][1] < self._abstention_threshold:
            return []

        bm25_hits = self._bm25_index.search(query, k=over_fetch)
        if source_type_filter is not None:
            bm25_hits = [
                (chunk_id, rank)
                for chunk_id, rank in bm25_hits
                if self._chunk_to_source_type.get(chunk_id) == source_type_filter
            ]
            # Re-rank densely after filtering so RRF sees consecutive ranks.
            bm25_hits = [(chunk_id, rank + 1) for rank, (chunk_id, _) in enumerate(bm25_hits)]

        dense_ranked = [(chunk_id, rank + 1) for rank, (chunk_id, _) in enumerate(dense_hits)]
        fused = rrf_fuse([bm25_hits, dense_ranked])
        doc_ranked = deduplicate_to_docs(fused, self._chunk_to_doc)
        return doc_ranked[:top_k]
