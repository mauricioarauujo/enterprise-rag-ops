# EvalRecord Schema and JSONL Persistence

> **Purpose**: The shape of one persisted evaluation record (one question x one model),
> its OTEL alignment, what it deliberately excludes, and the key-per-record fields
> added in Phase 6.
> **Confidence**: HIGH (codebase — `eval/records.py`, ADR-0007)
> **ADR**: `docs/adr/0007-eval-record-schema.md`

## What One Record Captures

`EvalRecord` (Pydantic model in `eval/records.py`) is one JSONL line written per
question per generator model. It embeds everything needed to reconstruct the baseline
report without re-running the sweep.

```
question_id   — identifies the question in the benchmark
category      — question category (10 categories in EnterpriseRAG-Bench)
run_id        — identifies the sweep (e.g. "baseline")
k             — retrieval cut-off the run used (NOT hard-coded; read by report)
gen_ai        — OTEL GenAI namespace: gen_ai.request.model + gen_ai.system
generation    — CallStats: tokens, latency_s, model, system, cost_usd
judge         — CallStats: same shape, for the judge call
answer        — the generator's answer string
sources       — list[str] of cited doc_ids
fact_recall / fact_precision / faithfulness_ratio — float|None aggregates
retrieval_ranked_ids — deduplicated doc-level IDs (retrieval metric input)
did_abstain_retrieval / did_abstain_e2e — bool flags
failure_mode  — str|None: failure-taxonomy tag, written by `rag-classify` post-hoc
                (None until classified). Backward-compatible (added Sprint 3 / Phase 8).
```

The `failure_mode` field is persisted here but **owned by the observability domain** —
its vocabulary, cascade, and thresholds live in
[observability/failure-taxonomy](../../observability/concepts/failure-taxonomy.md). This
concept only records that the field exists on the schema.

## What the Record Deliberately Excludes

`per_fact` and `per_citation` verdict lists are **not persisted**. They are produced by
the judge and used on-the-fly to compute the three aggregates, then discarded. This
limits the JSONL footprint and avoids storing the raw LLM judge output verbatim.

The three floats (`fact_recall`, `fact_precision`, `faithfulness_ratio`) are the
Python-derived aggregates stored in the record — the LLM never emits them directly
(see `concepts/schema-as-ssot.md`).

## OTEL GenAI Alignment

The `gen_ai` nested object mirrors the OTEL GenAI semantic conventions:

```python
gen_ai.request.model  →  gen_ai_request_model  (OTEL attribute)
gen_ai.system         →  gen_ai_system         ("openai" | "anthropic" | "google")
gen_ai.operation.name →  gen_ai_operation_name (default "chat")
```

This alignment positions records for future trace ingestion without schema migration.

## The `k` Field

`k` (retrieval cut-off, default 10) is persisted on every record so the report reads
it dynamically rather than hard-coding 10. A run with `k=5` would produce
`Recall@5` headers, not mislabelled `Recall@10` headers. The `k` value is constant
across a run; reading from `records[0].k` in the report is correct.

## `retrieval_ranked_ids`

Stored as **deduplicated doc-level IDs** (not chunk IDs). The runner calls
`deduplicate_ranked_ids` on the raw `chunk_id` list returned by the retriever; the
result maps `chunk_id` → `doc_id` via `split("::")[0]` before deduplication. The
report's per-category retrieval aggregation consumes this field directly.

## Related

- `eval/records.py` — `EvalRecord`, `CallStats`, `Price`, `compute_cost_usd`
- `docs/adr/0007-eval-record-schema.md`
- [cost-accounting.md](cost-accounting.md)
- [../patterns/multi-model-runner.md](../patterns/multi-model-runner.md)
