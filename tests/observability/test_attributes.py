"""Tests for pure span attribute mapping and verdict hydration (AC-7).

sprint-8/phase-3: each judge-span fact line now carries its `supporting_doc_id` (or the
`—` sentinel) and, for failed facts, the phase-2 root-cause label (`retrieval_gap` /
`generation_gap`) from `classify_fact_gap`. All offline — pure mapper, no LLM call.
"""

import inspect

from enterprise_rag_ops.eval.records import CallStats, EvalRecord
from enterprise_rag_ops.eval.root_cause import classify_fact_gap
from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict
from enterprise_rag_ops.observability import attributes
from enterprise_rag_ops.observability.attributes import build_span_attrs


def _make_record(
    per_fact: list[FactVerdict] | None = None,
    per_citation: list[CitationVerdict] | None = None,
    retrieval_ranked_ids: list[str] | None = None,
    judge_cost_usd: float | None = None,
) -> EvalRecord:
    """Minimal EvalRecord with controllable per_fact / retrieval_ranked_ids (offline)."""
    return EvalRecord(
        question_id="q1",
        category="test",
        run_id="run1",
        k=5,
        gen_ai={"request": {"model": "m1"}, "system": "openai"},
        generation=CallStats(
            input_tokens=0, output_tokens=0, latency_s=0.0, model="m1", system="openai"
        ),
        judge=CallStats(
            input_tokens=0,
            output_tokens=0,
            latency_s=0.0,
            model="j1",
            system="openai",
            cost_usd=judge_cost_usd,
        ),
        answer="answer",
        sources=["d1"],
        fact_recall=1.0,
        fact_precision=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=retrieval_ranked_ids if retrieval_ranked_ids is not None else ["d1"],
        did_abstain_retrieval=False,
        did_abstain_e2e=False,
        per_fact=per_fact,
        per_citation=per_citation,
    )


def test_build_span_attrs_verdict_hydration_present():
    """AC-2/AC-9: fact prefix preserved; doc suffix added; citation lines unchanged, after facts."""
    record = _make_record(
        per_fact=[
            FactVerdict(fact="fact1", verdict="present", supporting_doc_id="d1"),
            FactVerdict(fact="fact2", verdict="absent", supporting_doc_id=None),
        ],
        per_citation=[
            CitationVerdict(doc_id="d1", verdict="supported"),
            CitationVerdict(doc_id="d2", verdict="unsupported"),
        ],
        retrieval_ranked_ids=["d1"],
    )

    judge_attrs = build_span_attrs(record)["judge"]

    assert judge_attrs["output.mime_type"] == "text/plain"
    expected_value = (
        "fact: fact1 -> present [doc: d1]\n"
        "fact: fact2 -> absent [doc: — | retrieval_gap]\n"
        "citation: d1 -> supported\n"
        "citation: d2 -> unsupported"
    )
    assert judge_attrs["output.value"] == expected_value


def test_fact_line_carries_supporting_doc_id():
    """AC-1/SC-4: a fact's supporting_doc_id is surfaced on the judge span."""
    record = _make_record(
        per_fact=[FactVerdict(fact="f", verdict="present", supporting_doc_id="doc-12")],
        retrieval_ranked_ids=["doc-12"],
    )
    assert "[doc: doc-12]" in build_span_attrs(record)["judge"]["output.value"]


def test_failed_fact_generation_gap_absent():
    """AC-4: failed (absent) fact whose supporting doc IS retrieved -> generation_gap label."""
    record = _make_record(
        per_fact=[FactVerdict(fact="f", verdict="absent", supporting_doc_id="doc-12")],
        retrieval_ranked_ids=["doc-12"],
    )
    assert build_span_attrs(record)["judge"]["output.value"] == (
        "fact: f -> absent [doc: doc-12 | generation_gap]"
    )


def test_failed_fact_generation_gap_contradicted():
    """AC-4: the other failed verdict (contradicted) also yields the generation_gap label."""
    record = _make_record(
        per_fact=[FactVerdict(fact="f", verdict="contradicted", supporting_doc_id="doc-12")],
        retrieval_ranked_ids=["doc-12"],
    )
    assert "[doc: doc-12 | generation_gap]" in build_span_attrs(record)["judge"]["output.value"]


def test_failed_fact_retrieval_gap_none_doc():
    """AC-5/AC-7: failed fact with None doc -> `—` sentinel + retrieval_gap (full-line, em-dash)."""
    record = _make_record(
        per_fact=[FactVerdict(fact="f", verdict="absent", supporting_doc_id=None)],
        retrieval_ranked_ids=["doc-real"],
    )
    line = build_span_attrs(record)["judge"]["output.value"]
    assert line == "fact: f -> absent [doc: — | retrieval_gap]"
    assert "None" not in line
    assert "—" in line  # U+2014 em-dash, not a hyphen/en-dash


def test_present_fact_has_doc_no_label():
    """AC-3/AC-6: a present fact shows its doc but no root-cause label (it has no gap)."""
    record = _make_record(
        per_fact=[FactVerdict(fact="f", verdict="present", supporting_doc_id="doc-9")],
        retrieval_ranked_ids=["doc-9"],
    )
    line = build_span_attrs(record)["judge"]["output.value"]
    assert "[doc: doc-9]" in line
    assert "retrieval_gap" not in line
    assert "generation_gap" not in line


def test_label_matches_classify_fact_gap_predicate():
    """AC-11: the rendered label on each fact line equals classify_fact_gap (no reimplementation)."""
    record = _make_record(
        per_fact=[
            FactVerdict(fact="a", verdict="absent", supporting_doc_id="doc-in"),
            FactVerdict(fact="b", verdict="contradicted", supporting_doc_id=None),
            FactVerdict(fact="c", verdict="present", supporting_doc_id="doc-in"),
        ],
        retrieval_ranked_ids=["doc-in"],
    )
    value = build_span_attrs(record)["judge"]["output.value"]
    lines = value.splitlines()
    for fv, line in zip(record.per_fact, lines, strict=True):
        gap = classify_fact_gap(fv, record.retrieval_ranked_ids)
        if gap is not None:
            assert f"| {gap}]" in line
        else:
            assert "|" not in line


def test_judge_attrs_key_set():
    """Judge-span attribute key set. Sprint-8 introduced no eval.fact.* keys; B-05 then added
    the OpenInference `llm.*` cost keys alongside the OTEL `gen_ai.*` keys (no key removed)."""
    record = _make_record(
        per_fact=[FactVerdict(fact="f", verdict="present", supporting_doc_id="d1")],
        per_citation=[CitationVerdict(doc_id="d1", verdict="supported")],
        retrieval_ranked_ids=["d1"],
        judge_cost_usd=0.001,
    )
    judge_attrs = build_span_attrs(record)["judge"]
    assert set(judge_attrs) == {
        "gen_ai.request.model",
        "gen_ai.system",
        "gen_ai.operation.name",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "latency_s",
        "output.value",
        "output.mime_type",
        "cost_usd",
        # B-05: OpenInference cost-widget keys
        "llm.token_count.prompt",
        "llm.token_count.completion",
        "llm.token_count.total",
        "llm.model_name",
        "llm.provider",
    }
    # No eval.fact.* keys (sprint-8 invariant preserved).
    assert not any(k.startswith("eval.fact") for k in judge_attrs)


def test_llm_token_keys_helper_maps_distinct_values():
    """B-05: the cost-widget helper maps prompt/completion/total/model/provider correctly
    (distinct token values so prompt, completion, and total can't be confused)."""
    stats = CallStats(input_tokens=11, output_tokens=7, latency_s=1.0, model="m1", system="openai")
    assert attributes._llm_token_keys(stats) == {
        "llm.token_count.prompt": 11,
        "llm.token_count.completion": 7,
        "llm.token_count.total": 18,
        "llm.model_name": "m1",
        "llm.provider": "openai",
    }


def test_llm_cost_keys_present_on_both_llm_spans():
    """B-05: both LLM spans (generation + judge) carry the llm.* cost keys, and the OTEL
    gen_ai.* keys remain (additive — no key removed)."""
    attrs = build_span_attrs(_make_record())
    for role in ("generation", "judge"):
        a = attrs[role]
        assert {"llm.token_count.prompt", "llm.token_count.total", "llm.model_name"} <= set(a)
        assert "gen_ai.usage.input_tokens" in a  # OTEL key still present


def test_attributes_module_has_no_phoenix_or_otel_import():
    """AC-10/NFR-1: mapper purity — no phoenix/opentelemetry import (root_cause leaf only)."""
    import_lines = [
        line
        for line in inspect.getsource(attributes).splitlines()
        if line.startswith(("import ", "from "))
    ]
    joined = "\n".join(import_lines)
    assert "phoenix" not in joined
    assert "opentelemetry" not in joined


def test_build_span_attrs_verdict_hydration_both_none():
    """AC-8: no output.value/mime_type keys when both verdict lists are None."""
    judge_attrs = build_span_attrs(_make_record(per_fact=None, per_citation=None))["judge"]
    assert "output.value" not in judge_attrs
    assert "output.mime_type" not in judge_attrs


def test_build_span_attrs_verdict_hydration_both_empty():
    """AC-8: no output.value/mime_type keys when both verdict lists are empty."""
    judge_attrs = build_span_attrs(_make_record(per_fact=[], per_citation=[]))["judge"]
    assert "output.value" not in judge_attrs
    assert "output.mime_type" not in judge_attrs
