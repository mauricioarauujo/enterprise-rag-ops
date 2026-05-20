"""Index-build pipeline: corpus.jsonl → BM25 + embeddings + LanceDB.

Idempotency (FR-10) lives here: `build_index()` skips if the LanceDB directory
already exists; `force=True` (the `make rebuild-index` path) wipes all three
artifacts first. Per-source chunk-count logging at INFO mirrors
`ingest/cli.py` (NFR-6).
"""

from __future__ import annotations

import json
import logging
import shutil
from collections import Counter
from collections.abc import Iterable

import numpy as np

from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.ingest.writer import read_corpus
from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.bm25_index import BM25Index
from enterprise_rag_ops.retrieval.chunker import chunk_document, chunk_documents
from enterprise_rag_ops.retrieval.embedder import BGEEmbedder
from enterprise_rag_ops.retrieval.hybrid_retriever import HybridRetriever
from enterprise_rag_ops.retrieval.interfaces import Embedder
from enterprise_rag_ops.retrieval.schema import Chunk
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore

logger = logging.getLogger("enterprise_rag_ops.retrieval")


def _log_per_source_counts(chunks: Iterable[Chunk], doc_source_type: dict[str, str]) -> None:
    """Mirror ingest's per-source documents log, but for chunks (NFR-6)."""
    counts: Counter[str] = Counter(doc_source_type[c.doc_id] for c in chunks)
    for source_type in sorted(counts):
        logger.info("  %-14s %d chunks", source_type, counts[source_type])


def _clear_artifacts() -> None:
    """Remove the three persisted index artifacts (the `force=True` path)."""
    for path in (config.BM25_INDEX_DIR, config.LANCEDB_DIR):
        if path.exists():
            shutil.rmtree(path)
    for path in (config.EMBEDDINGS_PATH, config.CHUNK_ORDER_PATH):
        if path.exists():
            path.unlink()


def build_index(
    force: bool = False,
    embedder: Embedder | None = None,
) -> int:
    """Build the three retrieval artifacts from `corpus.jsonl`.

    Returns the number of chunks indexed. Idempotent: returns early (with 0)
    when the LanceDB directory already exists, unless `force=True`.

    `embedder` is injectable so tests can drive the pipeline with `StubEmbedder`
    without instantiating BGE-M3 — production `make build-index` leaves it
    `None` to get the default BGE-M3.
    """
    if config.LANCEDB_DIR.exists() and not force:
        logger.info(
            "LanceDB dir %s exists; skipping rebuild (use force=True to override)",
            config.LANCEDB_DIR,
        )
        return 0
    if force:
        _clear_artifacts()

    documents: list[Document] = list(read_corpus(config.CORPUS_PATH))
    doc_source_type = {doc.id: doc.source_type for doc in documents}
    logger.info("Loaded %d documents from %s", len(documents), config.CORPUS_PATH)

    chunks = chunk_documents(documents)
    logger.info(
        "Chunked into %d chunks (size=%d overlap=%d)",
        len(chunks),
        config.CHUNK_SIZE,
        config.CHUNK_OVERLAP,
    )
    _log_per_source_counts(chunks, doc_source_type)

    # BM25 — same ordered chunk list anchors every artifact below.
    bm25 = BM25Index.build(chunks)
    bm25.save(config.BM25_INDEX_DIR)
    logger.info("Saved BM25 index → %s", config.BM25_INDEX_DIR)

    # Dense embeddings — encode once at build time (NFR-1).
    embedder = embedder or BGEEmbedder()
    vectors = embedder.encode([c.text for c in chunks])
    config.EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(config.EMBEDDINGS_PATH, vectors)
    config.CHUNK_ORDER_PATH.write_text(
        json.dumps([c.chunk_id for c in chunks]),
        encoding="utf-8",
    )
    logger.info(
        "Saved embeddings (%dx%d) → %s", vectors.shape[0], vectors.shape[1], config.EMBEDDINGS_PATH
    )

    # LanceDB — the same chunk ordering, with source_type as a pre-filterable column.
    store = LanceDBStore(config.LANCEDB_DIR)
    store.add(
        chunks=chunks,
        vectors=vectors,
        source_types=[doc_source_type[c.doc_id] for c in chunks],
    )
    logger.info("Saved LanceDB table → %s", config.LANCEDB_DIR)
    return len(chunks)


def load_retriever(embedder: Embedder | None = None) -> HybridRetriever:
    """Construct a `HybridRetriever` from the persisted artifacts (NFR-1).

    No re-indexing or re-encoding — a fresh process opens BM25, LanceDB, and the
    chunk-order sidecar, then serves queries. The corpus is read once to build
    the chunk_id↔(doc_id, source_type) maps the retriever needs at query time.
    """
    bm25 = BM25Index.load(config.BM25_INDEX_DIR)
    store = LanceDBStore.open(config.LANCEDB_DIR)
    embedder = embedder or BGEEmbedder()

    # Rebuild the chunk_id → (doc_id, source_type) maps from corpus.jsonl. This
    # is O(corpus size) at startup — fine for ~3-5k chunks; can be persisted as
    # a sidecar if it ever becomes a hotspot.
    chunk_to_doc: dict[str, str] = {}
    chunk_to_source_type: dict[str, str] = {}
    for doc in read_corpus(config.CORPUS_PATH):
        for chunk in chunk_document(doc):
            chunk_to_doc[chunk.chunk_id] = doc.id
            chunk_to_source_type[chunk.chunk_id] = doc.source_type

    return HybridRetriever(
        embedder=embedder,
        vector_store=store,
        bm25_index=bm25,
        chunk_to_doc=chunk_to_doc,
        chunk_to_source_type=chunk_to_source_type,
    )
