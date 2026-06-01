# Observability Knowledge Base

> **Purpose**: Observability for the custom RAG eval harness — OTel-GenAI / OpenInference
> span trees (chain → retriever → generation → judge), the deterministic eval-JSONL → Arize
> Phoenix replay exporter (reset-and-replay idempotency), span-attribute mapping, cost/token
> economics on spans, offline score write-back, and the rule-based failure-mode taxonomy
> (5-label first-match cascade over EvalRecord aggregates + gold). ADRs: 0004, 0007, 0008.
> **Sprint 3 / Phases 7–8 shipped** (2026-05-28–30).
> **MCP Validated**: 2026-06-01

## Quick Navigation

### Concepts

| File                                                                                 | Purpose                                                          |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| [concepts/span-tree-shape.md](concepts/span-tree-shape.md)                           | The 4-span OTel tree: chain → retriever → generation → judge     |
| [concepts/span-attribute-mapping.md](concepts/span-attribute-mapping.md)             | OpenInference / OTel-GenAI attribute conventions per span role   |
| [concepts/reset-and-replay-idempotency.md](concepts/reset-and-replay-idempotency.md) | Why project-delete + full-replay is idempotent; known limitation |
| [concepts/failure-taxonomy.md](concepts/failure-taxonomy.md)                         | 5-label first-match cascade: predicates, thresholds, ordering    |
| [concepts/aggregate-granularity-limit.md](concepts/aggregate-granularity-limit.md)   | Why the classifier cannot pinpoint which fact/citation failed    |

### Patterns

| File                                                                               | Purpose                                                                    |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| [patterns/eval-jsonl-replay.md](patterns/eval-jsonl-replay.md)                     | Replay eval-JSONL → Phoenix: ScoreSink, reset, span loop, score write-back |
| [patterns/manual-span-instrumentation.md](patterns/manual-span-instrumentation.md) | Manual Python 3.11 OTel span tree via `phoenix.otel.register`              |
| [patterns/failure-classifier-cascade.md](patterns/failure-classifier-cascade.md)   | Rule-based `classify()` cascade wired to `rag-classify` CLI                |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — attribute names, score metrics, cascade order, CLI flags

---

## Architecture Decisions

- [docs/adr/0004-observability-tool.md](../../../docs/adr/0004-observability-tool.md) — accepted; Phoenix deployed (runner-up) over Langfuse for hardware reasons
- [docs/adr/0007-eval-record-schema.md](../../../docs/adr/0007-eval-record-schema.md) — accepted; EvalRecord schema and cost model
- [docs/adr/0008-failure-taxonomy.md](../../../docs/adr/0008-failure-taxonomy.md) — accepted; 5-label taxonomy + thresholds

---

## Key Invariants

- Deployed backend: **Arize Phoenix** (`arizephoenix/phoenix:version-15.0.0`); Langfuse rejected on 8 GB hardware grounds.
- Wire format: **OpenTelemetry GenAI semantic conventions + OpenInference span kinds** — tool-swap is a thin remap.
- Idempotency: `reset_project` (delete) then full replay; no upsert-by-seed.
- `cost_usd_total` on the chain span is written only when BOTH `generation.cost_usd` and `judge.cost_usd` are non-None.
- Span kind strings: `"chain"`, `"retriever"`, `"llm"` (generation and judge both use `"llm"`).
- Failure taxonomy classifies on aggregate metrics only; per-fact detail is excluded from `EvalRecord`.
- `failure_mode: str | None = None` — backward-compatible; older records parse cleanly.
