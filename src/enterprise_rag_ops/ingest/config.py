"""Ingest configuration: dataset coordinates, the pinned revision, and paths.

The revision SHA is pinned for reproducibility (NFR-1): re-running ingest at the
same SHA and `DOCS_PER_SOURCE` must yield a byte-identical corpus.
"""

from __future__ import annotations

from pathlib import Path

# --- Dataset coordinates ---------------------------------------------------

DATASET_ID = "onyx-dot-app/EnterpriseRAG-Bench"

# Pinned commit SHA of the `main` branch, captured 2026-05-17 (dataset last
# modified 2026-05-08). Reproducibility depends on this never drifting silently.
DATASET_REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"

# The dataset exposes two configs: `documents` (the corpus, ~512K rows) and
# `questions` (the 500-question eval set, used from Sprint 2 on). Phase 1 ingests
# the corpus only.
DOCUMENTS_CONFIG = "documents"
DOCUMENTS_SPLIT = "test"

# The nine enterprise source types present at DATASET_REVISION. Enumerated from
# the corpus, not guessed — a source type outside this set raises
# UnknownSourceTypeError rather than being dropped (FR-3).
SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "confluence",
        "fireflies",
        "github",
        "gmail",
        "google_drive",
        "hubspot",
        "jira",
        "linear",
        "slack",
    }
)

# --- Sampling --------------------------------------------------------------

# Documents kept per source type in the default stratified subset. Override via
# `make download-data DOCS_PER_SOURCE=<n>`.
DEFAULT_DOCS_PER_SOURCE = 100

# --- Paths -----------------------------------------------------------------

# Repo root: config.py lives at src/enterprise_rag_ops/ingest/config.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
CORPUS_PATH = PROCESSED_DIR / "corpus.jsonl"
