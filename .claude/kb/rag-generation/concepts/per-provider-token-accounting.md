# per-provider-token-accounting

> **Purpose**: How each provider SDK surfaces token usage, and how those fields map to `CallStats.input_tokens` / `CallStats.output_tokens` — with special handling for Gemini 2.5 thinking tokens.
> **Confidence**: HIGH (codebase-grounded; Gemini accounting verified by unit tests)
> **MCP Validated**: 2026-06-01

## Overview

Every `generate_with_stats` call produces a `CallStats` with `input_tokens` and `output_tokens`. The SDK field names differ per provider, and Gemini 2.5 introduces a third category (thinking tokens) that must be added to output for cost correctness. All reads are defensive (`getattr(..., 0)`) so a missing `usage` object never crashes a sweep.

## Field Mapping

### OpenAI

```python
usage = getattr(response, "usage", None)
input_tokens  = getattr(usage, "prompt_tokens", 0)     if usage else 0
output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
```

### Anthropic

```python
usage = getattr(response, "usage", None)
input_tokens  = getattr(usage, "input_tokens", 0)  if usage else 0
output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
```

### Google Gemini

```python
usage      = getattr(response, "usage_metadata", None)
input_tokens = getattr(usage, "prompt_token_count", 0) or 0  if usage else 0
candidates   = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
thoughts     = getattr(usage, "thoughts_token_count", 0) or 0  if usage else 0
output_tokens = candidates + thoughts
```

**Why `candidates + thoughts`:** Gemini 2.5 Flash / Flash-Lite with thinking enabled bills thinking tokens as output tokens but excludes them from `candidates_token_count`. If only `candidates_token_count` is used, the reported output count is lower than what Google actually charges. The `thoughts_token_count` field is absent (attribute missing) on non-thinking models, so `getattr(..., 0)` handles both cases safely.

The dual `or 0` guard (`getattr(..., 0) or 0`) handles the case where the field exists but is `None` rather than missing entirely — a pattern observed in some SDK versions for optional metadata.

## CallStats Schema

```python
# eval/records.py
class CallStats(BaseModel):
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str
    system: str           # "openai" | "anthropic" | "google"
    cost_usd: float | None = None
```

`cost_usd` is computed after the call by the runner via `compute_cost_usd(stats, price)` — not inside the generator. See `rag-eval` → `concepts/cost-accounting.md`.

## Common Mistakes

| Don't                                               | Do                                                                   |
| --------------------------------------------------- | -------------------------------------------------------------------- |
| Use only `candidates_token_count` for Gemini output | Add `thoughts_token_count` to get billed-output total                |
| Assume `usage` is always present                    | Use `getattr(response, "usage_metadata", None)` and check for `None` |
| Hard-crash on missing token fields                  | `getattr(usage, "field", 0) or 0` — always returns an int            |

## Related

- [concepts/generator-seam.md](generator-seam.md) — CallStats context in the seam
- `rag-eval` → `concepts/cost-accounting.md` — price-table lookup and `compute_cost_usd`
- `rag-eval` → `concepts/stats-capture-seam.md` — `generate_with_stats` rationale
