"""Tests for the adapter registry and the flat adapter."""

import pytest

from enterprise_rag_ops.ingest.adapters import REGISTRY, flat_adapter, get_adapter
from enterprise_rag_ops.ingest.config import SOURCE_TYPES
from enterprise_rag_ops.ingest.schema import Document, UnknownSourceTypeError

RAW = {
    "doc_id": "dsid_abc",
    "source_type": "confluence",
    "title": "Runbook",
    "content": "Deploy steps...",
}


def test_flat_adapter_maps_fields():
    doc = flat_adapter(RAW)
    assert isinstance(doc, Document)
    assert doc.id == "dsid_abc"
    assert doc.source_type == "confluence"
    assert doc.text == "Deploy steps..."
    assert doc.metadata == {"title": "Runbook"}


def test_registry_covers_every_known_source_type():
    assert set(REGISTRY) == set(SOURCE_TYPES)


@pytest.mark.parametrize("source_type", sorted(SOURCE_TYPES))
def test_get_adapter_returns_flat_adapter_for_known_sources(source_type):
    assert get_adapter(source_type) is flat_adapter


def test_get_adapter_raises_on_unknown_source_type():
    with pytest.raises(UnknownSourceTypeError):
        get_adapter("notion")
