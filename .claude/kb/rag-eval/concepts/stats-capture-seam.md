# Stats-Capture Seam: `generate_with_stats` / `judge_with_stats`

> **Purpose**: How token usage, latency, and model metadata are captured on the
> implementations without touching the `Generator`/`Judge` Protocols or `rag-ask`.
> **Confidence**: HIGH (codebase — `generation/openai_generator.py`,
> `generation/anthropic_generator.py`, `eval/openai_judge.py`)

## The Design

The `Generator` and `Judge` Protocols (ADR-0005 seam) expose `generate()` and
`judge()` — clean, stats-free interfaces. Phase 6 needed per-call metrics without
polluting those seams or breaking the `rag-ask` CLI.

The solution: add `generate_with_stats()` and `judge_with_stats()` methods to the
**concrete implementations only**. The Protocols stay unchanged; `rag-ask` calls
`generate()` and never sees a `CallStats`.

```
Generator Protocol    →  generate(chunks, question) → AnswerWithSources
OpenAIGenerator       →  generate_with_stats(...)  → (AnswerWithSources, CallStats)
AnthropicGenerator    →  generate_with_stats(...)  → (AnswerWithSources, CallStats)

Judge Protocol        →  judge(...) → JudgeVerdict
OpenAIJudge           →  judge_with_stats(...) → (JudgeVerdict, CallStats)
```

`generate()` and `judge()` are thin wrappers that call `*_with_stats` and discard
the stats — no code duplication, no seam pollution.

## What `CallStats` Captures

```python
class CallStats(BaseModel):
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str         # the model string sent to the API
    system: str        # "openai" | "anthropic" | "google"
    cost_usd: float | None = None   # filled in by runner after the call
```

`cost_usd` is intentionally `None` at capture time — the runner looks up the price
table and calls `compute_cost_usd(stats, price)` after the fact. This keeps
`CallStats` free of config dependency.

## Token Extraction per Provider

**OpenAI** (`usage.prompt_tokens` / `usage.completion_tokens`):

```python
usage = getattr(response, "usage", None)
input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
```

**Anthropic** (`usage.input_tokens` / `usage.output_tokens`):

```python
usage = getattr(response, "usage", None)
input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
```

Both use `getattr(…, 0)` defensively — `usage` is `None` in stub/fake responses.

## Latency Capture

`time.perf_counter()` wraps the API call:

```python
start_time = time.perf_counter()
response = self._client.messages.create(...)
latency = time.perf_counter() - start_time
```

This measures wall-clock time including network — the relevant quantity for a sweep
where per-call latency directly affects total run time.

## Extending to a New Provider

To add a `GeminiGenerator`:

1. Implement `generate_with_stats` returning `(AnswerWithSources, CallStats)`.
2. Extract tokens from the provider-specific usage object.
3. Set `system` to the provider name (e.g. `"google"`).
4. Add an entry in `_GENERATOR_FACTORY` in `runner.py`.
5. Add a price entry in `configs/baseline.yaml`.
   The `Generator` Protocol and `rag-ask` CLI are untouched.

## Related

- `generation/openai_generator.py`, `generation/anthropic_generator.py`
- `eval/openai_judge.py`
- `eval/records.py` — `CallStats`
- [eval-record-schema.md](eval-record-schema.md)
- [cost-accounting.md](cost-accounting.md)
