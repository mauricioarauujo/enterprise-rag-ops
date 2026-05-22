"""Turn ranked chunk hits into a `list[Chunk]` for the prompt.

Consumes `HybridRetriever.retrieve_chunks` output — `(chunk_id, doc_id, score)`
tuples already ranked and deduplicated to the best chunk per doc. The assembler
fetches those exact chunks' text and caps to `max_chunks`, preserving fused-rank
order (RQ-9 as revised: the relevant chunk reaches the LLM, not a per-doc title).
"""

from __future__ import annotations

from enterprise_rag_ops.retrieval.interfaces import VectorStore
from enterprise_rag_ops.retrieval.schema import Chunk

DEFAULT_MAX_CHUNKS = 5


class ContextAssembler:
    """Fetch ranked chunks' text + truncate to `max_chunks` (FR-6, RQ-14)."""

    def __init__(self, store: VectorStore, max_chunks: int = DEFAULT_MAX_CHUNKS) -> None:
        if max_chunks <= 0:
            raise ValueError(f"max_chunks must be positive, got {max_chunks}")
        self._store = store
        self._max_chunks = max_chunks

    def assemble(self, chunk_hits: list[tuple[str, str, float]]) -> list[Chunk]:
        """Return up to `max_chunks` chunks in fused-rank order.

        - `chunk_hits` is `HybridRetriever.retrieve_chunks` output:
          `(chunk_id, doc_id, score)` tuples, best first, one per distinct doc.
        - Returns `[]` when `chunk_hits == []` — abstention is the CLI's
          responsibility, but the assembler is defensive.
        """
        if not chunk_hits:
            return []

        ranked_chunk_ids = [chunk_id for chunk_id, _doc_id, _score in chunk_hits][
            : self._max_chunks
        ]
        # One mechanical read; the store gives no ordering guarantee, so we
        # re-order to the ranked list we already hold.
        fetched = {c.chunk_id: c for c in self._store.fetch_chunks_by_chunk_ids(ranked_chunk_ids)}
        # Defensive: a chunk_id absent from the store (stale index) is skipped.
        return [fetched[cid] for cid in ranked_chunk_ids if cid in fetched]
