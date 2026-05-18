"""The flat adapter — the one normalization all nine sources need.

At DATASET_REVISION every `documents` record shares an identical flat schema
(``doc_id``, ``source_type``, ``title``, ``content``), so a single adapter
handles all source types. Per-source adapters can be added later if a future
revision diverges; the registry keeps that a registration detail.
"""

from __future__ import annotations

from enterprise_rag_ops.ingest.schema import Document


def flat_adapter(raw: dict) -> Document:
    """Map a flat-schema EnterpriseRAG-Bench record to a `Document`.

    Field mapping: ``doc_id`` -> ``id``, ``source_type`` -> ``source_type``,
    ``content`` -> ``text``. ``title`` is preserved under ``metadata`` since
    retrieval (Phase 2) may use it for display or boosting.
    """
    return Document(
        id=raw["doc_id"],
        source_type=raw["source_type"],
        text=raw["content"],
        metadata={"title": raw["title"]},
    )
