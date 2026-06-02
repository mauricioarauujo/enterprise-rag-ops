# Concept: Span Attribute Mapping

**Confidence**: HIGH — grounded in `attributes.py` (codebase) + OTel/OpenInference semconv
(research pillar 3, verified via ADR-0004).

## What It Is

Each span role maps to a specific set of attributes drawn from `EvalRecord` fields.
Attributes follow **OTel GenAI semantic conventions** (`gen_ai.*`) for LLM spans and
**OpenInference** conventions (`retrieval.documents.*`) for retriever spans.

## Chain Span (root)

| Attribute               | Source field                   | Convention                     |
| ----------------------- | ------------------------------ | ------------------------------ |
| `question_id`           | `record.question_id`           | custom                         |
| `category`              | `record.category`              | custom                         |
| `run_id`                | `record.run_id`                | custom                         |
| `k`                     | `record.k`                     | custom                         |
| `gen_ai.request.model`  | `record.gen_ai.request.model`  | OTel GenAI                     |
| `gen_ai.system`         | `record.gen_ai.system`         | OTel GenAI                     |
| `gen_ai.operation.name` | `record.gen_ai.operation.name` | OTel GenAI                     |
| `cost_usd_total`        | derived (gen+judge)            | custom — only if both non-None |

## Retriever Span

| Attribute                                  | Source                           | Convention    |
| ------------------------------------------ | -------------------------------- | ------------- |
| `retrieval.documents.{i}.document.id`      | `record.retrieval_ranked_ids[i]` | OpenInference |
| `retrieval.documents.{i}.document.rank`    | `i`                              | OpenInference |
| `retrieval.documents.{i}.document.content` | `doc_lookup[doc_id]` (opt-in)    | OpenInference |

`.content` is **live** (Phase 16) but opt-in: the pure mapper (`attributes.py`) emits only
`.id` and `.rank`; the exporter (`exporter.py`) post-processes `span_attrs["retriever"]` after
`build_span_attrs` returns when `doc_lookup` is non-None (i.e., `--enrich-from-index` was
passed). A missing `doc_id` is omitted and logged as a warning — never an empty string, never a
crash (FR-5). `.document.score` is still out: scores are not persisted in `EvalRecord`
(field is `list[str]`, no scores); deriving them requires a retrieval re-run (FR-7).

**ID identity assumption:** `EvalRecord.retrieval_ranked_ids` holds doc-level IDs identical to
`Document.id` in `corpus.jsonl`. If chunking ever makes these IDs diverge, every lookup misses
and warns per record.

## Generation and Judge Spans (identical shape)

| Attribute                    | Source field        | Convention            |
| ---------------------------- | ------------------- | --------------------- | ------------------------- |
| `gen_ai.request.model`       | `record.{generation | judge}.model`         | OTel GenAI                |
| `gen_ai.system`              | `record.{generation | judge}.system`        | OTel GenAI                |
| `gen_ai.operation.name`      | `"chat"` (literal)  | OTel GenAI            |
| `gen_ai.usage.input_tokens`  | `record.{generation | judge}.input_tokens`  | OTel GenAI                |
| `gen_ai.usage.output_tokens` | `record.{generation | judge}.output_tokens` | OTel GenAI                |
| `latency_s`                  | `record.{generation | judge}.latency_s`     | custom                    |
| `cost_usd`                   | `record.{generation | judge}.cost_usd`      | custom — only if non-None |

## Cost Rule

`cost_usd` is **never written as `0.0`** when the price was unknown. If
`CallStats.cost_usd is None`, the attribute is omitted entirely from the span dict.
`cost_usd_total` on the chain span follows the same rule: omitted unless both
generation and judge costs are non-None.

## Offline Score Annotations (not span attributes)

Eval scores are not span attributes — they are written as Phoenix span **annotations**
via `client.spans.log_span_annotations_dataframe`. Each annotation row has:
`span_id` (16-char hex), `score` (float), `label` (string).

Score-to-span routing:

- `did_abstain_e2e` → chain span
- `did_abstain_retrieval` → retriever span
- `faithfulness_ratio` → generation span
- `fact_recall`, `fact_precision` → judge span

## Sources

- `src/enterprise_rag_ops/observability/attributes.py` — full attribute builders
- Research (pillar 3): OTel GenAI semconv table, OpenInference retrieval conventions
- `docs/adr/0004-observability-tool.md` — attribute field alignment rationale
