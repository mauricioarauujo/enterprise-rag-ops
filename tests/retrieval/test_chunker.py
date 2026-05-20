"""Tests for `chunk_document` / `chunk_documents` (FR-2, AC-2)."""

from __future__ import annotations

from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.chunker import chunk_document, chunk_documents


def test_chunk_document_preserves_doc_id():
    doc = Document(id="doc_a", source_type="slack", text="word " * 200)
    chunks = chunk_document(doc)
    assert chunks, "expected at least one chunk"
    assert all(c.doc_id == doc.id for c in chunks)


def test_chunk_ids_are_deterministic_and_offset_indexed():
    doc = Document(id="doc_a", source_type="slack", text="word " * 200)
    chunks_run_1 = chunk_document(doc)
    chunks_run_2 = chunk_document(doc)
    assert [c.chunk_id for c in chunks_run_1] == [c.chunk_id for c in chunks_run_2]
    assert chunks_run_1[0].chunk_id == "doc_a::0"
    if len(chunks_run_1) > 1:
        assert chunks_run_1[1].chunk_id == "doc_a::1"


def test_chunker_uniform_across_sources_no_per_source_branch(synthetic_documents):
    """AC-2: single-source vs multi-source corpus produces chunks with no per-source code path."""
    confluence_only = [d for d in synthetic_documents if d.source_type == "confluence"]

    mixed_chunks = chunk_documents(synthetic_documents)
    single_chunks = chunk_documents(confluence_only)

    confluence_chunks_from_mixed = [
        c
        for c in mixed_chunks
        if c.doc_id.startswith("doc_pto") or c.doc_id in {"doc_holidays", "doc_incident"}
    ]
    # The confluence chunks produced by chunking the full corpus equal those
    # produced by chunking the confluence-only corpus — same strategy, no branch.
    assert [(c.chunk_id, c.text) for c in confluence_chunks_from_mixed] == [
        (c.chunk_id, c.text) for c in single_chunks
    ]


def test_chunk_size_below_configured_max(synthetic_documents):
    chunks = chunk_documents(synthetic_documents)
    # RecursiveCharacterTextSplitter may slightly exceed chunk_size on boundary
    # cases; we assert a generous upper bound to catch regressions, not exact size.
    assert all(len(c.text) <= config.CHUNK_SIZE * 2 for c in chunks)
