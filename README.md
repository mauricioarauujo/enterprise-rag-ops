# Enterprise RAG Ops

Production-grade RAG evaluation and observability over the [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/enterprise-rag-bench) dataset.

## What this project is

A harness for building, **evaluating**, and **observing** a retrieval-augmented generation system the way it would be done at a company that ships RAG to enterprise customers — per-fact LLM-as-judge scoring, retrieval metrics with abstention, multi-model comparison, OpenTelemetry tracing, and a failure-mode taxonomy surfaced in a dashboard.

The primary differentiator is not the RAG itself — it's the **evaluation harness** and **observability layer** around it.

## What this project is not

- Not a RAG framework to compete with LangChain / LlamaIndex
- Not a leaderboard chase — the goal is depth on eval + ops, not SOTA scores
- Not production code for a real customer

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
