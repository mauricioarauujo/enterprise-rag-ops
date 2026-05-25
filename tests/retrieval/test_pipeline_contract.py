"""Pipeline-contract test — the offline wiring gate run by `make test` (FR-11, AC-11).

Asserts the full chunk → BM25 + dense → RRF fusion → chunk→doc_id dedup → top-k
wiring end-to-end, using only the `StubEmbedder` (no model download). Also
covers `build_index` idempotency (AC-4) on a tmp_path-scoped corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from enterprise_rag_ops.ingest.writer import write_corpus
from enterprise_rag_ops.retrieval import config, pipeline
from enterprise_rag_ops.retrieval.bm25_index import BM25Index
from enterprise_rag_ops.retrieval.chunker import chunk_documents
from enterprise_rag_ops.retrieval.hybrid_retriever import HybridRetriever
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore


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


def test_pipeline_contract_end_to_end(temp_paths, synthetic_documents, stub_embedder):
    """AC-11: chunk → BM25 + dense → RRF → dedup → top-k, no network, unique doc_ids."""
    write_corpus(synthetic_documents, config.CORPUS_PATH)

    chunks_indexed = pipeline.build_index(force=False, embedder=stub_embedder)
    assert chunks_indexed > 0

    # All three artifacts are present (AC-3).
    assert config.BM25_INDEX_DIR.exists()
    assert config.EMBEDDINGS_PATH.exists()
    assert config.LANCEDB_DIR.exists()

    # Wire a fresh retriever from the persisted artifacts (mirrors load_retriever
    # but with the stub embedder, no BGE-M3 download).
    bm25 = BM25Index.load(config.BM25_INDEX_DIR)
    store = LanceDBStore.open(config.LANCEDB_DIR)
    chunks = chunk_documents(synthetic_documents)
    chunk_to_doc = {c.chunk_id: c.doc_id for c in chunks}
    doc_source_type = {d.id: d.source_type for d in synthetic_documents}
    chunk_to_source_type = {c.chunk_id: doc_source_type[c.doc_id] for c in chunks}

    retriever = HybridRetriever(
        embedder=stub_embedder,
        vector_store=store,
        bm25_index=bm25,
        chunk_to_doc=chunk_to_doc,
        chunk_to_source_type=chunk_to_source_type,
        abstention_threshold=-1.0,
    )
    results = retriever.retrieve("PTO policy company holidays", top_k=5)

    doc_ids = [doc_id for doc_id, _ in results]
    assert results, "wired pipeline returned no results"
    assert len(doc_ids) == len(set(doc_ids)), "duplicate doc_ids in pipeline output"
    assert len(doc_ids) <= 5


def test_build_index_is_idempotent(temp_paths, synthetic_documents, stub_embedder):
    """AC-4 (first half): re-running `build_index` with LanceDB present is a no-op."""
    write_corpus(synthetic_documents, config.CORPUS_PATH)
    first = pipeline.build_index(force=False, embedder=stub_embedder)
    assert first > 0

    embeddings_mtime = config.EMBEDDINGS_PATH.stat().st_mtime_ns
    second = pipeline.build_index(force=False, embedder=stub_embedder)
    assert second == 0  # skipped
    assert config.EMBEDDINGS_PATH.stat().st_mtime_ns == embeddings_mtime, (
        "artifacts must not be touched"
    )


def test_rebuild_index_force_clears_and_regenerates(temp_paths, synthetic_documents, stub_embedder):
    """AC-4 (second half): force=True deletes and regenerates all three artifacts."""
    write_corpus(synthetic_documents, config.CORPUS_PATH)
    pipeline.build_index(force=False, embedder=stub_embedder)

    embeddings_mtime = config.EMBEDDINGS_PATH.stat().st_mtime_ns
    rebuilt = pipeline.build_index(force=True, embedder=stub_embedder)

    assert rebuilt > 0
    assert config.BM25_INDEX_DIR.exists()
    assert config.EMBEDDINGS_PATH.exists()
    assert config.LANCEDB_DIR.exists()
    assert config.EMBEDDINGS_PATH.stat().st_mtime_ns >= embeddings_mtime


def test_load_retriever_from_persisted_artifacts(temp_paths, synthetic_documents, stub_embedder):
    """`load_retriever` reopens BM25 + LanceDB and rebuilds chunk maps via the
    same chunker — exercised offline so the path isn't only covered by the
    local-only smoke gate (REVIEW.md NON-BLOCKING #2).
    """
    write_corpus(synthetic_documents, config.CORPUS_PATH)
    pipeline.build_index(force=False, embedder=stub_embedder)

    retriever = pipeline.load_retriever(embedder=stub_embedder)
    assert isinstance(retriever, HybridRetriever)

    # Stub vectors are quasi-orthogonal so the 0.45 cosine gate would always
    # fire — disable the gate to test the *wiring* (BM25 + LanceDB + maps), not
    # the gate itself (which `test_hybrid_retriever.py` already covers).
    retriever._abstention_threshold = -1.0
    results = retriever.retrieve("PTO policy company holidays", top_k=5)
    assert results, "load_retriever produced an empty result on an in-corpus query"
    doc_ids = [doc_id for doc_id, _ in results]
    assert len(doc_ids) == len(set(doc_ids))


def test_embeddings_and_chunk_order_are_aligned(temp_paths, synthetic_documents, stub_embedder):
    """The .npy matrix row order matches the chunk-order sidecar — the anchor
    that prevents RRF from fusing mismatched IDs (DESIGN risk)."""
    write_corpus(synthetic_documents, config.CORPUS_PATH)
    pipeline.build_index(force=False, embedder=stub_embedder)

    vectors = np.load(config.EMBEDDINGS_PATH)
    chunk_ids: list[str] = json.loads(Path(config.CHUNK_ORDER_PATH).read_text(encoding="utf-8"))
    chunks = chunk_documents(synthetic_documents)
    assert chunk_ids == [c.chunk_id for c in chunks]
    assert vectors.shape == (len(chunks), stub_embedder.dim)
