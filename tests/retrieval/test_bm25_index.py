"""Tests for `BM25Index` (FR-3, AC-5)."""

from __future__ import annotations

from enterprise_rag_ops.retrieval.bm25_index import BM25Index
from enterprise_rag_ops.retrieval.chunker import chunk_documents


def test_bm25_search_returns_chunk_ids_with_ranks(synthetic_documents):
    chunks = chunk_documents(synthetic_documents)
    index = BM25Index.build(chunks)
    results = index.search("PTO policy company", k=5)
    assert results, "expected BM25 hits for in-corpus query"
    assert all(rank >= 1 for _, rank in results)
    # The best hit (rank=1) should be a chunk of the PTO doc.
    top_chunk_id = results[0][0]
    assert top_chunk_id.startswith("doc_pto::")


def test_bm25_save_load_roundtrip_with_mmap(tmp_path, synthetic_documents):
    """AC-5: BM25 index is reloadable from disk with mmap=True without re-indexing."""
    chunks = chunk_documents(synthetic_documents)
    BM25Index.build(chunks).save(tmp_path / "bm25")

    reloaded = BM25Index.load(tmp_path / "bm25")
    assert reloaded.size == len(chunks)
    assert reloaded.search("PTO policy", k=3) == BM25Index.build(chunks).search("PTO policy", k=3)


def test_bm25_search_clamps_to_corpus_size(synthetic_documents):
    chunks = chunk_documents(synthetic_documents[:1])
    index = BM25Index.build(chunks)
    # k larger than corpus must not raise.
    results = index.search("anything", k=1000)
    assert len(results) <= index.size
