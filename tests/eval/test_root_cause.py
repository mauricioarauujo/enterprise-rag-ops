"""Unit tests for the per-fact root-cause attribution leaf (ACs 1-7, FR-1/2/4).

All offline: pure-Python predicate + rollup over hand-built records. No network, no API
key, no mocked LLM (NFR-2). A local `_fv`/`_record_with_facts` factory keeps per-fact /
retrieval_ranked_ids directly controllable (the taxonomy test helper does not expose
per_fact, so duplicating a tiny factory here is cleaner than cross-importing).
"""

from __future__ import annotations

import pytest

from enterprise_rag_ops.eval.records import (
    CallStats,
    EvalRecord,
    GenAiFields,
    GenAiOperation,
    GenAiRequest,
)
from enterprise_rag_ops.eval.root_cause import (
    RootCauseRollup,
    classify_fact_gap,
    rollup,
)
from enterprise_rag_ops.eval.schema import FactVerdict


def _fv(fact: str, verdict: str, supporting_doc_id: str | None = None) -> FactVerdict:
    return FactVerdict(fact=fact, verdict=verdict, supporting_doc_id=supporting_doc_id)


def _record_with_facts(
    per_fact: list[FactVerdict] | None,
    retrieval_ranked_ids: list[str],
) -> EvalRecord:
    """Minimal EvalRecord with controllable per_fact / retrieval_ranked_ids."""
    return EvalRecord(
        question_id="q1",
        category="test-category",
        run_id="test-run",
        k=10,
        gen_ai=GenAiFields(
            request=GenAiRequest(model="test-model"),
            system="test-system",
            operation=GenAiOperation(name="chat"),
        ),
        generation=CallStats(
            input_tokens=10,
            output_tokens=10,
            latency_s=0.5,
            model="test-model",
            system="test-system",
            cost_usd=0.0001,
        ),
        judge=CallStats(
            input_tokens=10,
            output_tokens=10,
            latency_s=0.5,
            model="test-model",
            system="test-system",
            cost_usd=0.0001,
        ),
        answer="test answer",
        sources=[],
        fact_recall=1.0,
        fact_precision=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=retrieval_ranked_ids,
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        per_fact=per_fact,
    )


def test_present_fact_returns_none():
    """AC-1: a `present` fact is never a failure, regardless of supporting_doc_id/membership."""
    assert classify_fact_gap(_fv("f", "present", "doc_x"), ["doc_x"]) is None
    assert classify_fact_gap(_fv("f", "present", None), []) is None
    assert classify_fact_gap(_fv("f", "present", "off_set"), ["doc_x"]) is None


@pytest.mark.parametrize("verdict", ["absent", "contradicted"])
def test_failed_fact_none_doc_is_retrieval_gap(verdict):
    """AC-2: a failed fact with supporting_doc_id None -> retrieval_gap (both verdicts)."""
    assert classify_fact_gap(_fv("f", verdict, None), ["doc_real"]) == "retrieval_gap"


def test_failed_fact_retrieved_doc_is_generation_gap():
    """AC-3: a failed fact whose supporting doc IS retrieved -> generation_gap."""
    assert classify_fact_gap(_fv("f", "absent", "doc_real"), ["doc_real"]) == "generation_gap"


def test_failed_fact_out_of_set_doc_is_retrieval_gap_defensive():
    """AC-4: non-None supporting_doc_id NOT in the retrieved set -> retrieval_gap (FR-4)."""
    assert classify_fact_gap(_fv("f", "absent", "gd_hallucinated"), ["doc_real"]) == "retrieval_gap"


def test_output_domain_over_matrix():
    """AC-5: every return is in {"retrieval_gap", "generation_gap", None} across the matrix."""
    retrieval_ranked_ids = ["doc_real"]
    doc_id_options = [None, "doc_real", "gd_out_of_set"]
    for verdict in ["present", "absent", "contradicted"]:
        for doc_id in doc_id_options:
            result = classify_fact_gap(_fv("f", verdict, doc_id), retrieval_ranked_ids)
            assert result in {"retrieval_gap", "generation_gap", None}


def test_rollup_counts_mixed_facts():
    """AC-6: rollup sums failed facts correctly into retrieval_gap / generation_gap."""
    record = _record_with_facts(
        per_fact=[
            _fv("a", "present", "doc_real"),
            _fv("b", "absent", None),
            _fv("c", "contradicted", "doc_real"),
            _fv("d", "absent", "out_of_set"),
        ],
        retrieval_ranked_ids=["doc_real"],
    )
    rc = rollup(record)
    assert rc.retrieval_gap == 2
    assert rc.generation_gap == 1
    assert rc.no_failed_facts is False
    assert rc.has_per_fact is True
    assert rc.total_failed == 3


def test_rollup_zero_failed_facts_distinct_from_degraded():
    """AC-6: per-fact evidence present, zero failed facts -> no_failed_facts True, not degraded."""
    record = _record_with_facts(
        per_fact=[
            _fv("a", "present", "doc_real"),
            _fv("b", "present", None),
        ],
        retrieval_ranked_ids=["doc_real"],
    )
    rc = rollup(record)
    assert rc.no_failed_facts is True
    assert rc.has_per_fact is True
    assert rc.total_failed == 0


def test_rollup_per_fact_none_degrades():
    """AC-7: rollup over per_fact=None does not raise; degraded marker distinct from zero-gaps."""
    record = _record_with_facts(per_fact=None, retrieval_ranked_ids=["doc_real"])
    rc = rollup(record)
    assert isinstance(rc, RootCauseRollup)
    assert rc.has_per_fact is False
    assert rc.retrieval_gap == 0
    assert rc.generation_gap == 0
    assert rc.no_failed_facts is False
    assert rc.total_failed == 0
