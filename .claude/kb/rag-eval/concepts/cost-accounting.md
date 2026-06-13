# Cost Accounting in Multi-Model Sweeps

> **Purpose**: How token-cost is captured per call, accumulated across a sweep, and
> guarded by a ceiling — the "None on missing price, never silent 0" rule, plus
> two-call **combined** cost and the runner **cost-guard invariant** (ADR-0012).
> **Confidence**: HIGH (codebase — `eval/records.py`, `eval/runner.py`, `generation/router_generator.py`, ADR-0007, ADR-0012)
> **ADR**: `docs/adr/0007-eval-record-schema.md`, `docs/adr/0012-router-generator-composite.md`

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

## Two-Call Combined Cost (Router, ADR-0012)

A cost-router (an LLM cascade) makes a cheap call **always** and a strong call **iff**
it escalates. The `RouterGenerator` is the _single owner_ of the combined cost — it is
the only site holding both sub-`CallStats` objects and the price table — so it
manufactures one output `CallStats` rather than letting the runner sum two rows:

```python
# generation/router_generator.py — combined cost (cheap always, strong iff escalated)
cost_usd = (cheap_cost or 0.0) + ((strong_cost or 0.0) if escalate else 0.0)
```

- Tokens and `latency_s` are summed the same way (cheap always + strong-iff-escalated).
- `model = "router"`, `system = "router"` (synthetic identity; both are `str`, not the
  `ModelConfig` `Literal`, so no schema change).
- `confidence_score` on the output is the **cheap** call's signal.
- `None` summands map to `0.0`, mirroring the runner's `(x or 0.0)` convention.

This enforces the #1 research-fairness rule: the cheap call is **always** charged on an
escalated query — never dropped, never double-counted. See the rag-generation pattern
[../../rag-generation/patterns/router-cascade-composite.md](../../rag-generation/patterns/router-cascade-composite.md).

## The Runner Cost-Guard Invariant (the load-bearing bit)

The runner's cost line changed from an **unconditional** recompute to a **guarded** one:

```python
# eval/runner.py — before: cost_usd = compute_cost_usd(...)   (always)
if gen_stats.cost_usd is None:                                 # after: guarded
    gen_stats.cost_usd = compute_cost_usd(gen_stats, config.prices.get(gen_stats.model))
```

**Invariant:** _a generator that pre-sets `cost_usd` owns its cost — the runner treats
it as final and does not recompute._ This is what lets the router's manufactured
combined cost survive: a `"router"` model has **no price-table entry**, so an
unconditional recompute would `compute_cost_usd → None` and **null** the true combined
figure.

The guard is **backwards-compatible**: all three concrete generators build `CallStats`
without `cost_usd` (defaults to `None`), so the body runs exactly as before for every
single-model config. The retrieval-abstain stub already pre-set `cost_usd=0.0` and now
correctly keeps it (0 tokens × any price = 0.0, unchanged). The judge cost is _always_
recomputed — only the generator line is guarded.

## Related

- `eval/records.py` — `Price`, `CallStats`, `compute_cost_usd`
- `eval/config.py` — `RunConfig.prices`, `cost_ceiling_usd`, `RouterConfig`
- `eval/runner.py` — cost accumulation + ceiling guard + the cost-guard invariant
- `generation/router_generator.py` — combined-cost single owner (ADR-0012)
- [stats-capture-seam.md](stats-capture-seam.md) — the `*_with_stats` 3-tuple the router composes
- [eval-record-schema.md](eval-record-schema.md)
- [../patterns/multi-model-runner.md](../patterns/multi-model-runner.md)
- [../../rag-generation/patterns/router-cascade-composite.md](../../rag-generation/patterns/router-cascade-composite.md)
- [cost-per-correct-answer.md](cost-per-correct-answer.md) — the head-to-head metric that uses this cost
