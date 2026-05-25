# Architecture Decision Records

Each ADR captures one significant decision: its context, the decision, and the consequences.

## Convention

- One file per decision, numbered: `0001-short-slug.md`.
- Sections: **Status** (proposed / accepted / deferred / superseded), **Date** (YYYY-MM-DD),
  **Context**, **Decision**, **Consequences**.

## Index

| ID   | Title                                                                                       | Status   | Date       |
| ---- | ------------------------------------------------------------------------------------------- | -------- | ---------- |
| 0001 | [Eval Framework — Custom Thin Per-Fact Judge](0001-eval-framework.md)                       | accepted | 2026-05-23 |
| 0002 | [Retrieval Architecture — Hybrid BM25 + Dense over LanceDB](0002-retrieval-architecture.md) | accepted | 2026-05-18 |
| 0003 | [Generation Layer — OpenAI Structured Outputs with Source Attribution](0003-generation.md)  | accepted | 2026-05-20 |
| 0005 | [LLM Provider Matrix — OpenAI / Anthropic / Ollama](0005-llm-provider-matrix.md)            | accepted | 2026-05-24 |
| 0006 | [Cassette Replay — VCR Replay for E2E Tests](0006-cassette-replay.md)                       | accepted | 2026-05-24 |

Planned: ADR-0004 (observability tool, Sprint 3).
