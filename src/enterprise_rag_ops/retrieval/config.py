"""Retrieval configuration: paths, model coordinates, and tunable parameters.

All values are the Phase 2 defaults pinned in DEFINE / DESIGN. They live here so
the build pipeline, CLI, and tests share one source of truth — and so a future
sweep (Sprint 2 eval) edits one file, not five.
"""

from __future__ import annotations

from enterprise_rag_ops.ingest import config as ingest_config

# --- Paths -----------------------------------------------------------------

# Mirror ingest/config.py: derive PROCESSED_DIR from one place so the two
# packages can't drift on where corpus.jsonl lives.
PROCESSED_DIR = ingest_config.PROCESSED_DIR
CORPUS_PATH = ingest_config.CORPUS_PATH

BM25_INDEX_DIR = PROCESSED_DIR / "bm25_index"
EMBEDDINGS_PATH = PROCESSED_DIR / "embeddings.npy"
CHUNK_ORDER_PATH = PROCESSED_DIR / "embeddings.chunks.json"
LANCEDB_DIR = PROCESSED_DIR / "lancedb"
LANCEDB_TABLE = "chunks"

# --- Chunking --------------------------------------------------------------

# 256-token child window with 32-token overlap (FR-2). We approximate tokens as
# characters via RecursiveCharacterTextSplitter's default length function — the
# absolute units are irrelevant; what matters is uniformity across sources.
CHUNK_SIZE = 256
CHUNK_OVERLAP = 32

# --- BM25 ------------------------------------------------------------------

BM25_METHOD = "lucene"
BM25_K1 = 1.5
BM25_B = 0.75

# --- Embedding -------------------------------------------------------------

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# --- Hybrid retrieval ------------------------------------------------------

# Reciprocal Rank Fusion smoothing constant. 60 is the standard from the
# original Cormack et al. RRF paper; no calibration is done in Phase 2.
RRF_K = 60

# Each retriever fetches TOP_K * OVER_FETCH candidates before fusion so the
# fused set has enough overlap to dedup-to-doc cleanly.
OVER_FETCH = 3
TOP_K = 10

# Abstention gate: if the top-1 dense cosine similarity falls below this, the
# retriever returns [] rather than serving low-quality matches (FR-9).
ABSTENTION_THRESHOLD = 0.45
