"""Unit and e2e tests for abstention scoring (FR-7, FR-8, FR-11d, AC-9, AC-10)."""

from __future__ import annotations

import os

import pytest

from enterprise_rag_ops.eval.abstention import (
    evaluate_e2e_abstention,
    evaluate_retrieval_abstention,
)
from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.generation.cli import ABSTAIN_ANSWER
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


def test_evaluate_retrieval_abstention_synthetic():
    """AC-9: retrieval-level scorer precision/recall on synthetic inputs."""
    questions = [
        Question(
            question_id="q1",
            question="Q1",
            answer_facts=[],
            expected_doc_ids=[],
            category="info_not_found",
        ),  # should abstain
        Question(
            question_id="q2",
            question="Q2",
            answer_facts=[],
            expected_doc_ids=["docA"],
            category="basic",
        ),  # should answer
        Question(
            question_id="q3",
            question="Q3",
            answer_facts=[],
            expected_doc_ids=[],
            category="info_not_found",
        ),  # should abstain
        Question(
            question_id="q4",
            question="Q4",
            answer_facts=[],
            expected_doc_ids=["docB"],
            category="basic",
        ),  # should answer
    ]

    retrieved_results = {
        "q1": [],  # TP: should abstain, did abstain
        "q2": [],  # FP: should answer, did abstain
        "q3": ["docC"],  # FN: should abstain, did not abstain
        "q4": ["docD"],  # TN: should answer, did not abstain
    }

    metrics = evaluate_retrieval_abstention(questions, retrieved_results)
    # TP=1 (q1), FP=1 (q2), FN=1 (q3)
    # Precision = TP / (TP + FP) = 1 / 2 = 0.5
    # Recall = TP / (TP + FN) = 1 / 2 = 0.5
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5


def test_evaluate_e2e_abstention_synthetic():
    """AC-10: end-to-end scorer precision/recall on synthetic inputs."""
    questions = [
        Question(
            question_id="q1",
            question="Q1",
            answer_facts=[],
            expected_doc_ids=[],
            category="info_not_found",
        ),  # should abstain
        Question(
            question_id="q2",
            question="Q2",
            answer_facts=[],
            expected_doc_ids=["docA"],
            category="basic",
        ),  # should answer
        Question(
            question_id="q3",
            question="Q3",
            answer_facts=[],
            expected_doc_ids=[],
            category="info_not_found",
        ),  # should abstain
        Question(
            question_id="q4",
            question="Q4",
            answer_facts=[],
            expected_doc_ids=["docB"],
            category="basic",
        ),  # should answer
    ]

    answers = {
        "q1": AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[]),  # TP
        "q2": AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[]),  # FP
        "q3": AnswerWithSources(answer="Here is the info.", sources=["docC"]),  # FN
        "q4": AnswerWithSources(answer="Here is the info.", sources=["docB"]),  # TN
    }

    metrics = evaluate_e2e_abstention(questions, answers)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5


# `vcr` is a selection label only (`-m vcr`); vcrpy 6 ships no pytest plugin, so
# the cassette is applied by the explicit `vcr_record.use_cassette(...)` below.
@pytest.mark.vcr
def test_e2e_abstention_paris_anchor(vcr_record, monkeypatch):
    """AC-10, AC-16, NFR-8: Paris anchor case replayed offline via VCR."""
    # Ensure OPENAI_API_KEY is set to a dummy value so OpenAIGenerator initializes
    # without network errors when replaying offline.
    if not os.environ.get("OPENAI_API_KEY"):
        monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-for-replay")

    from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator

    # Redwood-shield is unrelated to Paris, so generator must abstain.
    dummy_chunks = [
        Chunk(
            chunk_id="dummy::0",
            doc_id="dummy",
            text="The redwood-shield policy MED value is set to 100 for failovers.",
        )
    ]
    question = "What is the capital of France?"

    generator = OpenAIGenerator()

    with vcr_record.use_cassette("abstention_info_not_found.yaml"):
        result = generator.generate(context_chunks=dummy_chunks, question=question)

    assert result.answer == ABSTAIN_ANSWER
    assert len(result.sources) == 0
