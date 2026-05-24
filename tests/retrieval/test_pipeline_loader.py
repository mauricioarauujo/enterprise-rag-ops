"""Regression tests for `load_retriever` (FR-9, FR-11c, AC-11).

Asserts that `load_retriever` does not read or chunk the raw corpus,
but instead loads mappings from the sidecar and LanceDB.
"""

from __future__ import annotations

import pytest

from enterprise_rag_ops.ingest.writer import write_corpus
from enterprise_rag_ops.retrieval import config, pipeline
from enterprise_rag_ops.retrieval.chunker import chunk_documents
from enterprise_rag_ops.retrieval.pipeline import load_retriever


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    """Redirect every artifact path in `retrieval.config` to a tmp_path so the
    build pipeline runs hermetically — no touching of `data/processed/`."""
    processed = tmp_path / "processed"
    processed.mkdir()
    monkeypatch.setattr(config, "PROCESSED_DIR", processed)
    monkeypatch.setattr(config, "CORPUS_PATH", processed / "corpus.jsonl")
    monkeypatch.setattr(config, "BM25_INDEX_DIR", processed / "bm25_index")
    monkeypatch.setattr(config, "EMBEDDINGS_PATH", processed / "embeddings.npy")
    monkeypatch.setattr(config, "CHUNK_ORDER_PATH", processed / "embeddings.chunks.json")
    monkeypatch.setattr(config, "LANCEDB_DIR", processed / "lancedb")
    return processed


def test_load_retriever_no_corpus_read_or_chunk(
    temp_paths, synthetic_documents, stub_embedder, monkeypatch
):
    # 1. Build the index first so we have persisted artifacts.
    write_corpus(synthetic_documents, config.CORPUS_PATH)
    pipeline.build_index(force=False, embedder=stub_embedder)

    # 2. Spy on read_corpus in pipeline.py
    read_called = False
    original_read_corpus = pipeline.read_corpus

    def spy_read_corpus(*args, **kwargs):
        nonlocal read_called
        read_called = True
        return original_read_corpus(*args, **kwargs)

    monkeypatch.setattr(pipeline, "read_corpus", spy_read_corpus)

    # 3. Call load_retriever
    retriever = load_retriever(embedder=stub_embedder)
    assert retriever is not None

    # 4. Assert read_corpus was NOT called during load_retriever
    assert not read_called, "load_retriever re-read the corpus from disk!"

    # 5. Verify the reconstructed maps are correct
    expected_chunks = chunk_documents(synthetic_documents)
    doc_source_type = {doc.id: doc.source_type for doc in synthetic_documents}

    for chunk in expected_chunks:
        assert retriever._chunk_to_doc[chunk.chunk_id] == chunk.doc_id
        assert retriever._chunk_to_source_type[chunk.chunk_id] == doc_source_type[chunk.doc_id]
