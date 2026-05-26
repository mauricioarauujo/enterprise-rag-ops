# Cost Accounting in Multi-Model Sweeps

> **Purpose**: How token-cost is captured per call, accumulated across a sweep, and
> guarded by a ceiling — including the "None on missing price, never silent 0" rule.
> **Confidence**: HIGH (codebase — `eval/records.py`, `eval/runner.py`, ADR-0007)
> **ADR**: `docs/adr/0007-eval-record-schema.md`

## Price Table in Config

Prices live in `RunConfig.prices` (YAML → Pydantic), keyed by `model_id`:

```yaml
prices:
  gpt-5-nano-2025-08-07:
    input_usd_per_1m: 0.05
    output_usd_per_1m: 0.40
  claude-haiku-4-5-20251001:
    input_usd_per_1m: 1.00
    output_usd_per_1m: 5.00
```

`Price` is a Pydantic model with `input_usd_per_1m` and `output_usd_per_1m`.
The table is in config, not code — adding a new model requires only a YAML edit.

## `compute_cost_usd` — None on Missing Price

```python
# eval/records.py
def compute_cost_usd(stats: CallStats, price: Price | None) -> float | None:
    if price is None:
        logger.warning("No price entry for model %s under system %s.", ...)
        return None   # never silent 0
    cost = (stats.input_tokens / 1e6) * price.input_usd_per_1m
          + (stats.output_tokens / 1e6) * price.output_usd_per_1m
    return cost
```

If a model is absent from the price table, `cost_usd` is `None` on both the
`generation` and `judge` `CallStats`. The report propagates `None` as "N/A" (the same
`None`-convention as eval metrics — see `concepts/none-empty-denominator.md`). It
**never** silently treats a missing price as $0.

## Cost Accumulation and the Ceiling Guard

The runner accumulates cost under a `cost_lock` to stay correct under concurrency:

```python
with cost_lock:
    cost_before = total_cost_usd
    total_cost_usd += call_cost        # call_cost = gen + judge (0.0 if None)
    crossed_now = (
        config.cost_ceiling_usd is not None
        and cost_before <= config.cost_ceiling_usd
        and total_cost_usd > config.cost_ceiling_usd
    )
    if crossed_now:
        halt_run = True
    should_write = not halt_run or crossed_now  # boundary record is never lost
```

`halt_run` is read and written only inside `cost_lock` — never bare — to avoid a
data race under `ThreadPoolExecutor`. The record that crosses the ceiling is still
written so no data is silently discarded.

## Abstention Cost

When the retriever returns empty results (`did_abstain_retrieval=True`), the runner
short-circuits to a synthetic `CallStats` with all zeros and skips the generator call.
The judge still runs (to score the abstention answer). Cost for abstentions is
effectively judge-only.

## Report Propagation

In `report.py`, a model's total cost is `None` (rendered as "N/A") if any record for
that model has a `None` cost field — partial missing-price entries are treated as
"total unknown", not as partial sums. This prevents misleadingly low totals when only
some calls had prices.

## Related

- `eval/records.py` — `Price`, `CallStats`, `compute_cost_usd`
- `eval/config.py` — `RunConfig.prices`, `cost_ceiling_usd`
- `eval/runner.py` — cost accumulation + ceiling guard
- [eval-record-schema.md](eval-record-schema.md)
- [../patterns/multi-model-runner.md](../patterns/multi-model-runner.md)
