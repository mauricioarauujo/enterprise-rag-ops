"""Rule-based failure-mode classifier for evaluation records (FR-1, FR-2, FR-3, FR-4, FR-5).

Uses aggregate metrics and gold dataset questions to classify evaluation records
into one of five categories:
- abstention_error: Disagreement on whether the model should have abstained.
- retrieval_miss: No gold documents returned in the retriever's top-k slice.
- hallucination: Answer was generated but faithfulness falls below threshold.
- incomplete: Answer was faithful but missed required facts (low recall).
- correct: Model answered correctly and meets all quality thresholds.
"""

from __future__ import annotations

from enum import StrEnum

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.root_cause import RootCauseRollup, rollup


class FailureMode(StrEnum):
    """Supported failure modes for the RAG evaluation records."""

    ABSTENTION_ERROR = "abstention_error"
    RETRIEVAL_MISS = "retrieval_miss"
    HALLUCINATION = "hallucination"
    INCOMPLETE = "incomplete"
    CORRECT = "correct"


HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5
INCOMPLETE_RECALL_THRESHOLD = 0.5


def _should_abstain(question: Question) -> bool:
    """Check if the question is unanswerable (i.e. has no expected doc IDs)."""
    return len(question.expected_doc_ids) == 0


def _retrieval_hit(record: EvalRecord, question: Question) -> bool:
    """Check if retrieval succeeded (at least one gold doc in the top-k)."""
    return len(question.expected_doc_ids) > 0 and bool(
        set(question.expected_doc_ids) & set(record.retrieval_ranked_ids[: record.k])
    )


def is_abstention_error(record: EvalRecord, question: Question) -> bool:
    """Check if there is an abstention error (Checked FIRST).

    Covers both:
    1. False abstention: Answerable question, but the model abstained.
    2. Failure to abstain: Unanswerable question, but the model did not abstain.
    """
    return _should_abstain(question) != record.did_abstain_e2e


def is_retrieval_miss(record: EvalRecord, question: Question) -> bool:
    """Check if the retriever failed to retrieve any gold documents in top-k."""
    return len(question.expected_doc_ids) > 0 and not (
        set(question.expected_doc_ids) & set(record.retrieval_ranked_ids[: record.k])
    )


def is_hallucination(record: EvalRecord, question: Question) -> bool:
    """Check if the response is unfaithful to the retrieved documents.

    A None faithfulness_ratio (meaning no sources cited) must never classify
    as a hallucination.
    """
    return (
        _retrieval_hit(record, question)
        and record.faithfulness_ratio is not None
        and record.faithfulness_ratio < HALLUCINATION_FAITHFULNESS_THRESHOLD
    )


def is_incomplete(record: EvalRecord, question: Question) -> bool:
    """Check if the answer is incomplete (low fact recall).

    Applies to records that had a retrieval hit, did not hallucinate,
    did not abstain e2e, have a non-None fact_recall, and the fact_recall
    falls below the incomplete recall threshold.
    """
    return (
        _retrieval_hit(record, question)
        and not is_hallucination(record, question)
        and not record.did_abstain_e2e
        and record.fact_recall is not None
        and record.fact_recall < INCOMPLETE_RECALL_THRESHOLD
    )


def classify(record: EvalRecord, question: Question) -> FailureMode:
    """Classify an evaluation record into a failure mode or correct classification.

    Follows a strict first-match priority cascade:
    abstention_error -> retrieval_miss -> hallucination -> incomplete -> correct
    """
    if is_abstention_error(record, question):
        return FailureMode.ABSTENTION_ERROR
    if is_retrieval_miss(record, question):
        return FailureMode.RETRIEVAL_MISS
    if is_hallucination(record, question):
        return FailureMode.HALLUCINATION
    if is_incomplete(record, question):
        return FailureMode.INCOMPLETE
    return FailureMode.CORRECT


def attribute_root_cause(record: EvalRecord) -> RootCauseRollup:
    """Per-fact root-cause attribution at the taxonomy surface (FR-5 / SC-3).

    Delegates to `root_cause.rollup` so the taxonomy can attribute a retrieval-miss
    vs generation-gap root cause from the per-fact `supporting_doc_id` signal — not
    just answer-level aggregates (SC-3's literal requirement). Additive and orthogonal:
    it does NOT touch `classify()`, the cascade order, the `FailureMode` members, or
    the `is_*` helpers — no record is reclassified (Decision C / AC-12).
    """
    return rollup(record)
