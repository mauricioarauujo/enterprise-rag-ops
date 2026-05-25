"""`OpenAIJudge` call-shape + prompt tests (AC-6, AC-7).

All offline via `FakeOpenAIClient` — no live call under `make test`. Injecting the
client bypasses the `OPENAI_API_KEY` construction guard, so these run with no key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.eval.openai_judge import DEFAULT_MODEL, OpenAIJudge
from enterprise_rag_ops.eval.schema import JudgeVerdict, _LLMJudgeVerdict
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk
from tests.eval.conftest import FakeOpenAIClient


def _judge(client, sample_answer, sample_facts, sample_chunks) -> JudgeVerdict:
    return OpenAIJudge(client=client).judge(
        question="What is the capital of France?",
        answer_with_sources=sample_answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )


def test_issues_exactly_one_create_call(
    canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    client = FakeOpenAIClient(canned_verdict_payload)
    _judge(client, sample_answer, sample_facts, sample_chunks)
    assert len(client.calls) == 1


def test_sends_strict_json_schema_without_float_properties(
    canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    """The sent schema is the LLM-facing surface — strict, two lists, no floats (AC-6)."""
    client = FakeOpenAIClient(canned_verdict_payload)
    _judge(client, sample_answer, sample_facts, sample_chunks)
    rf = client.calls[0]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    props = rf["json_schema"]["schema"]["properties"]
    assert set(props) == {"per_fact", "per_citation"}
    assert "fact_recall" not in props
    assert "faithfulness_ratio" not in props


def test_honors_rag_judge_model_env(
    monkeypatch, canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    monkeypatch.setenv("RAG_JUDGE_MODEL", "gpt-judge-test")
    client = FakeOpenAIClient(canned_verdict_payload)
    _judge(client, sample_answer, sample_facts, sample_chunks)
    assert client.calls[0]["model"] == "gpt-judge-test"


def test_defaults_to_default_model(
    monkeypatch, canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    monkeypatch.delenv("RAG_JUDGE_MODEL", raising=False)
    client = FakeOpenAIClient(canned_verdict_payload)
    _judge(client, sample_answer, sample_facts, sample_chunks)
    assert client.calls[0]["model"] == DEFAULT_MODEL


def test_prompt_contains_facts_checklist_and_per_doc_blocks(
    canned_verdict_payload, sample_answer, sample_facts, sample_chunks
):
    """AC-7: facts as a numbered checklist + each cited doc in its own named block."""
    client = FakeOpenAIClient(canned_verdict_payload)
    _judge(client, sample_answer, sample_facts, sample_chunks)
    user_msg = client.calls[0]["messages"][1]["content"]
    # Numbered fact checklist.
    assert "1. Paris is the capital of France." in user_msg
    assert "2. France is in Europe." in user_msg
    # One separately named block per cited doc_id (the per-doc isolation, not a blob).
    assert "=== doc doc_real ===" in user_msg
    assert "=== doc gd_unrelated ===" in user_msg
    assert "Paris is the capital and most populous city of France." in user_msg


def test_cited_doc_not_in_retrieved_set_renders_unavailable(
    canned_verdict_payload, sample_facts, sample_chunks
):
    """A cited doc_id absent from retrieved_docs gets an explicit unavailable block."""
    answer = AnswerWithSources(answer="...", sources=["doc_real", "doc_missing"])
    client = FakeOpenAIClient(canned_verdict_payload)
    OpenAIJudge(client=client).judge(
        question="q",
        answer_with_sources=answer,
        answer_facts=sample_facts,
        retrieved_docs=sample_chunks,
    )
    user_msg = client.calls[0]["messages"][1]["content"]
    assert "=== doc doc_missing (text unavailable) ===" in user_msg


def test_malformed_payload_raises_validation_error(sample_answer, sample_facts, sample_chunks):
    """Drift surfaces as a typed ValidationError, not an opaque SDK error (AC-6)."""
    bad = '{"per_fact": [{"fact": "x", "verdict": "definitely"}], "per_citation": []}'
    client = FakeOpenAIClient(bad)
    with pytest.raises(ValidationError):
        _judge(client, sample_answer, sample_facts, sample_chunks)


def test_aggregates_floats_in_python_from_returned_lists(
    sample_answer, sample_facts, sample_chunks
):
    """All three floats are derived in Python from the returned lists.

    Uses a present/present/contradicted + supported/unsupported payload so every
    float — including `fact_precision`'s contradicted branch — is non-trivially < 1.0.
    """
    payload = _LLMJudgeVerdict.model_validate(
        {
            "per_fact": [
                {"fact": "a", "verdict": "present"},
                {"fact": "b", "verdict": "present"},
                {"fact": "c", "verdict": "contradicted"},
            ],
            "per_citation": [
                {"doc_id": "d1", "verdict": "supported"},
                {"doc_id": "d2", "verdict": "unsupported"},
            ],
        }
    ).model_dump_json()
    verdict = _judge(FakeOpenAIClient(payload), sample_answer, sample_facts, sample_chunks)
    assert verdict.fact_recall == 2 / 3  # |present| / |facts|
    assert verdict.fact_precision == 2 / 3  # |present| / (|present| + |contradicted|)
    assert verdict.faithfulness_ratio == 0.5  # |supported| / |citations|


def test_multiple_chunks_same_doc_are_joined_in_prompt(canned_verdict_payload, sample_facts):
    """A doc split across chunks renders one block with all chunk texts, not just the last."""
    answer = AnswerWithSources(answer="...", sources=["doc_multi"])
    chunks = [
        Chunk(chunk_id="doc_multi::0", doc_id="doc_multi", text="First chunk body."),
        Chunk(chunk_id="doc_multi::1", doc_id="doc_multi", text="Second chunk body."),
    ]
    client = FakeOpenAIClient(canned_verdict_payload)
    OpenAIJudge(client=client).judge(
        question="q",
        answer_with_sources=answer,
        answer_facts=sample_facts,
        retrieved_docs=chunks,
    )
    user_msg = client.calls[0]["messages"][1]["content"]
    assert "=== doc doc_multi ===" in user_msg
    assert "First chunk body." in user_msg
    assert "Second chunk body." in user_msg  # not collapsed to the last-seen chunk


def test_missing_api_key_raises_runtime_error(monkeypatch):
    """No client + no key → a clean RuntimeError, not an SDK stack trace (NFR-7)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAIJudge()
