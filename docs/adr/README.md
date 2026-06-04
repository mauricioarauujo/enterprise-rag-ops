# Architecture Decision Records

Each ADR captures one significant decision: its context, the decision, and the consequences.

## Convention

- One file per decision, numbered: `0001-short-slug.md`.
- Sections: **Status** (proposed / accepted / deferred / superseded), **Date** (YYYY-MM-DD),
  **Context**, **Decision**, **Consequences**.

## Index

| ID   | Title                                                                                                         | Status   | Date       |
| ---- | ------------------------------------------------------------------------------------------------------------- | -------- | ---------- |
| 0001 | [Eval Framework — Custom Thin Per-Fact Judge](0001-eval-framework.md)                                         | accepted | 2026-05-23 |
| 0002 | [Retrieval Architecture — Hybrid BM25 + Dense over LanceDB](0002-retrieval-architecture.md)                   | accepted | 2026-05-18 |
| 0003 | [Generation Layer — OpenAI Structured Outputs with Source Attribution](0003-generation.md)                    | accepted | 2026-05-20 |
| 0004 | [Observability & Cost Tracking — Langfuse Self-Hosted, OTEL-Native Records](0004-observability-tool.md)       | proposed | 2026-05-25 |
| 0005 | [LLM Provider Matrix — OpenAI / Anthropic / Ollama](0005-llm-provider-matrix.md)                              | accepted | 2026-05-24 |
| 0006 | [Cassette Replay — VCR Replay for E2E Tests](0006-cassette-replay.md)                                         | accepted | 2026-05-24 |
| 0007 | [Evaluation Record Schema and Cost-Accounting Model](0007-eval-record-schema.md)                              | accepted | 2026-05-25 |
| 0008 | [Rule-Based Failure-Mode Taxonomy and Classifier](0008-failure-taxonomy.md)                                   | accepted | 2026-05-30 |
| 0009 | [Triage to GitHub Issues — gh-CLI Client, Body-Marker Idempotency, Dry-Run Default](0009-triage-to-issues.md) | accepted | 2026-06-02 |
| 0010 | [Persist Judge Reasoning in Gold and Design Bronze Archive](0010-persist-judge-reasoning-bronze-gold.md)      | accepted | 2026-06-02 |
| 0011 | [Inference-Time Escalation Signal for the Cost-Aware Router](0011-escalation-signal.md)                       | accepted | 2026-06-04 |

ADR-0004 is **proposed** (drafted in Sprint 2 / Phase 6 to constrain the eval-record schema;
acceptance deferred to Sprint 3 / Phase 7 when the tool is wired). ADR-0007 (eval-record schema + cost-accounting model) is accepted.
