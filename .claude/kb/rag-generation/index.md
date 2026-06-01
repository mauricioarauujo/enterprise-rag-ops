# RAG Generation Knowledge Base

> **Purpose**: The `Generator` Protocol seam, per-provider structured-output mechanisms, token accounting, and the add-a-generator recipe for the three-provider matrix (OpenAI / Anthropic / Google).
> **MCP Validated**: 2026-06-01

## Quick Navigation

### Concepts

| File                                                                                     | Purpose                                                                          |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [concepts/generator-seam.md](concepts/generator-seam.md)                                 | Generator Protocol, AnswerWithSources contract, abstention, dispatch             |
| [concepts/structured-output-per-provider.md](concepts/structured-output-per-provider.md) | Three divergent structured-output mechanisms and the invariant that unifies them |
| [concepts/per-provider-token-accounting.md](concepts/per-provider-token-accounting.md)   | CallStats field mapping per SDK; Gemini thinking-token billing                   |

### Patterns

| File                                                       | Purpose                                                   |
| ---------------------------------------------------------- | --------------------------------------------------------- |
| [patterns/add-a-generator.md](patterns/add-a-generator.md) | Recipe to add a fourth provider behind the Generator seam |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — per-provider lookup: structured-output mechanism, token fields, key-scrub header, retry knob

---

## Key Concepts

| Concept                  | Description                                                                                           |
| ------------------------ | ----------------------------------------------------------------------------------------------------- |
| **Generator Protocol**   | Single-method seam; `generate` + `generate_with_stats` on every impl                                  |
| **AnswerWithSources**    | Closed Pydantic schema (`extra="forbid"`); shared contract across all three providers                 |
| **ABSTAIN_ANSWER**       | Sentinel string in `schema.py`; enforced at retrieval gate AND prompt level                           |
| **`_GENERATOR_FACTORY`** | `dict[system -> class]` dispatch in `eval/runner.py`; one line per provider                           |
| **Open-schema mirror**   | `_GeminiResponseSchema` — Gemini rejects `additionalProperties`; closed enforcement moved client-side |

---

## Cross-Domain Links

| Topic                                    | Owner                                                  |
| ---------------------------------------- | ------------------------------------------------------ |
| `generate_with_stats` stats-capture seam | `rag-eval` → `concepts/stats-capture-seam.md`          |
| Cassette/replay testing (ADR-0006)       | `rag-eval` → `patterns/cassette-replay-eval.md`        |
| Multi-model runner wiring                | `rag-eval` → `patterns/multi-model-runner.md`          |
| Cost accounting (price table)            | `rag-eval` → `concepts/cost-accounting.md`             |
| `gen_ai.system` span mapping             | `observability` → `concepts/span-attribute-mapping.md` |

---

## Agent Usage

| Agent        | Primary Files                                                        | Use Case           |
| ------------ | -------------------------------------------------------------------- | ------------------ |
| kb-architect | `generation/interfaces.py`, `generation/schema.py`, `eval/runner.py` | Domain maintenance |
