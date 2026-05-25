# Enterprise RAG Ops

Production-grade RAG evaluation and observability over the [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/enterprise-rag-bench) dataset.

**Status:** Phase 0 — Bootstrap. Not yet functional.

## What this project is

A harness for building, **evaluating**, and **observing** a retrieval-augmented generation system the way it would be done at a company that ships RAG to enterprise customers — per-fact LLM-as-judge scoring, retrieval metrics with abstention, multi-model comparison, OpenTelemetry tracing, and a failure-mode taxonomy surfaced in a dashboard.

The primary differentiator is not the RAG itself — it's the **evaluation harness** and **observability layer** around it.

## What this project is not

- Not a RAG framework to compete with LangChain / LlamaIndex
- Not a leaderboard chase — the goal is depth on eval + ops, not SOTA scores
- Not production code for a real customer

## Roadmap

Built in phases, each with a clear exit criterion.

| Phase             | Focus                                                       |
| ----------------- | ----------------------------------------------------------- |
| 0 — Bootstrap     | Repo, harness, tooling                                      |
| 1 — Substrate     | Baseline hybrid RAG                                         |
| 2 — Eval Harness  | Per-fact judge + multi-model report — **primary signal**    |
| 3 — Observability | Tracing + failure taxonomy + dashboard — **differentiator** |
| 4 — Polish & Ship | Documentation, write-up, release                            |

## Development

Requirements: Python 3.11+, [uv](https://github.com/astral-sh/uv).

```bash
# Setup
uv sync

# Quality pipeline
make format    # ruff format
make lint      # ruff check
make test      # pytest

# Or lint + test together
make lint test
```

## License

MIT. See `LICENSE`.
