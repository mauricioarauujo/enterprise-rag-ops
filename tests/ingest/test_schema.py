"""Tests for the Document model and ingest errors."""

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.ingest.schema import Document, UnknownSourceTypeError


def test_document_valid_construction():
    doc = Document(id="d1", source_type="slack", text="hello", metadata={"title": "T"})
    assert doc.id == "d1"
    assert doc.source_type == "slack"
    assert doc.text == "hello"
    assert doc.metadata == {"title": "T"}


def test_document_metadata_defaults_to_empty_dict():
    doc = Document(id="d1", source_type="slack", text="hello")
    assert doc.metadata == {}


@pytest.mark.parametrize("field", ["id", "source_type", "text"])
def test_empty_string_field_rejected(field):
    kwargs = {"id": "d1", "source_type": "slack", "text": "hello"}
    kwargs[field] = ""
    with pytest.raises(ValidationError):
        Document(**kwargs)


@pytest.mark.parametrize("field", ["id", "source_type", "text"])
def test_whitespace_only_field_rejected(field):
    kwargs = {"id": "d1", "source_type": "slack", "text": "hello"}
    kwargs[field] = "   "
    with pytest.raises(ValidationError):
        Document(**kwargs)


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Document(id="d1", source_type="slack", text="hi", unexpected="x")


def test_unknown_source_type_error_carries_source_type():
    err = UnknownSourceTypeError("notion")
    assert err.source_type == "notion"
    assert "notion" in str(err)
    assert isinstance(err, ValueError)
