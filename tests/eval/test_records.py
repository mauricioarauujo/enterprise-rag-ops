"""Unit tests for EvalRecord, CallStats, and compute_cost_usd (AC-1, AC-3, AC-10)."""

from __future__ import annotations

import logging

import pytest

from enterprise_rag_ops.eval.records import (
    CallStats,
    EvalRecord,
    Price,
    compute_cost_usd,
)


def test_eval_record_roundtrip_and_exclusions():
    """AC-1: EvalRecord serializes and round-trips; excludes per_fact/per_citation."""
    record_dict = {
        "question_id": "q1",
        "category": "legal",
        "run_id": "run_test_123",
        "gen_ai": {
            "request": {"model": "gpt-5-nano-2025-08-07"},
            "system": "openai",
            "operation": {"name": "chat"},
        },
        "generation": {
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_s": 1.2,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.000025,
        },
        "judge": {
            "input_tokens": 200,
            "output_tokens": 10,
            "latency_s": 0.8,
            "model": "gpt-5-nano-2025-08-07",
            "system": "openai",
            "cost_usd": 0.000014,
        },
        "answer": "Yes, Paris is the capital.",
        "sources": ["doc_1"],
        "fact_recall": 1.0,
        "fact_precision": 0.8,
        "faithfulness_ratio": None,
        "retrieval_ranked_ids": ["doc_1", "doc_2"],
        "did_abstain_retrieval": False,
        "did_abstain_e2e": False,
    }

    # Load and validate
    record = EvalRecord.model_validate(record_dict)
    assert record.question_id == "q1"
    assert record.fact_recall == 1.0
    assert record.faithfulness_ratio is None
    assert record.generation.input_tokens == 100

    # Dump to JSON and parse back
    json_data = record.model_dump_json()
    roundtripped = EvalRecord.model_validate_json(json_data)
    assert roundtripped.run_id == "run_test_123"

    # Assert exclusion of per_fact and per_citation
    assert "per_fact" not in EvalRecord.model_fields
    assert "per_citation" not in EvalRecord.model_fields

    schema = EvalRecord.model_json_schema()
    assert "per_fact" not in schema["properties"]
    assert "per_citation" not in schema["properties"]


def test_call_stats_fields():
    """AC-3: CallStats carries specified fields."""
    stats = CallStats(
        input_tokens=150,
        output_tokens=30,
        latency_s=0.75,
        model="claude-3-5-haiku-20241022",
        system="anthropic",
        cost_usd=0.00024,
    )
    assert stats.input_tokens == 150
    assert stats.output_tokens == 30
    assert stats.latency_s == 0.75
    assert stats.model == "claude-3-5-haiku-20241022"
    assert stats.system == "anthropic"
    assert stats.cost_usd == 0.00024


@pytest.mark.parametrize(
    "input_tokens,output_tokens,input_price,output_price,expected_cost",
    [
        (1_000_000, 1_000_000, 0.05, 0.40, 0.45),
        (500_000, 250_000, 0.80, 4.00, 0.40 + 1.00),
        (0, 0, 10.0, 20.0, 0.0),
    ],
)
def test_compute_cost_usd_arithmetic(
    input_tokens, output_tokens, input_price, output_price, expected_cost
):
    """AC-10: cost is calculated correctly per formula: (in/1e6)*price_in + (out/1e6)*price_out."""
    stats = CallStats(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=1.0,
        model="dummy-model",
        system="dummy-sys",
    )
    price = Price(input_usd_per_1m=input_price, output_usd_per_1m=output_price)
    cost = compute_cost_usd(stats, price)
    assert cost == pytest.approx(expected_cost)


def test_compute_cost_usd_missing_price(caplog):
    """AC-10: missing price yields cost_usd = None and logs warning."""
    stats = CallStats(
        input_tokens=100,
        output_tokens=50,
        latency_s=1.0,
        model="missing-model",
        system="missing-system",
    )

    with caplog.at_level(logging.WARNING):
        cost = compute_cost_usd(stats, None)

    assert cost is None
    assert "No price entry found for model missing-model under system missing-system" in caplog.text
