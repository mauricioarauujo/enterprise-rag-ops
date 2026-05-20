"""Chunk model — the retrieval package's contract.

A `Chunk` is a sub-document window produced by the chunker. It mirrors
`ingest/schema.py::Document` as the unit the retrieval layer indexes and ranks.
The invariant `Chunk.doc_id == Document.id` (FR-1) is what lets the smoke gate
deduplicate retrieved chunks back to documents and score against
`expected_doc_ids`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Chunk:
    """A single chunk of a `Document`.

    Fields:
        chunk_id: Deterministic identifier, ``f"{doc_id}::{offset}"`` — the offset
            is the chunk's 0-based position within its source document.
        doc_id: The parent `Document.id`. The dedup key: retrieval ranks chunks
            but returns documents, so this is the foreign key back to the corpus.
        text: The chunk body — a fixed-size window of the document text.
    """

    chunk_id: str
    doc_id: str
    text: str
