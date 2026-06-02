# RAG Eval Knowledge Base

> **Purpose**: LLM-as-judge evaluation of RAG answers — per-fact recall/precision scoring
> against gold `answer_facts`, doc-level (per-`doc_id`) citation faithfulness, the `None`
> empty-denominator/abstention convention, structured-output judge prompting, judge
> determinism, retrieval metric aggregation, abstention scoring, cassette/replay testing,
> multi-model sweep runner, cost accounting, HTML+MD report rendering, the
> stats-capture seam (`generate_with_stats` / `judge_with_stats`), failure-mode triage
> clustering (`rag-triage`), and triage-to-issues (`rag-issues`).
> **Phase 4 + Phase 5 + Phase 6 shipped** (Sprint 2, 2026-05-23–26).
> **Phase 14 + Phase 15 shipped** (Sprint 5, 2026-06-02).
> ADRs: `docs/adr/0001-eval-framework.md`, `docs/adr/0007-eval-record-schema.md`,
> `docs/adr/0009-triage-to-issues.md`.
> **Last updated**: 2026-06-02

## Quick Navigation

### Concepts

| File                                                                                 | Purpose                                                                   |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| [concepts/per-doc-faithfulness.md](concepts/per-doc-faithfulness.md)                 | Why per-`doc_id` block isolation catches spurious citations               |
| [concepts/none-empty-denominator.md](concepts/none-empty-denominator.md)             | `None` as N/A for empty-denominator eval ratios                           |
| [concepts/schema-as-ssot.md](concepts/schema-as-ssot.md)                             | Private LLM-facing subset keeps floats out of strict schema               |
| [concepts/judge-determinism.md](concepts/judge-determinism.md)                       | `strict: true` + closed Literal vocabulary vs. multi-sample               |
| [concepts/retrieval-metric-aggregation.md](concepts/retrieval-metric-aggregation.md) | Per-category aggregation, None-skipping, dedup-before-metrics order       |
| [concepts/abstention-scoring.md](concepts/abstention-scoring.md)                     | Empty-gold predicate, two-layer abstention, gate-rarely-fires insight     |
| [concepts/eval-record-schema.md](concepts/eval-record-schema.md)                     | `EvalRecord` shape, OTEL alignment, `k` field, what is excluded (Phase 6) |
| [concepts/cost-accounting.md](concepts/cost-accounting.md)                           | Price table in config, None on missing price, ceiling guard (Phase 6)     |
| [concepts/stats-capture-seam.md](concepts/stats-capture-seam.md)                     | `generate_with_stats`/`judge_with_stats` — seam on implementations only   |
| [concepts/failure-triage.md](concepts/failure-triage.md)                             | Groupby-aggregate over classified JSONL → ranked `TriageReport` clusters  |

### Patterns

| File                                                                   | Purpose                                                                         |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| [patterns/per-fact-judge-call.md](patterns/per-fact-judge-call.md)     | Single structured-output judge call: schema, call, re-validate, aggregate       |
| [patterns/offline-ci-judge.md](patterns/offline-ci-judge.md)           | StubJudge + fake client for network-free CI                                     |
| [patterns/cassette-replay-eval.md](patterns/cassette-replay-eval.md)   | vcrpy cassette wiring, root fixture, response-header scrubbing (Phase 6 fix)    |
| [patterns/multi-model-runner.md](patterns/multi-model-runner.md)       | Multi-model sweep: single retriever, flush, cost ceiling, FR-10 gap (Phase 6)   |
| [patterns/eval-report-render.md](patterns/eval-report-render.md)       | HTML+MD render via `string.Template`, None→N/A, dynamic `k` (Phase 6)           |
| [patterns/concurrent-eval-sweep.md](patterns/concurrent-eval-sweep.md) | BGE-M3 encoder lock, Anthropic max_retries/timeout, sweep checklist (Phase 6)   |
| [patterns/triage-to-issues.md](patterns/triage-to-issues.md)           | Cluster → grounded GitHub Issue draft; body-marker idempotency, dry-run default |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — formulas, schema fields, verdict vocab, retrieval aggregation, abstention, cassette snippet

---

## Architecture Decisions

- [docs/adr/0001-eval-framework.md](../../../docs/adr/0001-eval-framework.md) — accepted; custom thin judge, ADR-0005 seam
- [docs/adr/0006-cassette-replay.md](../../../docs/adr/0006-cassette-replay.md) — accepted; cassette/replay pattern for live-LLM eval tests
- [docs/adr/0007-eval-record-schema.md](../../../docs/adr/0007-eval-record-schema.md) — accepted; `EvalRecord` schema, cost model
- [docs/adr/0009-triage-to-issues.md](../../../docs/adr/0009-triage-to-issues.md) — accepted; gh-CLI seam, body-marker idempotency, dry-run default

---

## Key Invariants

- The LLM produces only the two verdict lists; aggregate floats are derived in Python.
- `None` means "not applicable" — never coerce to `0.0` for downstream averaging.
- Every cited `doc_id` gets its own named block in the prompt; a missing doc gets `(text unavailable)`.
- `openai` is imported only in `eval/openai_judge.py`; all other eval modules are offline-safe.
- `RAG_JUDGE_MODEL` overrides the default judge model; `OPENAI_API_KEY` is only needed for live runs.
- Unanswerable predicate: `len(expected_doc_ids) == 0`, not `category == "info_not_found"`.
- `ABSTAIN_ANSWER` sentinel is enforced at **both** the retrieval gate and the generator prompt.
- vcrpy `record_mode="none"` by default — tests fail, never silently hit the network.
- `vcr_record` fixture lives in root `tests/conftest.py`; it scrubs both request creds and account-identifying response headers via `before_record_response` (vcrpy 6 has no `filter_response_headers`).
- `cost_usd` is `None` when the model is absent from the price table — never silent `0.0`.
- BGE-M3 encoder is not thread-safe; the runner serializes encode under `retrieve_lock`.
- FR-10 guard checks index dir existence only, not gold-awareness — always run `make build-index-gold` before a sweep.
- `EvalRecord` excludes `per_fact`/`per_citation` lists; only the three Python-derived aggregate floats are persisted.
- `k` is persisted on every `EvalRecord` and read dynamically by the report — no hard-coded retrieval cut-off.
- `rag-triage` fails fast on any `failure_mode is None` — run `rag-classify` first; no partial-skip.
- `TriageReport.schema_version = "1.0"` is the cross-phase contract; `rag-issues` hard-rejects any other value.
- `rag-issues` is dry-run by default — no GitHub call without `--create`; `GhCliClient` is never instantiated in tests.
- Body-marker fingerprint idempotency is best-effort (GitHub search propagation delay); may create a duplicate, never crashes.
