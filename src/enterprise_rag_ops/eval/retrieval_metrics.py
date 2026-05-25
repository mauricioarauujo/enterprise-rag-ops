"""Pure evaluation metrics for RAG retrieval (FR-4, FR-5, AC-5, AC-6, AC-7, AC-14).

All metrics run on a doc-level deduplicated ranked list where chunk IDs
(e.g., "doc::0") are mapped to doc IDs ("doc") and only the first occurrence is kept.
Empty expected_doc_ids (empty denominator) returns None.
"""

from __future__ import annotations

import math


def deduplicate_ranked_ids(ranked_ids: list[str]) -> list[str]:
    """Map chunk IDs to doc IDs (via chunk_id.split("::", 1)[0]) and keep first wins."""
    seen = set()
    deduped = []
    for rid in ranked_ids:
        doc_id = rid.split("::", 1)[0]
        if doc_id not in seen:
            seen.add(doc_id)
            deduped.append(doc_id)
    return deduped


def recall_at_k(ranked_ids: list[str], expected_doc_ids: list[str], k: int = 10) -> float | None:
    """Recall@k: |R ∩ D_k| / |R|.

    R = expected_doc_ids, D_k = first k deduplicated doc IDs.
    Returns None if expected_doc_ids is empty.
    """
    if not expected_doc_ids:
        return None

    deduped = deduplicate_ranked_ids(ranked_ids)
    cutoff = deduped[:k]

    gold_set = set(expected_doc_ids)
    hits = sum(1 for doc_id in cutoff if doc_id in gold_set)
    return hits / len(gold_set)


def precision_at_k(ranked_ids: list[str], expected_doc_ids: list[str], k: int = 10) -> float | None:
    """Precision@k: |R ∩ D_k| / k.

    R = expected_doc_ids, D_k = first k deduplicated doc IDs.
    Returns None if expected_doc_ids is empty.
    """
    if not expected_doc_ids:
        return None

    deduped = deduplicate_ranked_ids(ranked_ids)
    cutoff = deduped[:k]

    gold_set = set(expected_doc_ids)
    hits = sum(1 for doc_id in cutoff if doc_id in gold_set)
    return hits / k


def mrr(ranked_ids: list[str], expected_doc_ids: list[str], k: int = 10) -> float | None:
    """Mean Reciprocal Rank (MRR) within top-k: 1 / rank_of_first_hit.

    Returns None if expected_doc_ids is empty or if there is no hit in top-k.
    """
    if not expected_doc_ids:
        return None

    deduped = deduplicate_ranked_ids(ranked_ids)
    cutoff = deduped[:k]

    gold_set = set(expected_doc_ids)
    for index, doc_id in enumerate(cutoff):
        if doc_id in gold_set:
            return 1.0 / (index + 1)
    return None


def ndcg_at_k(ranked_ids: list[str], expected_doc_ids: list[str], k: int = 10) -> float | None:
    """Normalized Discounted Cumulative Gain (nDCG@k) with binary relevance.

    nDCG@k = DCG@k / IDCG@k.
    Returns None if expected_doc_ids is empty.
    Returns 0.0 if expected_doc_ids is not empty but no hits in top-k.
    """
    if not expected_doc_ids:
        return None

    deduped = deduplicate_ranked_ids(ranked_ids)
    cutoff = deduped[:k]

    gold_set = set(expected_doc_ids)

    # Calculate DCG@k
    dcg = 0.0
    for index, doc_id in enumerate(cutoff):
        if doc_id in gold_set:
            dcg += 1.0 / math.log2(index + 2)

    # Calculate IDCG@k: ideal DCG has min(len(gold_set), k) hits at the top
    n_gold = len(gold_set)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(n_gold, k)))

    if idcg == 0.0:
        return None

    return dcg / idcg
