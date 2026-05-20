"""Tests for `LanceDBStore` (FR-5, FR-7, AC-6).

LanceDB is local/embedded — no network needed for these tests.
"""

from __future__ import annotations

from enterprise_rag_ops.retrieval.chunker import chunk_documents
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore


def _build_store(tmp_path, documents, embedder):
    chunks = chunk_documents(documents)
    vectors = embedder.encode([c.text for c in chunks])
    doc_source_type = {d.id: d.source_type for d in documents}
    store = LanceDBStore(tmp_path / "lancedb")
    store.add(
        chunks=chunks,
        vectors=vectors,
        source_types=[doc_source_type[c.doc_id] for c in chunks],
    )
    return store, chunks, vectors


def test_lancedb_add_then_dense_search_returns_self_at_top(
    tmp_path, synthetic_documents, stub_embedder
):
    store, chunks, vectors = _build_store(tmp_path, synthetic_documents, stub_embedder)
    # Searching with a chunk's own vector must return that chunk first.
    hits = store.dense_search(query_vector=vectors[0], k=3)
    assert hits[0][0] == chunks[0].chunk_id
    # Cosine similarity of a vector with itself is ~1.0 (StubEmbedder is normalized).
    assert hits[0][1] > 0.99


def test_lancedb_source_type_prefilter_restricts_results(
    tmp_path, synthetic_documents, stub_embedder
):
    """AC-8 (vector-store half): only chunks of the requested source_type are returned."""
    store, chunks, vectors = _build_store(tmp_path, synthetic_documents, stub_embedder)
    doc_source_type = {d.id: d.source_type for d in synthetic_documents}
    chunk_id_to_source = {c.chunk_id: doc_source_type[c.doc_id] for c in chunks}

    hits = store.dense_search(query_vector=vectors[0], k=20, source_type_filter="slack")
    assert hits, "expected at least one slack hit"
    assert all(chunk_id_to_source[chunk_id] == "slack" for chunk_id, _ in hits)


def test_lancedb_open_reuses_existing_table(tmp_path, synthetic_documents, stub_embedder):
    """AC-3-adjacent: a fresh process can open the persisted table without rebuilding."""
    _build_store(tmp_path, synthetic_documents, stub_embedder)
    reopened = LanceDBStore.open(tmp_path / "lancedb")
    # Query through the reopened handle; a None table would raise.
    chunks = chunk_documents(synthetic_documents)
    vectors = stub_embedder.encode([chunks[0].text])
    hits = reopened.dense_search(query_vector=vectors[0], k=1)
    assert hits
