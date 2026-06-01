# Pattern: Manual Python 3.11 OTel Span Tree

**Confidence**: HIGH — grounded in `phoenix_client.py`, `exporter.py` (codebase) +
OTel-GenAI/OpenInference semconv (research pillar 3).

## When to Use

Use when you need to instrument a new code path (e.g., an online RAG request, not just
a replay) with the same span-tree shape as the replay exporter. This pattern shows how
to stand up the tracer provider and emit a chain → retriever → llm tree manually.

## Setup: TracerProvider via `phoenix.otel.register`

All Phoenix-specific imports are contained in `phoenix_client.py`. The pattern for
registering a provider (inside `PhoenixScoreSink.__init__`):

```python
from phoenix.otel import register
from opentelemetry import trace

# Normalize the endpoint before passing (see split_endpoint in phoenix_client.py)
provider = register(
    project_name=project,
    endpoint=otlp_endpoint,         # must end in /v1/traces
    api_key=os.environ.get("PHOENIX_API_KEY"),   # None = no auth
    set_global_tracer_provider=True,
    verbose=False,
)
tracer = trace.get_tracer("replay-exporter", tracer_provider=provider)
```

`set_global_tracer_provider=True` means child spans can use `trace.get_tracer()` with
no explicit provider argument.

## Emitting a Span Tree (Context Manager Pattern)

```python
with tracer.start_as_current_span(
    question_id,
    openinference_span_kind="chain",
    attributes=chain_attrs,         # dict[str, Any]
) as chain_span:
    chain_span_id = f"{chain_span.get_span_context().span_id:016x}"

    with tracer.start_as_current_span(
        "retriever",
        openinference_span_kind="retriever",
        attributes=retriever_attrs,
    ) as ret_span:
        ret_span_id = f"{ret_span.get_span_context().span_id:016x}"

    with tracer.start_as_current_span(
        "generation",
        openinference_span_kind="llm",
        attributes=gen_attrs,
    ) as gen_span:
        gen_span_id = f"{gen_span.get_span_context().span_id:016x}"

    with tracer.start_as_current_span(
        "judge",
        openinference_span_kind="llm",
        attributes=judge_attrs,
    ) as judge_span:
        judge_span_id = f"{judge_span.get_span_context().span_id:016x}"
```

Each `with` block is exited before the next sibling opens — no concurrent spans.

## Flushing

After emitting spans, call `provider.force_flush()` before any score annotation API
calls. Phoenix's annotation API references span IDs that must already be committed.
The `flush()` method on `PhoenixScoreSink` wraps this with a warning on error.

## Key Attribute Conventions

See [concepts/span-attribute-mapping.md](../concepts/span-attribute-mapping.md) for the
full table. Minimum viable set for an LLM span:

```python
gen_attrs = {
    "gen_ai.request.model": "claude-haiku-4-5-20251001",
    "gen_ai.system": "anthropic",
    "gen_ai.operation.name": "chat",
    "gen_ai.usage.input_tokens": 420,
    "gen_ai.usage.output_tokens": 88,
    "latency_s": 1.34,
    # cost_usd: only include if non-None
}
```

## Tool-Swap Seam

All `from phoenix.*` and `from opentelemetry.*` imports are **strictly contained in
`phoenix_client.py`** (NFR-3). The rest of the observability layer (`exporter.py`,
`attributes.py`, `cli.py`) only imports from `phoenix_client` and the eval `records`
module. A future swap (Langfuse, pure OTel collector) is localized to one file.

## Sources

- `src/enterprise_rag_ops/observability/phoenix_client.py`
- `src/enterprise_rag_ops/observability/exporter.py`
- Research (pillar 3): Phoenix manual instrumentation, OTel context propagation
- See also: [concepts/span-tree-shape.md](../concepts/span-tree-shape.md)
