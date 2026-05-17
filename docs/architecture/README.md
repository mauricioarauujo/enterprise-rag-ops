# Architecture

System design for Enterprise RAG Ops.

## Thesis

The project is a RAG **evaluation and observability** harness. The retrieval-augmented
generation pipeline is deliberately conventional; the engineering signal is in the layers
around it — per-fact judging, retrieval metrics with abstention, multi-model comparison,
tracing, and a failure-mode taxonomy.

## Components

_Filled in as Sprint 1 (substrate) and Sprint 2 (eval harness) land._

- **Substrate** — document indexing, hybrid retrieval (BM25 + dense), generation with
  source attribution.
- **Eval harness** — per-fact LLM-as-judge, retrieval recall/abstention metrics,
  multi-model runner.
- **Observability** — OpenTelemetry tracing, failure taxonomy, dashboard.

## Decisions

Significant choices are recorded as ADRs in [`../adr/`](../adr/).
