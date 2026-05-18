"""Streaming access to the EnterpriseRAG-Bench corpus.

The `documents` config is a 1.3 GB / ~512K-row Parquet file; streaming keeps peak
memory bounded (NFR-2) by never materializing the full corpus.
"""

from __future__ import annotations

from collections.abc import Iterator

from datasets import load_dataset

from enterprise_rag_ops.ingest import config


def stream_documents(revision: str = config.DATASET_REVISION) -> Iterator[dict]:
    """Yield raw corpus records from EnterpriseRAG-Bench at a pinned revision.

    Each record is a dict with keys ``doc_id``, ``source_type``, ``title``, and
    ``content``. Iteration streams from the remote Parquet file; the full corpus
    is never loaded into memory.
    """
    dataset = load_dataset(
        config.DATASET_ID,
        config.DOCUMENTS_CONFIG,
        split=config.DOCUMENTS_SPLIT,
        revision=revision,
        streaming=True,
    )
    yield from dataset
