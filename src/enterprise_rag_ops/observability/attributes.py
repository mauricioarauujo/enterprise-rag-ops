"""Module for pure, tool-agnostic mapping of EvalRecord to trace/span attributes (FR-3, FR-5).

Does not import Phoenix or OpenTelemetry, allowing easy unit testing and zero lock-in (NFR-3).
"""

from typing import Any

from enterprise_rag_ops.eval.records import CallStats, EvalRecord
from enterprise_rag_ops.eval.root_cause import classify_fact_gap


def _llm_token_keys(stats: CallStats) -> dict[str, Any]:
    """OpenInference token-count + model keys that drive Phoenix's native cost widget (B-05).

    Phoenix computes per-span cost as token_count x its model-pricing table and aggregates
    to the trace; it reads these `llm.*` keys, not the OTEL `gen_ai.*` keys we also emit.
    """
    return {
        "llm.token_count.prompt": stats.input_tokens,
        "llm.token_count.completion": stats.output_tokens,
        "llm.token_count.total": stats.input_tokens + stats.output_tokens,
        "llm.model_name": stats.model,
        "llm.provider": stats.system,
    }


def build_span_attrs(record: EvalRecord) -> dict[str, dict[str, Any]]:
    """Map an EvalRecord to OpenInference/OTEL attributes for each span in the tree (FR-3).

    Returns:
        dict: A mapping of span role ("chain", "retriever", "generation", "judge") to its
              corresponding dictionary of attributes.
    """
    # 1. Root chain span attributes (metadata and operational parameters)
    chain_attrs = {
        "question_id": record.question_id,
        "category": record.category,
        "run_id": record.run_id,
        "k": record.k,
        "gen_ai.request.model": record.gen_ai.request.model,
        "gen_ai.system": record.gen_ai.system,
        "gen_ai.operation.name": record.gen_ai.operation.name,
    }

    # Cost rule (Q3 / FR-3): Trace-level cost_usd_total only if BOTH costs are known.
    if record.generation.cost_usd is not None and record.judge.cost_usd is not None:
        chain_attrs["cost_usd_total"] = record.generation.cost_usd + record.judge.cost_usd

    # 2. Child retriever span attributes (FR-12 seam)
    retriever_attrs = {}
    for i, doc_id in enumerate(record.retrieval_ranked_ids):
        retriever_attrs[f"retrieval.documents.{i}.document.id"] = doc_id
        retriever_attrs[f"retrieval.documents.{i}.document.rank"] = i

        # Enrichment activated in Phase 16: retrieval.documents.{i}.document.content is
        # hydrated at the exporter boundary (observability/exporter.py), not in this pure
        # mapper, to keep attributes.py free of retrieval/ingest imports (NFR-1). Score
        # (.score) remains out — not persisted in EvalRecord (FR-7).

    # 3. Child generation span attributes
    gen_attrs = {
        "gen_ai.request.model": record.generation.model,
        "gen_ai.system": record.generation.system,
        "gen_ai.operation.name": "chat",
        "gen_ai.usage.input_tokens": record.generation.input_tokens,
        "gen_ai.usage.output_tokens": record.generation.output_tokens,
        "latency_s": record.generation.latency_s,
        # OpenInference token-count + model keys (B-05): Phoenix's native Total Cost widget
        # derives cost from llm.token_count.* x its model-pricing table, NOT from our custom
        # cost_usd. Emitted alongside the OTEL gen_ai.* keys (no key removed); cost_usd stays
        # for the offline report's own accounting.
        **_llm_token_keys(record.generation),
    }
    # Phase 17: hydrate the generated answer onto the generation span as the OpenInference
    # output.value so Phoenix's Info tab renders it. Always-on — record.answer is an in-record
    # field (no external read), mapped like every other field here; only the gold-derived
    # question (input.value, written at the exporter boundary) is opt-in (FR-4/NFR-7).
    gen_attrs["output.value"] = record.answer
    gen_attrs["output.mime_type"] = "text/plain"
    # Cost rule (Q3 / FR-3): Omit cost_usd if it is None (never write 0)
    if record.generation.cost_usd is not None:
        gen_attrs["cost_usd"] = record.generation.cost_usd

    # 4. Child judge span attributes
    judge_attrs = {
        "gen_ai.request.model": record.judge.model,
        "gen_ai.system": record.judge.system,
        "gen_ai.operation.name": "chat",
        "gen_ai.usage.input_tokens": record.judge.input_tokens,
        "gen_ai.usage.output_tokens": record.judge.output_tokens,
        "latency_s": record.judge.latency_s,
        # OpenInference token-count + model keys (B-05) — see the generation span note.
        **_llm_token_keys(record.judge),
    }
    # Build verdict lines for hydration onto the judge span (FR-10, RQ-2).
    # Each fact line carries its supporting_doc_id (or "—" sentinel); failed facts also
    # carry the phase-2 root-cause label from classify_fact_gap (sprint-8/phase-3, FR-1/2/3).
    fact_lines = []
    for fv in record.per_fact or []:
        doc_or_dash = fv.supporting_doc_id if fv.supporting_doc_id is not None else "—"
        gap = classify_fact_gap(fv, record.retrieval_ranked_ids)
        bracket = f"[doc: {doc_or_dash}]" if gap is None else f"[doc: {doc_or_dash} | {gap}]"
        fact_lines.append(f"fact: {fv.fact} -> {fv.verdict} {bracket}")
    lines = fact_lines + [
        f"citation: {cv.doc_id} -> {cv.verdict}" for cv in (record.per_citation or [])
    ]
    if lines:
        judge_attrs["output.value"] = "\n".join(lines)
        judge_attrs["output.mime_type"] = "text/plain"

    # Cost rule (Q3 / FR-3): Omit cost_usd if it is None (never write 0)
    if record.judge.cost_usd is not None:
        judge_attrs["cost_usd"] = record.judge.cost_usd

    return {
        "chain": chain_attrs,
        "retriever": retriever_attrs,
        "generation": gen_attrs,
        "judge": judge_attrs,
    }


def build_score_rows(
    record: EvalRecord, span_ids: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    """Map an EvalRecord and in-process span IDs to annotation rows (FR-5).

    Each row dict contains:
        - span_id (str): The ID of the span to attach the score to.
        - score (float): The numeric evaluation score (1.0 or 0.0 for booleans).
        - label (str): The string value of the evaluation outcome.

    Returns:
        dict: A mapping of metric names ("did_abstain_e2e", "did_abstain_retrieval",
              "faithfulness_ratio", "fact_recall", "fact_precision") to lists of row dicts.
    """
    scores = {}

    # did_abstain_e2e (BOOLEAN) -> root chain
    if "chain" in span_ids:
        scores["did_abstain_e2e"] = [
            {
                "span_id": span_ids["chain"],
                "score": 1.0 if record.did_abstain_e2e else 0.0,
                "label": "true" if record.did_abstain_e2e else "false",
            }
        ]

    # did_abstain_retrieval (BOOLEAN) -> retriever
    if "retriever" in span_ids:
        scores["did_abstain_retrieval"] = [
            {
                "span_id": span_ids["retriever"],
                "score": 1.0 if record.did_abstain_retrieval else 0.0,
                "label": "true" if record.did_abstain_retrieval else "false",
            }
        ]

    # faithfulness_ratio (NUMERIC) -> llm "generation"
    if "generation" in span_ids and record.faithfulness_ratio is not None:
        scores["faithfulness_ratio"] = [
            {
                "span_id": span_ids["generation"],
                "score": float(record.faithfulness_ratio),
                "label": str(record.faithfulness_ratio),
            }
        ]

    # fact_recall (NUMERIC) -> llm "judge"
    if "judge" in span_ids and record.fact_recall is not None:
        scores["fact_recall"] = [
            {
                "span_id": span_ids["judge"],
                "score": float(record.fact_recall),
                "label": str(record.fact_recall),
            }
        ]

    # fact_precision (NUMERIC) -> llm "judge"
    if "judge" in span_ids and record.fact_precision is not None:
        scores["fact_precision"] = [
            {
                "span_id": span_ids["judge"],
                "score": float(record.fact_precision),
                "label": str(record.fact_precision),
            }
        ]

    return scores
