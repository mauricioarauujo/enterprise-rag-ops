"""Tests for the verdict schemas (AC-1/2/3)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.eval.schema import (
    CitationVerdict,
    FactVerdict,
    JudgeVerdict,
    _LLMJudgeVerdict,
)


def test_fact_verdict_valid_construction():
    fv = FactVerdict(fact="Paris is the capital of France.", verdict="present")
    assert fv.verdict == "present"
    assert FactVerdict.model_validate_json(fv.model_dump_json()) == fv


def test_fact_verdict_rejects_out_of_vocab_verdict():
    with pytest.raises(ValidationError):
        FactVerdict.model_validate({"fact": "x", "verdict": "maybe"})


def test_fact_verdict_rejects_extra_field():
    with pytest.raises(ValidationError):
        FactVerdict.model_validate({"fact": "x", "verdict": "present", "doc_id": "d"})


def test_citation_verdict_valid_construction():
    cv = CitationVerdict(doc_id="doc_a", verdict="unsupported")
    assert cv.verdict == "unsupported"


def test_citation_verdict_rejects_out_of_vocab_verdict():
    with pytest.raises(ValidationError):
        CitationVerdict.model_validate({"doc_id": "d", "verdict": "partial"})


def test_citation_verdict_rejects_extra_field():
    with pytest.raises(ValidationError):
        CitationVerdict.model_validate({"doc_id": "d", "verdict": "supported", "x": 1})


def test_judge_verdict_floats_default_to_none():
    """The three aggregate floats are Python-derived and default to None (AC-3)."""
    jv = JudgeVerdict(per_fact=[], per_citation=[])
    assert jv.fact_recall is None
    assert jv.fact_precision is None
    assert jv.faithfulness_ratio is None


def test_llm_facing_schema_excludes_aggregate_floats():
    """The LLM-facing surface is the two lists only — no float properties (Risk #1)."""
    schema = _LLMJudgeVerdict.model_json_schema()
    assert set(schema["required"]) == {"per_fact", "per_citation"}
    assert "fact_recall" not in schema["properties"]
    assert "fact_precision" not in schema["properties"]
    assert "faithfulness_ratio" not in schema["properties"]


def test_llm_facing_schema_is_strict_compatible():
    """Closed top + closed nested objects → consumable as an OpenAI strict json_schema."""
    schema = _LLMJudgeVerdict.model_json_schema()
    assert schema["additionalProperties"] is False
    for defn in schema["$defs"].values():
        assert defn["additionalProperties"] is False
        # OpenAI `strict` requires every property to be required — no optionals.
        assert set(defn["required"]) == set(defn["properties"])
    # Sanity: serializable for OpenAI `response_format`.
    json.dumps(schema)
