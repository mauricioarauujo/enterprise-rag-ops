"""Unit tests for retrieval metrics (FR-11a, AC-5, AC-6, AC-7, AC-14)."""

from __future__ import annotations

from enterprise_rag_ops.eval.retrieval_metrics import (
    deduplicate_ranked_ids,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_deduplicate_ranked_ids_handles_chunk_ids():
    """AC-6: multiple chunks from the same doc collapse to first wins."""
    ranked = ["docA::0", "docB::0", "docA::1", "docC::0", "docB::1"]
    assert deduplicate_ranked_ids(ranked) == ["docA", "docB", "docC"]


def test_deduplicate_ranked_ids_handles_plain_doc_ids():
    ranked = ["docA", "docB", "docA", "docC"]
    assert deduplicate_ranked_ids(ranked) == ["docA", "docB", "docC"]


def test_metrics_with_empty_expected_returns_none():
    """NFR-2, AC-5: empty expected_doc_ids (empty denominator) returns None."""
    ranked = ["docA", "docB"]
    expected = []
    assert recall_at_k(ranked, expected, k=5) is None
    assert precision_at_k(ranked, expected, k=5) is None
    assert mrr(ranked, expected, k=5) is None
    assert ndcg_at_k(ranked, expected, k=5) is None


def test_metrics_no_hits():
    """AC-7: no hits cases."""
    ranked = ["docA", "docB"]
    expected = ["docC"]
    assert recall_at_k(ranked, expected, k=5) == 0.0
    assert precision_at_k(ranked, expected, k=5) == 0.0
    assert mrr(ranked, expected, k=5) is None
    assert ndcg_at_k(ranked, expected, k=5) == 0.0


def test_metrics_all_hits_perfect():
    """AC-14 perfect ranking validation."""
    ranked = ["docA", "docB"]
    expected = ["docA", "docB"]
    assert recall_at_k(ranked, expected, k=5) == 1.0
    assert precision_at_k(ranked, expected, k=2) == 1.0
    assert mrr(ranked, expected, k=5) == 1.0
    assert ndcg_at_k(ranked, expected, k=5) == 1.0


def test_metrics_partial_hits_various_ranks():
    # ranked has chunks docA::0, docC::0, docB::0, docA::1
    # deduped = [docA, docC, docB]
    # expected = [docB, docA]
    # hits: docA (rank 1), docB (rank 3)
    ranked = ["docA::0", "docC::0", "docB::0", "docA::1"]
    expected = ["docB", "docA"]

    # At k=1, cutoff is [docA]. Hits = {docA} (1 hit)
    assert recall_at_k(ranked, expected, k=1) == 0.5
    assert precision_at_k(ranked, expected, k=1) == 1.0
    assert mrr(ranked, expected, k=1) == 1.0

    # At k=2, cutoff is [docA, docC]. Hits = {docA} (1 hit)
    assert recall_at_k(ranked, expected, k=2) == 0.5
    assert precision_at_k(ranked, expected, k=2) == 0.5
    assert mrr(ranked, expected, k=2) == 1.0

    # At k=3, cutoff is [docA, docC, docB]. Hits = {docA, docB} (2 hits)
    assert recall_at_k(ranked, expected, k=3) == 1.0
    assert precision_at_k(ranked, expected, k=3) == 2.0 / 3.0
    assert mrr(ranked, expected, k=3) == 1.0

    # Check MRR when first hit is at rank 2
    assert mrr(["docC", "docA"], expected, k=5) == 0.5


def test_ndcg_partial_ranking():
    # expected = [docA, docB] (n_gold = 2)
    # ranked = [docC, docA, docB] -> hits at index 1 and 2
    # DCG@3 = 0/log2(2) + 1/log2(3) + 1/log2(4) = 0 + 1/1.5849625 + 0.5 = 0.63092975 + 0.5 = 1.13092975
    # IDCG@3 = 1/log2(2) + 1/log2(3) = 1 + 0.63092975 = 1.63092975
    # nDCG@3 = 1.13092975 / 1.63092975 ≈ 0.6934
    ranked = ["docC", "docA", "docB"]
    expected = ["docA", "docB"]
    val = ndcg_at_k(ranked, expected, k=3)
    assert val is not None
    assert abs(val - 0.6934) < 1e-4
