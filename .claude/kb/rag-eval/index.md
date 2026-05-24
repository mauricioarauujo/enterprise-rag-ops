# RAG Eval Knowledge Base

> **Purpose**: LLM-as-judge evaluation of RAG answers — per-fact recall/precision scoring
> against gold `answer_facts`, doc-level (per-`doc_id`) citation faithfulness, the `None`
> empty-denominator/abstention convention, structured-output judge prompting, and judge
> determinism (strict schema + discrete verdict vocabulary).
> **Phase 4 shipped** (Sprint 2, 2026-05-23). ADR: `docs/adr/0001-eval-framework.md`.
> **MCP Validated**: 2026-05-24

## Quick Navigation

### Concepts

| File                                                                     | Purpose                                                     |
| ------------------------------------------------------------------------ | ----------------------------------------------------------- |
| [concepts/per-doc-faithfulness.md](concepts/per-doc-faithfulness.md)     | Why per-`doc_id` block isolation catches spurious citations |
| [concepts/none-empty-denominator.md](concepts/none-empty-denominator.md) | `None` as N/A for empty-denominator eval ratios             |
| [concepts/schema-as-ssot.md](concepts/schema-as-ssot.md)                 | Private LLM-facing subset keeps floats out of strict schema |
| [concepts/judge-determinism.md](concepts/judge-determinism.md)           | `strict: true` + closed Literal vocabulary vs. multi-sample |

### Patterns

| File                                                               | Purpose                                                                   |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| [patterns/per-fact-judge-call.md](patterns/per-fact-judge-call.md) | Single structured-output judge call: schema, call, re-validate, aggregate |
| [patterns/offline-ci-judge.md](patterns/offline-ci-judge.md)       | StubJudge + fake client for network-free CI                               |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — formulas, schema fields, verdict vocab

---

## Architecture Decision

- [docs/adr/0001-eval-framework.md](../../../docs/adr/0001-eval-framework.md) — accepted; custom thin judge, ADR-0005 seam

---

## Key Invariants

- The LLM produces only the two verdict lists; aggregate floats are derived in Python.
- `None` means "not applicable" — never coerce to `0.0` for downstream averaging.
- Every cited `doc_id` gets its own named block in the prompt; a missing doc gets `(text unavailable)`.
- `openai` is imported only in `eval/openai_judge.py`; all other eval modules are offline-safe.
- `RAG_JUDGE_MODEL` overrides the default judge model; `OPENAI_API_KEY` is only needed for live runs.
