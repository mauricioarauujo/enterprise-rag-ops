"""Unit tests for category-based retrieval metrics aggregation (FR-6, AC-8)."""

from __future__ import annotations

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.eval.retrieval_eval import aggregate_retrieval_metrics


def test_aggregate_retrieval_metrics_groups_by_category():
    # Setup some questions in different categories
    questions = [
        Question(
            question_id="q1",
            question="Q1",
            answer_facts=[],
            expected_doc_ids=["docA"],
            category="basic",
        ),
        Question(
            question_id="q2",
            question="Q2",
            answer_facts=[],
            expected_doc_ids=["docB"],
            category="basic",
        ),
        Question(
            question_id="q3",
            question="Q3",
            answer_facts=[],
            expected_doc_ids=["docC"],
            category="semantic",
        ),
        # Empty gold question (should yield None for all metrics, representing N/A)
        Question(
            question_id="q4",
            question="Q4",
            answer_facts=[],
            expected_doc_ids=[],
            category="info_not_found",
        ),
    ]

    ranked_results = {
        "q1": ["docA"],  # Perfect: recall=1, precision=1, mrr=1
        "q2": ["docX"],  # Zero hits: recall=0, precision=0, mrr=None
        "q3": ["docC"],  # Perfect: recall=1, precision=1, mrr=1
        "q4": ["docA"],  # Empty expected doc ids, all None
    }

    # Run aggregation
    results = aggregate_retrieval_metrics(questions, ranked_results, k=1)

    # Basic Category:
    # q1 recall=1.0, q2 recall=0.0 -> average = 0.5
    # q1 precision=1.0, q2 precision=0.0 -> average = 0.5
    # q1 mrr=1.0, q2 mrr=None (skipped) -> average = 1.0
    assert results["basic"]["recall_at_1"] == 0.5
    assert results["basic"]["precision_at_1"] == 0.5
    assert results["basic"]["mrr"] == 1.0

    # Semantic Category:
    # q3 recall=1.0, precision=1.0, mrr=1.0 -> average = 1.0
    assert results["semantic"]["recall_at_1"] == 1.0
    assert results["semantic"]["precision_at_1"] == 1.0
    assert results["semantic"]["mrr"] == 1.0

    # info_not_found Category:
    # expected_doc_ids empty -> all metrics None
    assert results["info_not_found"]["recall_at_1"] is None
    assert results["info_not_found"]["precision_at_1"] is None
    assert results["info_not_found"]["mrr"] is None
