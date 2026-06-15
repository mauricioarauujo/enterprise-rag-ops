"""Tests for pure-Python verdict aggregation (AC-4).

No network, no LLM call — hand-built verdict lists in, three floats out, including the
`None` empty-denominator convention.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.aggregate import aggregate
from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict


def _facts(*verdicts: str) -> list[FactVerdict]:
    return [FactVerdict(fact=f"f{i}", verdict=v) for i, v in enumerate(verdicts)]


def _citations(*verdicts: str) -> list[CitationVerdict]:
    return [CitationVerdict(doc_id=f"d{i}", verdict=v) for i, v in enumerate(verdicts)]


def test_formulas_over_mixed_verdicts():
    per_fact = _facts("present", "present", "absent", "contradicted")
    per_citation = _citations("supported", "unsupported", "supported")
    recall, precision, faithfulness = aggregate(per_fact, per_citation)
    assert recall == 2 / 4  # |present| / |facts|
    assert precision == 2 / 3  # |present| / (|present| + |contradicted|)
    assert faithfulness == 2 / 3  # |supported| / |citations|


def test_all_present_all_supported_is_one():
    recall, precision, faithfulness = aggregate(
        _facts("present", "present"), _citations("supported")
    )
    assert recall == 1.0
    assert precision == 1.0
    assert faithfulness == 1.0


def test_empty_facts_yields_none_recall():
    recall, precision, faithfulness = aggregate([], _citations("supported"))
    assert recall is None
    assert precision is None  # no present, no contradicted → 0 denominator
    assert faithfulness == 1.0


def test_empty_citations_yields_none_faithfulness():
    recall, _, faithfulness = aggregate(_facts("present"), [])
    assert recall == 1.0
    assert faithfulness is None


def test_all_absent_yields_none_precision_zero_recall():
    """No present and no contradicted → precision denominator is 0 → None."""
    recall, precision, _ = aggregate(_facts("absent", "absent"), [])
    assert recall == 0.0
    assert precision is None


def test_full_abstention_is_all_none():
    """An abstention with no facts and no citations → (None, None, None), not zeros."""
    assert aggregate([], []) == (None, None, None)


def test_deterministic():
    pf = _facts("present", "contradicted")
    pc = _citations("supported", "unsupported")
    assert aggregate(pf, pc) == aggregate(pf, pc)


def test_supporting_doc_id_does_not_affect_aggregates():
    """AC-8: aggregate ignores supporting_doc_id — identical floats with/without it."""
    pc = _citations("supported", "unsupported")
    without = [
        FactVerdict(fact="f0", verdict="present"),
        FactVerdict(fact="f1", verdict="contradicted"),
    ]
    with_attr = [
        FactVerdict(fact="f0", verdict="present", supporting_doc_id="doc_a"),
        FactVerdict(fact="f1", verdict="contradicted", supporting_doc_id=None),
    ]
    assert aggregate(without, pc) == aggregate(with_attr, pc)
