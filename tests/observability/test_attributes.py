"""Tests for pure span attribute mapping and verdict hydration (AC-7)."""

from enterprise_rag_ops.eval.records import CallStats, EvalRecord
from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict
from enterprise_rag_ops.observability.attributes import build_span_attrs


def test_build_span_attrs_verdict_hydration_present():
    """Assert hydration of per_fact and per_citation verdicts onto judge span (AC-7a)."""
    record = EvalRecord(
        question_id="q1",
        category="test",
        run_id="run1",
        k=5,
        gen_ai={"request": {"model": "m1"}, "system": "openai"},
        generation=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="m1", system="openai"
        ),
        judge=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="j1", system="openai"
        ),
        answer="answer",
        sources=["d1"],
        fact_recall=1.0,
        fact_precision=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["d1"],
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        per_fact=[
            FactVerdict(fact="fact1", verdict="present"),
            FactVerdict(fact="fact2", verdict="absent"),
        ],
        per_citation=[
            CitationVerdict(doc_id="d1", verdict="supported"),
            CitationVerdict(doc_id="d2", verdict="unsupported"),
        ],
    )

    attrs = build_span_attrs(record)
    judge_attrs = attrs["judge"]

    assert judge_attrs["output.mime_type"] == "text/plain"

    expected_value = (
        "fact: fact1 -> present\n"
        "fact: fact2 -> absent\n"
        "citation: d1 -> supported\n"
        "citation: d2 -> unsupported"
    )
    assert judge_attrs["output.value"] == expected_value


def test_build_span_attrs_verdict_hydration_both_none():
    """Assert no output.value/mime_type keys when both verdict lists are None (AC-7b)."""
    record = EvalRecord(
        question_id="q1",
        category="test",
        run_id="run1",
        k=5,
        gen_ai={"request": {"model": "m1"}, "system": "openai"},
        generation=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="m1", system="openai"
        ),
        judge=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="j1", system="openai"
        ),
        answer="answer",
        sources=["d1"],
        fact_recall=None,
        fact_precision=None,
        faithfulness_ratio=None,
        retrieval_ranked_ids=["d1"],
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        per_fact=None,
        per_citation=None,
    )

    attrs = build_span_attrs(record)
    judge_attrs = attrs["judge"]

    assert "output.value" not in judge_attrs
    assert "output.mime_type" not in judge_attrs


def test_build_span_attrs_verdict_hydration_both_empty():
    """Assert no output.value/mime_type keys when both verdict lists are empty (AC-7c)."""
    record = EvalRecord(
        question_id="q1",
        category="test",
        run_id="run1",
        k=5,
        gen_ai={"request": {"model": "m1"}, "system": "openai"},
        generation=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="m1", system="openai"
        ),
        judge=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="j1", system="openai"
        ),
        answer="answer",
        sources=["d1"],
        fact_recall=None,
        fact_precision=None,
        faithfulness_ratio=None,
        retrieval_ranked_ids=["d1"],
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        per_fact=[],
        per_citation=[],
    )

    attrs = build_span_attrs(record)
    judge_attrs = attrs["judge"]

    assert "output.value" not in judge_attrs
    assert "output.mime_type" not in judge_attrs
