# Concept: OTel-GenAI Span Tree Shape

**Confidence**: HIGH — grounded in `exporter.py` (codebase) + OTel GenAI semconv (research).

## What It Is

Every `EvalRecord` produces exactly **one trace** composed of **four nested spans**:

```
{question_id}   [chain]         ← root; named by question_id
 ├── retriever  [retriever]     ← doc-ID list + rank metadata
 ├── generation [llm]           ← generation stats + cost
 └── judge      [llm]           ← judge stats + cost
```

The root span name is the `question_id` string. The three child spans have the literal
names `"retriever"`, `"generation"`, `"judge"`. All child spans are at the same depth
(siblings under the root); there is no generation→judge nesting.

## Span Kind Strings

Span kinds are passed as `openinference_span_kind=` to `tracer.start_as_current_span`.
The string values follow the **OpenInference** specification:

| Span       | `openinference_span_kind` | Notes                     |
| ---------- | ------------------------- | ------------------------- |
| root       | `"chain"`                 | end-to-end pipeline       |
| retriever  | `"retriever"`             | vector/BM25 lookup result |
| generation | `"llm"`                   | answer generation call    |
| judge      | `"llm"`                   | LLM-as-judge call         |

Both LLM spans use `"llm"` (not `"gen_ai"` or `"chat"`). The OTel span kind on
the parent `tracer.start_as_current_span` is the default (INTERNAL), not CLIENT or
SERVER — Phoenix reads the OpenInference attribute, not the OTel kind enum.

## Span IDs

Span IDs are captured **in-process** as 16-char hex strings immediately after the
context manager yields:

```python
span_ids["chain"] = f"{chain_span.get_span_context().span_id:016x}"
```

These IDs are then used to route offline eval scores to the correct span via the
Phoenix annotations API. IDs are ephemeral — they exist only within the replay run;
re-running reset-and-replay generates new IDs.

## Relationship to EvalRecord

The span tree is a **projection** of one `EvalRecord`:

- One record → one trace (one chain span + three children).
- Each span carries attributes built by `build_span_attrs(record)` in `attributes.py`.
- Score annotations are built by `build_score_rows(record, span_ids)` in `attributes.py`.

## Info Tab Rendering (Phoenix)

Phoenix's **Info tab** displays span content when `input.value` / `output.value` are
present. The harness hydrates all four I/O slots across the tree:

| Span       | `input.value`                                  | `output.value`                                                         |
| ---------- | ---------------------------------------------- | ---------------------------------------------------------------------- |
| chain      | gold question text (opt-in, exporter boundary) | —                                                                      |
| retriever  | —                                              | —                                                                      |
| generation | —                                              | `record.answer` (always-on, mapper)                                    |
| judge      | —                                              | verdict lines per-fact+per-citation (always-on when non-empty, mapper) |

This makes a failed trace self-explanatory end-to-end: question (chain) → retrieved doc
IDs → generated answer (generation) → judge verdicts (judge).

## Invariants

- Span children are opened and closed in order: retriever → generation → judge. Each
  child's context manager is exited before the next sibling opens (no overlap).
- `cost_usd_total` is only set on the chain span when both `generation.cost_usd` and
  `judge.cost_usd` are non-None. If either is None, the field is omitted entirely.
- The pure mapper (`attributes.py`) writes `retrieval.documents.{i}.document.id` and `.rank`
  only. `.content` is live (Phase 16) via the opt-in `--enrich-from-index` path: when
  `doc_lookup` is non-None, `exporter.py` post-processes `span_attrs["retriever"]` after
  `build_span_attrs` returns to hydrate `.content` from `corpus.jsonl`. A missing `doc_id` is
  omitted + warned, never a crash. `.score` is still out — not persisted in `EvalRecord`.
- `output.value`/`output.mime_type` on the judge span are omitted when both `per_fact`
  and `per_citation` are None or empty — the same guard pattern as `cost_usd`.

## Sources

- `src/enterprise_rag_ops/observability/exporter.py` — span loop
- `src/enterprise_rag_ops/observability/attributes.py` — attribute builders
- Research (pillar 3): OpenInference span kind taxonomy, OTel GenAI semconv
