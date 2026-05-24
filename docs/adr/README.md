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

Planned: ADR-0004 (observability tool, Sprint 3) and ADR-0005 (LLM provider/model
matrix, Sprint 2/3) — both shifted by one when ADR-0003 took the generation slot.
