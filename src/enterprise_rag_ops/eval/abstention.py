"""Abstention scoring for RAG evaluation (FR-7, FR-8, NFR-5, AC-9, AC-10).

Computes precision and recall for abstention.
An unanswerable question (where expected_doc_ids is empty) should result in abstention.
An answerable question (where expected_doc_ids is non-empty) should not result in abstention.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.generation.cli import ABSTAIN_ANSWER
from enterprise_rag_ops.generation.schema import AnswerWithSources


def compute_abstention_metrics(
    questions: Sequence[Question],
    did_abstain_map: Mapping[str, bool],
) -> dict[str, float | None]:
    """Compute precision and recall for abstention.

    should_abstain is True when expected_doc_ids is empty.
    """
    tp = 0
    fp = 0
    fn = 0
    tn = 0

    # Filter to questions that actually have did_abstain entries.
    for q in questions:
        if q.question_id not in did_abstain_map:
            continue
        should_abstain = len(q.expected_doc_ids) == 0
        did_abstain = did_abstain_map[q.question_id]

        if should_abstain and did_abstain:
            tp += 1
        elif not should_abstain and did_abstain:
            fp += 1
        elif should_abstain and not did_abstain:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None

    return {
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def evaluate_retrieval_abstention(
    questions: Sequence[Question],
    retrieved_results: Mapping[str, Sequence[str] | Sequence[tuple[str, float]]],
) -> dict[str, float | None]:
    """Compute retrieval-level abstention precision and recall.

    An abstention is defined as the retriever returning an empty list [].
    """
    did_abstain_map = {qid: len(hits) == 0 for qid, hits in retrieved_results.items()}
    return compute_abstention_metrics(questions, did_abstain_map)


def evaluate_e2e_abstention(
    questions: Sequence[Question],
    answers: Mapping[str, AnswerWithSources],
) -> dict[str, float | None]:
    """Compute end-to-end abstention precision and recall.

    An e2e abstention is defined as AnswerWithSources.answer == ABSTAIN_ANSWER
    and AnswerWithSources.sources == [].
    """
    did_abstain_map = {}
    for qid, ans in answers.items():
        did_abstain_map[qid] = ans.answer == ABSTAIN_ANSWER and len(ans.sources) == 0
    return compute_abstention_metrics(questions, did_abstain_map)
