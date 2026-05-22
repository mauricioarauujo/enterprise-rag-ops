"""Tests for `HybridRetriever` — covers FR-6 through FR-10 and the AC-7 to AC-10 row.

Uses LanceDB in `tmp_path` and the `StubEmbedder` — no network, no model
download, fast enough for `make verify`.
"""

from __future__ import annotations

from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.bm25_index import BM25Index
from enterprise_rag_ops.retrieval.chunker import chunk_documents
from enterprise_rag_ops.retrieval.hybrid_retriever import (
    HybridRetriever,
    deduplicate_to_best_chunk,
    deduplicate_to_docs,
    rrf_fuse,
)
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore


def _build_retriever(
    tmp_path, documents, embedder, abstention_threshold=config.ABSTENTION_THRESHOLD
):
    chunks = chunk_documents(documents)
    vectors = embedder.encode([c.text for c in chunks])
    doc_source_type = {d.id: d.source_type for d in documents}
    store = LanceDBStore(tmp_path / "lancedb")
    store.add(
        chunks=chunks,
        vectors=vectors,
        source_types=[doc_source_type[c.doc_id] for c in chunks],
    )
    bm25 = BM25Index.build(chunks)
    chunk_to_doc = {c.chunk_id: c.doc_id for c in chunks}
    chunk_to_source_type = {c.chunk_id: doc_source_type[c.doc_id] for c in chunks}
    return HybridRetriever(
        embedder=embedder,
        vector_store=store,
        bm25_index=bm25,
        chunk_to_doc=chunk_to_doc,
        chunk_to_source_type=chunk_to_source_type,
        abstention_threshold=abstention_threshold,
    )


def test_rrf_fuse_combines_ranks():
    fused = rrf_fuse([[("a", 1), ("b", 2)], [("b", 1), ("a", 2)]], k=60)
    # Both chunks appear in both lists; equal scores → both present, deterministic order.
    chunk_ids = [chunk_id for chunk_id, _ in fused]
    assert set(chunk_ids) == {"a", "b"}


def test_rrf_fuse_higher_rank_wins():
    fused = rrf_fuse([[("a", 1), ("b", 5)]], k=60)
    assert fused[0][0] == "a"


def test_deduplicate_to_docs_keeps_first_rank():
    fused = [("c1::0", 0.9), ("c1::1", 0.8), ("c2::0", 0.7)]
    chunk_to_doc = {"c1::0": "c1", "c1::1": "c1", "c2::0": "c2"}
    result = deduplicate_to_docs(fused, chunk_to_doc)
    assert result == [("c1", 0.9), ("c2", 0.7)]


def test_deduplicate_to_best_chunk_keeps_winning_chunk_id():
    """The winning (highest-ranked) chunk per doc is retained — not the lex-first."""
    # c1::5 outranks c1::0, so it must represent doc c1 (the bug the smoke caught).
    fused = [("c1::5", 0.9), ("c1::0", 0.8), ("c2::3", 0.7)]
    chunk_to_doc = {"c1::5": "c1", "c1::0": "c1", "c2::3": "c2"}
    result = deduplicate_to_best_chunk(fused, chunk_to_doc)
    assert result == [("c1::5", "c1", 0.9), ("c2::3", "c2", 0.7)]


def test_retrieve_chunks_returns_chunk_doc_score_unique_docs(
    tmp_path, synthetic_documents, stub_embedder
):
    """retrieve_chunks: (chunk_id, doc_id, score), one chunk per doc, in rank order."""
    retriever = _build_retriever(
        tmp_path, synthetic_documents, stub_embedder, abstention_threshold=-1.0
    )
    hits = retriever.retrieve_chunks("PTO policy company", top_k=5)
    assert hits, "expected non-empty chunk hits"
    assert all(len(h) == 3 for h in hits)
    doc_ids = [doc_id for _chunk_id, doc_id, _score in hits]
    assert len(doc_ids) == len(set(doc_ids)), "one chunk per doc"
    # Each returned chunk_id belongs to its reported doc_id.
    for chunk_id, doc_id, _score in hits:
        assert chunk_id.startswith(doc_id)


def test_retrieve_chunks_abstains_when_below_threshold(
    tmp_path, synthetic_documents, stub_embedder
):
    """retrieve_chunks honors the same abstention gate as retrieve (FR-9)."""
    retriever = _build_retriever(
        tmp_path, synthetic_documents, stub_embedder, abstention_threshold=0.999
    )
    assert retriever.retrieve_chunks("unrelated to any document", top_k=5) == []


def test_retrieve_returns_unique_doc_ids(tmp_path, synthetic_documents, stub_embedder):
    """AC-7: at most top_k pairs, no duplicate doc_id, after fuse + dedup."""
    retriever = _build_retriever(
        tmp_path, synthetic_documents, stub_embedder, abstention_threshold=-1.0
    )
    results = retriever.retrieve("PTO policy company", top_k=5)
    doc_ids = [doc_id for doc_id, _ in results]
    assert len(doc_ids) <= 5
    assert len(doc_ids) == len(set(doc_ids))


def test_retrieve_source_type_filter_restricts_docs(tmp_path, synthetic_documents, stub_embedder):
    """AC-8: source_type_filter='slack' returns only slack docs."""
    retriever = _build_retriever(
        tmp_path, synthetic_documents, stub_embedder, abstention_threshold=-1.0
    )
    slack_doc_ids = {d.id for d in synthetic_documents if d.source_type == "slack"}
    results = retriever.retrieve("deploy freeze standup", top_k=10, source_type_filter="slack")
    assert results, "expected at least one slack hit"
    assert all(doc_id in slack_doc_ids for doc_id, _ in results)


def test_retrieve_abstains_when_top_cosine_below_threshold(
    tmp_path, synthetic_documents, stub_embedder
):
    """AC-9: top-1 dense cosine below threshold → empty list.

    StubEmbedder yields ~orthogonal vectors for unrelated text, so an absurdly
    high threshold simulates "no confident match" without needing BGE-M3.
    """
    retriever = _build_retriever(
        tmp_path, synthetic_documents, stub_embedder, abstention_threshold=0.999
    )
    results = retriever.retrieve("a query unrelated to any corpus document", top_k=5)
    assert results == []


def test_retrieve_with_filter_that_empties_candidates_returns_empty(
    tmp_path, synthetic_documents, stub_embedder
):
    """DESIGN risk: abstention + filter interaction — must not error when set is empty."""
    retriever = _build_retriever(
        tmp_path, synthetic_documents, stub_embedder, abstention_threshold=-1.0
    )
    results = retriever.retrieve("anything", top_k=5, source_type_filter="nonexistent_source")
    assert results == []


def test_retrieve_reranker_none_is_default_path(tmp_path, synthetic_documents, stub_embedder):
    """AC-10: passing reranker=None is the default — output unchanged."""
    chunks = chunk_documents(synthetic_documents)
    vectors = stub_embedder.encode([c.text for c in chunks])
    doc_source_type = {d.id: d.source_type for d in synthetic_documents}
    store = LanceDBStore(tmp_path / "lancedb")
    store.add(
        chunks=chunks,
        vectors=vectors,
        source_types=[doc_source_type[c.doc_id] for c in chunks],
    )
    bm25 = BM25Index.build(chunks)
    chunk_to_doc = {c.chunk_id: c.doc_id for c in chunks}
    chunk_to_source_type = {c.chunk_id: doc_source_type[c.doc_id] for c in chunks}

    default = HybridRetriever(
        embedder=stub_embedder,
        vector_store=store,
        bm25_index=bm25,
        chunk_to_doc=chunk_to_doc,
        chunk_to_source_type=chunk_to_source_type,
        abstention_threshold=-1.0,
    )
    explicit_none = HybridRetriever(
        embedder=stub_embedder,
        vector_store=store,
        bm25_index=bm25,
        chunk_to_doc=chunk_to_doc,
        chunk_to_source_type=chunk_to_source_type,
        reranker=None,
        abstention_threshold=-1.0,
    )
    assert default.retrieve("PTO policy", top_k=5) == explicit_none.retrieve("PTO policy", top_k=5)
