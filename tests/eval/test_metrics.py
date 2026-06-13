"""Unit tests for compute_cost_per_correct (sprint-7/phase-3, FR-8 / AC-3, AC-4, AC-5).

Cassette-free: the helper is pure arithmetic over constructed EvalRecord fixtures — it
touches no LLM API, so ADR-0006 (cassette/replay) does not apply.
"""

from __future__ import annotations

import pytest

from enterprise_rag_ops.eval.metrics import compute_cost_per_correct
from enterprise_rag_ops.eval.records import CallStats, EvalRecord


def _record(gen_cost: float | None, failure_mode: str, judge_cost: float = 0.0) -> EvalRecord:
    """Build a minimal classified EvalRecord with the only fields the metric reads:
    generation.cost_usd and failure_mode. judge_cost defaults to 0.0 but is set large in the
    judge-cost-ignored case to prove it never enters the numerator."""
    return EvalRecord(
        question_id="q",
        category="general",
        run_id="test",
        gen_ai={"request": {"model": "m"}, "system": "openai"},
        generation=CallStats(
            input_tokens=0,
            output_tokens=0,
            latency_s=0.0,
            model="m",
            system="openai",
            cost_usd=gen_cost,
        ),
        judge=CallStats(
            input_tokens=0,
            output_tokens=0,
            latency_s=0.0,
            model="j",
            system="openai",
            cost_usd=judge_cost,
        ),
        answer="a",
        sources=[],
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        failure_mode=failure_mode,
    )


def test_cost_per_correct_exact_all_correct():
    """AC-3: two correct records, gen costs 0.10 + 0.30 -> 0.40 / 2 == 0.20."""
    records = [_record(0.10, "correct"), _record(0.30, "correct")]
    assert compute_cost_per_correct(records) == pytest.approx(0.20)


def test_cost_per_correct_numerator_over_all_denominator_over_correct():
    """AC-3: numerator sums ALL records; denominator counts only correct ones.
    0.10 + 0.30 + 0.60 == 1.00 spent; 2 correct -> 0.50 per correct."""
    records = [
        _record(0.10, "correct"),
        _record(0.30, "correct"),
        _record(0.60, "hallucination"),
    ]
    assert compute_cost_per_correct(records) == pytest.approx(0.50)


def test_cost_per_correct_zero_correct_returns_none():
    """AC-4: a group with no correct answers -> None (not 0, not ZeroDivisionError)."""
    records = [_record(0.10, "hallucination"), _record(0.30, "over_abstention")]
    assert compute_cost_per_correct(records) is None


def test_cost_per_correct_none_summand_treated_as_zero():
    """AC-5: a record with generation.cost_usd=None contributes 0.0; no crash.
    None + 0.40 == 0.40 over 2 correct -> 0.20."""
    records = [_record(None, "correct"), _record(0.40, "correct")]
    assert compute_cost_per_correct(records) == pytest.approx(0.20)


def test_cost_per_correct_single_correct_record():
    """Single correct record -> its own gen cost."""
    assert compute_cost_per_correct([_record(0.07, "correct")]) == pytest.approx(0.07)


def test_cost_per_correct_single_incorrect_record_returns_none():
    """Single incorrect record -> None (zero correct)."""
    assert compute_cost_per_correct([_record(0.07, "hallucination")]) is None


def test_cost_per_correct_ignores_judge_cost():
    """Judge cost is eval overhead and must never enter the numerator: a huge judge_cost
    does not change the result (0.10 / 1 == 0.10)."""
    records = [_record(0.10, "correct", judge_cost=99.0)]
    assert compute_cost_per_correct(records) == pytest.approx(0.10)


def test_cost_per_correct_empty_iterable_returns_none():
    """No records -> denominator 0 -> None."""
    assert compute_cost_per_correct([]) is None


def test_cost_per_correct_accepts_iterator():
    """The helper materializes its input, so a one-shot iterator works (not just a list)."""
    records = iter([_record(0.10, "correct"), _record(0.30, "correct")])
    assert compute_cost_per_correct(records) == pytest.approx(0.20)
