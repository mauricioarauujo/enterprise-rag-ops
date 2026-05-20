"""Tests for the `Chunk` dataclass and the `Chunk.doc_id == Document.id` invariant (AC-1)."""

from __future__ import annotations

import pytest

from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.retrieval.schema import Chunk


def test_chunk_constructs_with_required_fields():
    chunk = Chunk(chunk_id="doc1::0", doc_id="doc1", text="hello")
    assert chunk.chunk_id == "doc1::0"
    assert chunk.doc_id == "doc1"
    assert chunk.text == "hello"


def test_chunk_is_frozen():
    chunk = Chunk(chunk_id="doc1::0", doc_id="doc1", text="hello")
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass raises FrozenInstanceError
        chunk.text = "modified"  # type: ignore[misc]


def test_chunk_doc_id_matches_document_id():
    """AC-1: constructing a Chunk from a Document yields chunk.doc_id == document.id."""
    doc = Document(id="doc_xyz", source_type="slack", text="body")
    chunk = Chunk(chunk_id=f"{doc.id}::0", doc_id=doc.id, text=doc.text)
    assert chunk.doc_id == doc.id
