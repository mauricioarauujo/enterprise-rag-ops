# Observability Quick Reference

> Fast lookup tables. For code, see linked patterns.

## Span Tree Structure

| Span Name              | OI `span_kind` | Parent | Key Attributes                                                                                                      |
| ---------------------- | -------------- | ------ | ------------------------------------------------------------------------------------------------------------------- |
| `{question_id}` (root) | `"chain"`      | —      | `question_id`, `category`, `run_id`, `k`, `gen_ai.*`, `cost_usd_total`\*; `input.value`\*\* (opt-in)                |
| `"retriever"`          | `"retriever"`  | chain  | `retrieval.documents.{i}.document.id`, `.rank`; `.content`\*\*\* (opt-in)                                           |
| `"generation"`         | `"llm"`        | chain  | `gen_ai.request.model`, `gen_ai.usage.{input,output}_tokens`, `cost_usd`\*, `latency_s`, `output.value` (always-on) |
| `"judge"`              | `"llm"`        | chain  | same gen_ai shape as generation; `output.value` (always-on when verdicts non-empty), `cost_usd`\*                   |

\*Only written when value is non-None.
\*\*`input.value`/`input.mime_type` hydrated at exporter boundary when `--enrich-from-questions` is passed; pure mapper does not set these.
\*\*\*`.content` hydrated at exporter boundary when `--enrich-from-index` is passed; pure mapper writes `.id`/`.rank` only.

## Score Metrics → Span Alignment

| Metric                  | Span       | Type    | Values                                |
| ----------------------- | ---------- | ------- | ------------------------------------- |
| `did_abstain_e2e`       | chain      | BOOLEAN | `1.0`/`0.0`, label `"true"`/`"false"` |
| `did_abstain_retrieval` | retriever  | BOOLEAN | `1.0`/`0.0`, label `"true"`/`"false"` |
| `faithfulness_ratio`    | generation | NUMERIC | `[0.0, 1.0]` or skip if None          |
| `fact_recall`           | judge      | NUMERIC | `[0.0, 1.0]` or skip if None          |
| `fact_precision`        | judge      | NUMERIC | `[0.0, 1.0]` or skip if None          |

## Failure Taxonomy — Cascade Order

| Priority | Label              | Predicate (short form)                                      |
| -------- | ------------------ | ----------------------------------------------------------- |
| 1        | `abstention_error` | `_should_abstain(q) != record.did_abstain_e2e`              |
| 2        | `retrieval_miss`   | answerable AND no gold doc in top-k                         |
| 3        | `hallucination`    | retrieval hit AND `faithfulness_ratio < 0.5`                |
| 4        | `incomplete`       | retrieval hit, faithful, not abstained, `fact_recall < 0.5` |
| 5        | `correct`          | all checks pass                                             |

## Threshold Constants

| Constant                               | Value              | Source                          |
| -------------------------------------- | ------------------ | ------------------------------- |
| `HALLUCINATION_FAITHFULNESS_THRESHOLD` | `0.5` (strict `<`) | `failure_taxonomy.py`, ADR-0008 |
| `INCOMPLETE_RECALL_THRESHOLD`          | `0.5`              | `failure_taxonomy.py`, ADR-0008 |

## CLI Flags

| Command             | Key Flags                              | Effect                                                                   |
| ------------------- | -------------------------------------- | ------------------------------------------------------------------------ |
| `rag-export-traces` | `--results`, `--endpoint`, `--project` | Replay JSONL → Phoenix                                                   |
| `rag-export-traces` | `--dry-run`                            | Validate JSONL only; no Phoenix connection                               |
| `rag-export-traces` | `--enrich-from-index`                  | Hydrate `.content` on retriever spans from `corpus.jsonl` (opt-in)       |
| `rag-export-traces` | `--corpus PATH`                        | Override corpus path for `--enrich-from-index` (default: `CORPUS_PATH`)  |
| `rag-export-traces` | `--enrich-from-questions`              | Hydrate `input.value` on chain spans with gold question text (opt-in)    |
| `rag-export-traces` | `--questions-revision SHA`             | Dataset revision SHA for gold question map (default: `DATASET_REVISION`) |
| `rag-classify`      | `--results`, `--output`                | Classify + write tagged JSONL                                            |
| `rag-classify`      | `--dry-run`                            | Print distribution; no file write                                        |

## Endpoint Normalization

| Input form                   | `register(endpoint=)`        | `Client(base_url=)`            |
| ---------------------------- | ---------------------------- | ------------------------------ |
| `http://host:6006`           | `http://host:6006/v1/traces` | `http://host:6006`             |
| `http://host:6006/v1/traces` | unchanged                    | stripped to `http://host:6006` |

## Root-Cause Attribution (sprint-8/phase-2)

| `RootCauseRollup` field | Type   | Meaning                                                                                    |
| ----------------------- | ------ | ------------------------------------------------------------------------------------------ |
| `retrieval_gap`         | `int`  | Failed facts where `supporting_doc_id is None` (evidence never retrieved)                  |
| `generation_gap`        | `int`  | Failed facts where `supporting_doc_id` is in `retrieval_ranked_ids` (retrieved but unused) |
| `has_per_fact`          | `bool` | `False` → degraded (pre-sprint-8 `per_fact=None`); renders **N/A**                         |
| `no_failed_facts`       | `bool` | `True` → evidence present, zero failures; report re-derives from counts                    |

Report null discipline: `any_evidence=False` → `None` → **N/A**; `denom==0` → `0.0` → **0.0%**.

Entry points: `failure_taxonomy.attribute_root_cause(record)` (taxonomy surface) or
`root_cause.rollup(record)` (leaf direct). See `concepts/failure-taxonomy.md`.

## Common Pitfalls

| Don't                                              | Do                                                 |
| -------------------------------------------------- | -------------------------------------------------- |
| Write `cost_usd_total` when either side is None    | Guard with `is not None` on both                   |
| Assume upsert-by-span-id idempotency               | Always `reset_project` before replay               |
| Classify on raw zero `fact_recall` without cascade | Let `abstention_error`/`retrieval_miss` fire first |
| Use `faithfulness_ratio is None` as hallucination  | Skip hallucination check when ratio is None        |
| Check `no_failed_facts` to distinguish N/A from 0% | Check `has_per_fact` first, then `denom==0`        |
