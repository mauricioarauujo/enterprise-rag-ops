"""BM25 lexical index — thin wrapper over `bm25s` (FR-3).

`bm25s.retrieve` returns *corpus positions*, not chunk IDs. The ordered chunk
list passed to `build` is the single source of truth for position↔chunk_id
mapping (a DESIGN risk we pin by construction).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import bm25s

from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.schema import Chunk


class BM25Index:
    """Lexical index over a fixed ordered list of chunks.

    The class owns three things together: the `bm25s.BM25` retriever, the chunk
    IDs in *insertion order*, and the persistence layout. They must be saved
    and loaded together — splitting them is what causes mismatched-ID fusion.
    """

    _CHUNK_IDS_FILE = "chunk_ids.txt"

    def __init__(self, retriever: bm25s.BM25, chunk_ids: list[str]) -> None:
        self._retriever = retriever
        self._chunk_ids = chunk_ids

    @classmethod
    def build(cls, chunks: Sequence[Chunk]) -> BM25Index:
        """Tokenize and index `chunks` in their given order."""
        texts = [c.text for c in chunks]
        tokens = bm25s.tokenize(texts, stopwords="en")
        retriever = bm25s.BM25(method=config.BM25_METHOD, k1=config.BM25_K1, b=config.BM25_B)
        retriever.index(tokens)
        return cls(retriever=retriever, chunk_ids=[c.chunk_id for c in chunks])

    def save(self, path: Path) -> None:
        """Persist the BM25 index and the chunk-id order sidecar."""
        path.mkdir(parents=True, exist_ok=True)
        self._retriever.save(str(path))
        (path / self._CHUNK_IDS_FILE).write_text("\n".join(self._chunk_ids), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BM25Index:
        """Reload a persisted BM25 index with mmap for low memory overhead."""
        retriever = bm25s.BM25.load(str(path), mmap=True)
        chunk_ids = (path / cls._CHUNK_IDS_FILE).read_text(encoding="utf-8").splitlines()
        return cls(retriever=retriever, chunk_ids=chunk_ids)

    def search(self, query: str, k: int) -> list[tuple[str, int]]:
        """Return `(chunk_id, rank)` pairs with rank starting at 1 (best = 1)."""
        q_tokens = bm25s.tokenize([query], stopwords="en")
        # bm25s requires k <= corpus size; clamp defensively.
        effective_k = min(k, len(self._chunk_ids))
        if effective_k == 0:
            return []
        positions, _scores = self._retriever.retrieve(q_tokens, k=effective_k)
        return [(self._chunk_ids[int(pos)], rank + 1) for rank, pos in enumerate(positions[0])]

    @property
    def size(self) -> int:
        return len(self._chunk_ids)
