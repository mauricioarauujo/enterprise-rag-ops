"""Protocol seams for the retrieval stack.

Three small `Protocol`s isolate every dependency the design anticipates swapping
(ADR-002). They name the boundaries — they do not pre-build alternative
implementations. The three:

- `Embedder`: injectable so the CI pipeline-contract test uses a stub and the
  568 MB BGE-M3 download stays local (NFR-3).
- `VectorStore`: isolates LanceDB-specific code so the anticipated
  LanceDB→Qdrant swap is a new file, not a rewrite (NFR-4).
- `Retriever`: the contract Phase 3 generation will depend on; a future
  reranker or graph retriever is a drop-in.

BM25 is intentionally not behind a seam — `bm25s` is local, file-based, and
not a documented swap candidate. A seam there would be "in case", which the
engineering guidance rejects.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from enterprise_rag_ops.retrieval.schema import Chunk


@runtime_checkable
class Embedder(Protocol):
    """Encodes texts to a fixed-dimension dense matrix.

    Implementations must produce **normalized** vectors — `HybridRetriever` and
    the abstention gate treat dot products as cosine similarities (FR-9).
    """

    dim: int

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return an `(len(texts), dim)` float32 array of L2-normalized vectors."""
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Persisted dense index over chunks with metadata pre-filtering."""

    def add(
        self, chunks: Sequence[Chunk], vectors: np.ndarray, source_types: Sequence[str]
    ) -> None:
        """Insert chunks + their embeddings + parallel source_type column."""
        ...

    def dense_search(
        self,
        query_vector: np.ndarray,
        k: int,
        source_type_filter: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return up to `k` (chunk_id, cosine_similarity) pairs, best first.

        `source_type_filter`, when set, restricts the candidate set via a
        pre-filter on the indexed `source_type` column.
        """
        ...


@runtime_checkable
class Retriever(Protocol):
    """Query-time interface Phase 3 generation depends on."""

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        source_type_filter: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return up to `top_k` `(doc_id, fused_score)` pairs with no duplicate doc_id."""
        ...
