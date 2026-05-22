"""Tests for `AnswerWithSources` (AC-1)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.generation.schema import AnswerWithSources


def test_round_trip_json():
    obj = AnswerWithSources(answer="The PTO policy allows 20 days.", sources=["doc_pto"])
    payload = obj.model_dump_json()
    assert AnswerWithSources.model_validate_json(payload) == obj


def test_missing_required_field_raises():
    with pytest.raises(ValidationError):
        AnswerWithSources.model_validate({"answer": "no sources field"})
    with pytest.raises(ValidationError):
        AnswerWithSources.model_validate({"sources": ["doc"]})


def test_extra_field_rejected():
    """Schema is closed — `additionalProperties: false` for OpenAI strict mode."""
    with pytest.raises(ValidationError):
        AnswerWithSources.model_validate({"answer": "a", "sources": ["doc"], "extra": "nope"})


def test_empty_sources_is_valid():
    """Abstention path (`sources=[]`) must validate (FR-8)."""
    obj = AnswerWithSources(answer="I don't have enough information.", sources=[])
    assert obj.sources == []


def test_json_schema_advertises_closed_object():
    schema = AnswerWithSources.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"answer", "sources"}
    # Sanity: schema is JSON-serializable for OpenAI `response_format`.
    json.dumps(schema)
