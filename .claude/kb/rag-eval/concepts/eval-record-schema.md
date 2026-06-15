# EvalRecord Schema and JSONL Persistence

> **Purpose**: The shape of one persisted evaluation record (one question x one model),
> its OTEL alignment, the bronze/gold exclusion boundary, and the key-per-record fields
> added in Phase 6 and Phase 18.
> **Confidence**: HIGH (codebase — `eval/records.py`, ADR-0007, ADR-0010)
> **ADRs**: `docs/adr/0007-eval-record-schema.md`, `docs/adr/0010-persist-judge-reasoning-bronze-gold.md`

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
per_fact      — list[FactVerdict]|None: the judge's per-fact verdict list, sourced
                from the in-memory JudgeVerdict at zero extra API cost (ADR-0010).
                Defaults to None; old results/*.jsonl load cleanly (backward-compat).
                Each FactVerdict carries: fact (str), verdict (Literal["present",
                "absent", "contradicted"]), and supporting_doc_id (str|None) — the
                doc_id of the retrieved document most directly supporting the gold fact,
                or None when no retrieved doc covers it (sprint-8/phase-1, backward-
                compatible default).
per_citation  — list[CitationVerdict]|None: the judge's per-citation verdict list,
                same provenance and backward-compatibility as per_fact (ADR-0010).
```

The `failure_mode` field is persisted here but **owned by the observability domain** —
its vocabulary, cascade, and thresholds live in
[observability/failure-taxonomy](../../observability/concepts/failure-taxonomy.md). This
concept only records that the field exists on the schema.

## Bronze / Gold Exclusion Boundary (ADR-0010)

ADR-0007 originally excluded all verdict checklists from gold to limit JSONL footprint.
ADR-0010 (sprint-6/phase-18) narrowed that exclusion with a two-layer split:

**Gold (built, on main):** `per_fact` and `per_citation` ARE now persisted in
`EvalRecord`. They are small discrete label lists (same scale as `sources` /
`retrieval_ranked_ids`), already computed in memory by the judge — so adding them to
gold costs zero extra LLM API calls. The runner populates them directly from the
`JudgeVerdict` returned by `judge_with_stats` (`runner.py`: `per_fact=verdict.per_fact,
per_citation=verdict.per_citation`). Both fields are `list[...] | None = None`
(optional + defaulted), so old `results/*.jsonl` load without migration.

**Bronze (designed in ADR-0010, built in phase-19):** The bulky generation input prompt
(embeds k=10 context chunks) and the raw LLM API response payloads remain excluded from
gold. They are designed for a gitignored bronze archive at
`data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json` with overwrite-by-key
idempotency and an opt-in `persist_bronze` flag (default `False`). The bronze writer
is **not yet built** — phase-19 builds and wires it.

The three floats (`fact_recall`, `fact_precision`, `faithfulness_ratio`) are still
Python-derived aggregates — the LLM never emits them directly
(see `concepts/schema-as-ssot.md`).

**Import:** `records.py` imports `FactVerdict` and `CitationVerdict` directly from the
existing closed `eval/schema.py` models — no new model was introduced.

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
- `eval/schema.py` — `FactVerdict`, `CitationVerdict` (reused by `EvalRecord`)
- `eval/runner.py` — EvalRecord build site (`per_fact=verdict.per_fact`, `per_citation=verdict.per_citation`)
- `docs/adr/0007-eval-record-schema.md` — original schema; Consequences now points to ADR-0010
- `docs/adr/0010-persist-judge-reasoning-bronze-gold.md` — scoped amendment: per_fact/per_citation into gold; bronze design
- [cost-accounting.md](cost-accounting.md)
- [../patterns/multi-model-runner.md](../patterns/multi-model-runner.md)
