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


def test_eval_record_roundtrip_and_presence():
    """AC-1: EvalRecord serializes and round-trips; includes per_fact/per_citation."""
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

    # Assert presence of per_fact and per_citation
    assert "per_fact" in EvalRecord.model_fields
    assert "per_citation" in EvalRecord.model_fields

    schema = EvalRecord.model_json_schema()
    assert "per_fact" in schema["properties"]
    assert "per_citation" in schema["properties"]


def test_eval_record_schema_ac1():
    """AC-1: model_fields['per_fact']/['per_citation'] exist, default None, annotated list[FactVerdict] | None / list[CitationVerdict] | None; FactVerdict/CitationVerdict imported from eval.schema, no new model in records.py."""
    from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict

    assert "per_fact" in EvalRecord.model_fields
    assert "per_citation" in EvalRecord.model_fields

    assert EvalRecord.model_fields["per_fact"].default is None
    assert EvalRecord.model_fields["per_citation"].default is None

    assert EvalRecord.model_fields["per_fact"].annotation == list[FactVerdict] | None
    assert EvalRecord.model_fields["per_citation"].annotation == list[CitationVerdict] | None


def test_eval_record_lossless_roundtrip_ac2():
    """AC-2: build EvalRecord with per_fact=[FactVerdict(fact='X', verdict='present')] and per_citation=[CitationVerdict(doc_id='d1', verdict='supported')]; assert EvalRecord.model_validate_json(rec.model_dump_json()) == rec and JSON contains the keys + label values."""
    from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict

    rec = EvalRecord(
        question_id="q_test",
        category="general",
        run_id="run_1",
        gen_ai={
            "request": {"model": "test-gen"},
            "system": "openai",
        },
        generation=CallStats(
            input_tokens=10, output_tokens=5, latency_s=0.1, model="test-gen", system="openai"
        ),
        judge=CallStats(
            input_tokens=20, output_tokens=10, latency_s=0.2, model="test-judge", system="openai"
        ),
        answer="Hello",
        sources=["doc_a"],
        fact_recall=1.0,
        fact_precision=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["doc_a"],
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        per_fact=[FactVerdict(fact="X", verdict="present")],
        per_citation=[CitationVerdict(doc_id="d1", verdict="supported")],
    )

    # Lossless round-trip
    dumped_json = rec.model_dump_json()
    parsed = EvalRecord.model_validate_json(dumped_json)
    assert parsed == rec

    # Assert JSON contains keys + label values
    import json

    parsed_json = json.loads(dumped_json)
    assert "per_fact" in parsed_json
    assert "per_citation" in parsed_json
    assert parsed_json["per_fact"] == [{"fact": "X", "verdict": "present"}]
    assert parsed_json["per_citation"] == [{"doc_id": "d1", "verdict": "supported"}]


def test_eval_record_backward_compat_ac3(tmp_path):
    """AC-3: a record dict with NO per_fact/per_citation keys parses via model_validate/model_validate_json with both == None, no ValidationError. Also tests a representative reader path (load_run_records)."""
    from enterprise_rag_ops.dashboard.data import load_run_records

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

    # model_validate
    rec = EvalRecord.model_validate(record_dict)
    assert rec.per_fact is None
    assert rec.per_citation is None

    # model_validate_json
    import json

    dumped = json.dumps(record_dict)
    rec_json = EvalRecord.model_validate_json(dumped)
    assert rec_json.per_fact is None
    assert rec_json.per_citation is None

    # Test representative reader path (load_run_records)
    temp_file = tmp_path / "test_run.jsonl"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(dumped + "\n")

    loaded_records = load_run_records([temp_file])
    assert len(loaded_records) == 1
    assert loaded_records[0].question_id == "q1"
    assert loaded_records[0].per_fact is None
    assert loaded_records[0].per_citation is None


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


def test_compute_cost_usd_gemini():
    """AC-8: Price(0.10, 0.40) for gemini-2.5-flash-lite yields non-None compute_cost_usd for system='google' CallStats."""
    stats = CallStats(
        input_tokens=100_000,
        output_tokens=50_000,
        latency_s=0.5,
        model="gemini-2.5-flash-lite",
        system="google",
    )
    price = Price(input_usd_per_1m=0.10, output_usd_per_1m=0.40)
    cost = compute_cost_usd(stats, price)
    assert cost is not None
    assert cost == pytest.approx(0.03)


def test_call_stats_confidence_score():
    """Verify confidence_score field on CallStats: exists, defaulted, and round-trips correctly."""
    # 1. Assert exists, is annotated float | None, default None
    assert "confidence_score" in CallStats.model_fields
    assert CallStats.model_fields["confidence_score"].annotation == float | None
    assert CallStats.model_fields["confidence_score"].default is None

    # 2. Built without confidence_score
    stats_no_conf = CallStats(
        input_tokens=100,
        output_tokens=50,
        latency_s=0.5,
        model="gemini-2.5-flash-lite",
        system="google",
    )
    assert stats_no_conf.confidence_score is None
    dumped_no_conf = stats_no_conf.model_dump_json()
    loaded_no_conf = CallStats.model_validate_json(dumped_no_conf)
    assert loaded_no_conf.confidence_score is None

    # 3. Built with confidence_score=0.42
    stats_with_conf = CallStats(
        input_tokens=100,
        output_tokens=50,
        latency_s=0.5,
        model="gemini-2.5-flash-lite",
        system="google",
        confidence_score=0.42,
    )
    assert stats_with_conf.confidence_score == 0.42
    dumped_with_conf = stats_with_conf.model_dump_json()
    assert "confidence_score" in dumped_with_conf
    loaded_with_conf = CallStats.model_validate_json(dumped_with_conf)
    assert loaded_with_conf.confidence_score == 0.42
