# Concept: Span Attribute Mapping

**Confidence**: HIGH — grounded in `attributes.py` (codebase) + OTel/OpenInference semconv
(research pillar 3, verified via ADR-0004).

## What It Is

Each span role maps to a specific set of attributes drawn from `EvalRecord` fields.
Attributes follow **OTel GenAI semantic conventions** (`gen_ai.*`) for LLM spans and
**OpenInference** conventions (`retrieval.documents.*`) for retriever spans.

## Chain Span (root)

| Attribute               | Source field                   | Convention                       | When                        |
| ----------------------- | ------------------------------ | -------------------------------- | --------------------------- |
| `question_id`           | `record.question_id`           | custom                           | always                      |
| `category`              | `record.category`              | custom                           | always                      |
| `run_id`                | `record.run_id`                | custom                           | always                      |
| `k`                     | `record.k`                     | custom                           | always                      |
| `gen_ai.request.model`  | `record.gen_ai.request.model`  | OTel GenAI                       | always                      |
| `gen_ai.system`         | `record.gen_ai.system`         | OTel GenAI                       | always                      |
| `gen_ai.operation.name` | `record.gen_ai.operation.name` | OTel GenAI                       | always                      |
| `cost_usd_total`        | derived (gen+judge)            | custom                           | only if both non-None       |
| `input.value`           | `question_lookup[question_id]` | OpenInference — Phoenix Info tab | opt-in at exporter boundary |
| `input.mime_type`       | `"text/plain"` (literal)       | OpenInference                    | opt-in, paired with above   |

`input.value` / `input.mime_type` are set by `exporter.py` **after** `build_span_attrs` returns,
not inside the pure mapper (`attributes.py`). They are hydrated only when
`question_lookup` is non-None, which requires the `--enrich-from-questions` CLI flag.
A missing `question_id` is logged as a warning and both keys are omitted for that
record — never a crash. The boundary-enrichment discipline matches Phase 16
(`--enrich-from-index`): the pure mapper stays import-light (NFR-1).

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

## Generation Span

| Attribute                    | Source field                      | Convention                       | When             |
| ---------------------------- | --------------------------------- | -------------------------------- | ---------------- |
| `gen_ai.request.model`       | `record.generation.model`         | OTel GenAI                       | always           |
| `gen_ai.system`              | `record.generation.system`        | OTel GenAI                       | always           |
| `gen_ai.operation.name`      | `"chat"` (literal)                | OTel GenAI                       | always           |
| `gen_ai.usage.input_tokens`  | `record.generation.input_tokens`  | OTel GenAI                       | always           |
| `gen_ai.usage.output_tokens` | `record.generation.output_tokens` | OTel GenAI                       | always           |
| `latency_s`                  | `record.generation.latency_s`     | custom                           | always           |
| `output.value`               | `record.answer`                   | OpenInference — Phoenix Info tab | always           |
| `output.mime_type`           | `"text/plain"` (literal)          | OpenInference                    | always           |
| `cost_usd`                   | `record.generation.cost_usd`      | custom                           | only if non-None |

`output.value` is **always-on** (Phase 17): `record.answer` is an in-record field — no
external read needed — so the pure mapper sets it directly. This makes Phoenix's Info tab
render the generated answer for every trace.

## Judge Span

| Attribute                    | Source field                 | Convention                       | When                  |
| ---------------------------- | ---------------------------- | -------------------------------- | --------------------- |
| `gen_ai.request.model`       | `record.judge.model`         | OTel GenAI                       | always                |
| `gen_ai.system`              | `record.judge.system`        | OTel GenAI                       | always                |
| `gen_ai.operation.name`      | `"chat"` (literal)           | OTel GenAI                       | always                |
| `gen_ai.usage.input_tokens`  | `record.judge.input_tokens`  | OTel GenAI                       | always                |
| `gen_ai.usage.output_tokens` | `record.judge.output_tokens` | OTel GenAI                       | always                |
| `latency_s`                  | `record.judge.latency_s`     | custom                           | always                |
| `output.value`               | verdict lines (see below)    | OpenInference — Phoenix Info tab | if verdicts non-empty |
| `output.mime_type`           | `"text/plain"` (literal)     | OpenInference                    | if verdicts non-empty |
| `cost_usd`                   | `record.judge.cost_usd`      | custom                           | only if non-None      |

`output.value` on the judge span is a `text/plain` block rendered from
`record.per_fact` and `record.per_citation` (Phase 19):

```
fact: <fact text> -> <verdict>
fact: <fact text> -> <verdict>
citation: <doc_id> -> <verdict>
```

Built with `str.join` from `record.per_fact` (if non-None/non-empty) then
`record.per_citation` (if non-None/non-empty). When **both** lists are None or empty,
both `output.value` and `output.mime_type` are omitted (mirrors the `cost_usd` omit
guard). Always-on when verdicts exist — no new flag, no new import — mapper purity
(NFR-1) preserved.

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

## Known Display Artifacts in Phoenix

- **Native cost widget shows $0**: Phoenix reads `llm.token_count.*` for its cost widget,
  but the harness emits `gen_ai.usage.*` (OTel GenAI) + a custom `cost_usd` attribute.
  The real cost is present on the span's Attributes tab; the widget simply doesn't read it.
- **Trace latency is replay duration**: Phoenix displays the span start/end delta, which
  reflects when `exporter.py` opened/closed the context manager — not the real
  `latency_s` attribute stored in the record. Both values are correct for their purpose;
  they measure different things.

These are known/acceptable display artifacts, not bugs.

## Sources

- `src/enterprise_rag_ops/observability/attributes.py` — full attribute builders (Phases 16, 17, 19)
- `src/enterprise_rag_ops/observability/exporter.py` — exporter boundary enrichment
- `src/enterprise_rag_ops/observability/cli.py` — `--enrich-from-questions` CLI flag
- OpenInference spec (`/arize-ai/openinference`): `input.value`, `output.value`, `input.mime_type`, `output.mime_type` confirmed as standard OpenInference keys (Pillar 2)
- `docs/adr/0004-observability-tool.md` — attribute field alignment rationale
