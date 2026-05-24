"""Two `Embedder` implementations.

`BGEEmbedder` is the production path: BGE-M3 via `sentence-transformers`, used
by `make build-index` and `make retrieval-smoke`. `StubEmbedder` is a
deterministic hash-based encoder injected into the CI pipeline-contract test
(RQ-5): same Protocol shape, normalized vectors, no model download — the stub
exercises the same cosine math as BGE-M3, so the abstention gate and dedup
logic are genuinely covered (DESIGN risk: stub fidelity).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from enterprise_rag_ops.retrieval import config


class BGEEmbedder:
    """BGE-M3 via `sentence-transformers`. The 568 MB model is downloaded once.

    Instantiating this triggers the download — done deliberately at build/
    smoke time, never in CI (NFR-3).
    """

    def __init__(self, model_name: str = config.EMBEDDING_MODEL) -> None:
        # Imported lazily so `make test` (with the stub) never imports torch.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = config.EMBEDDING_DIM

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.astype(np.float32, copy=False)


class StubEmbedder:
    """Deterministic hash-based encoder satisfying `Embedder` (FR-11, RQ-5).

    Each text is mapped to a fixed-`dim` vector by seeding numpy's RNG with
    BLAKE2b(text); the vector is L2-normalized so dot products are cosine
    similarities — the same code path BGE-M3 exercises. Same input → identical
    vector → CI runs are reproducible.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = np.empty((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            seed = int.from_bytes(
                hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
            )
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            norm = float(np.linalg.norm(v))
            vectors[i] = v / norm if norm > 0 else v
        return vectors
