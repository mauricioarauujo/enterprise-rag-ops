"""Aggregation of retrieval evaluation metrics grouped by question category (FR-6, AC-8).

Skips None values during aggregation (e.g. empty denominators or N/A).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.eval.retrieval_metrics import (
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def aggregate_retrieval_metrics(
    questions: Sequence[Question],
    ranked_results: Mapping[str, list[str]],
    k: int = 10,
) -> dict[str, dict[str, float | None]]:
    """Compute and aggregate retrieval metrics grouped by question category.

    Skips None values during aggregation. If a category has no valid metric
    values (e.g. info_not_found has empty gold sets), its aggregate is None.
    """
    category_metrics = defaultdict(lambda: defaultdict(list))

    for q in questions:
        ranked_ids = ranked_results.get(q.question_id, [])
        r = recall_at_k(ranked_ids, q.expected_doc_ids, k=k)
        p = precision_at_k(ranked_ids, q.expected_doc_ids, k=k)
        m = mrr(ranked_ids, q.expected_doc_ids, k=k)
        n = ndcg_at_k(ranked_ids, q.expected_doc_ids, k=k)

        if r is not None:
            category_metrics[q.category]["recall"].append(r)
        if p is not None:
            category_metrics[q.category]["precision"].append(p)
        if m is not None:
            category_metrics[q.category]["mrr"].append(m)
        if n is not None:
            category_metrics[q.category]["ndcg"].append(n)

    aggregated: dict[str, dict[str, float | None]] = {}
    all_categories = sorted({q.category for q in questions})

    for cat in all_categories:
        metrics = category_metrics[cat]
        recalls = metrics["recall"]
        precisions = metrics["precision"]
        mrrs = metrics["mrr"]
        ndcgs = metrics["ndcg"]

        aggregated[cat] = {
            f"recall_at_{k}": sum(recalls) / len(recalls) if recalls else None,
            f"precision_at_{k}": sum(precisions) / len(precisions) if precisions else None,
            "mrr": sum(mrrs) / len(mrrs) if mrrs else None,
            f"ndcg_at_{k}": sum(ndcgs) / len(ndcgs) if ndcgs else None,
        }

    return aggregated
