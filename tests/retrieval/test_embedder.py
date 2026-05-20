"""Tests for `StubEmbedder` — the CI seam (FR-11, RQ-5).

`BGEEmbedder` is exercised by `make retrieval-smoke`, not here — instantiating
it downloads 568 MB, which `make verify` must not do (NFR-3).
"""

from __future__ import annotations

import numpy as np

from enterprise_rag_ops.retrieval.embedder import StubEmbedder
from enterprise_rag_ops.retrieval.interfaces import Embedder


def test_stub_embedder_satisfies_protocol():
    embedder = StubEmbedder(dim=32)
    assert isinstance(embedder, Embedder)


def test_stub_embedder_shape_and_dtype():
    embedder = StubEmbedder(dim=32)
    vectors = embedder.encode(["alpha", "beta", "gamma"])
    assert vectors.shape == (3, 32)
    assert vectors.dtype == np.float32


def test_stub_embedder_is_deterministic():
    embedder_1 = StubEmbedder(dim=32)
    embedder_2 = StubEmbedder(dim=32)
    np.testing.assert_array_equal(embedder_1.encode(["alpha"]), embedder_2.encode(["alpha"]))


def test_stub_embedder_vectors_are_normalized():
    """L2-normalized so dot products are cosine similarities (DESIGN risk: stub fidelity)."""
    vectors = StubEmbedder(dim=64).encode(["alpha", "beta", "gamma"])
    norms = np.linalg.norm(vectors, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_stub_embedder_different_inputs_yield_different_vectors():
    vectors = StubEmbedder(dim=64).encode(["alpha", "beta"])
    assert not np.allclose(vectors[0], vectors[1])
