# Cost-Per-Correct-Answer Metric

> **Purpose**: The headline operational metric for router-vs-baseline head-to-head —
> of the dollars a system spends _generating_ answers, how many buy a _correct_ one?
> **Confidence**: HIGH (codebase — `eval/metrics.py::compute_cost_per_correct`,
> `tests/eval/test_metrics.py`, `docs/analysis/routing-verdict.md`, sprint-7/phase-3)
> **ADR**: `docs/adr/0012-router-generator-composite.md`

## Definition

```
cost_per_correct = sum(generation.cost_usd) / count(failure_mode == "correct")
```

Implemented in `src/enterprise_rag_ops/eval/metrics.py::compute_cost_per_correct`
(pure function, no I/O, cassette-free tested).

## Design Decisions

### Numerator: generation cost only

`EvalRecord.generation.cost_usd` is summed; `EvalRecord.judge.cost_usd` is **never
read**. Judge cost is eval overhead — identical across all systems, not a deployment
figure (BRAINSTORM Tension 3 in the phase-3 SDD). Including it would make the metric
measure "how expensive is our eval harness" instead of "how expensive is this
generator in production."

For the router row, `generation.cost_usd` is the **combined cost** (cheap always +
strong iff escalated) manufactured by `RouterGenerator` — see
[cost-accounting.md](cost-accounting.md) § Two-Call Combined Cost.

### Denominator: `failure_mode == "correct"` count

Records are pre-classified by the failure-mode triage step before this metric runs.
`CORRECT = "correct"` (the `FailureMode.CORRECT` label from the triage classifier).
All records for the system are summed in the numerator regardless of label; only
correct records count in the denominator — so a system that spends money to produce
wrong answers pays for them without credit.

### None on zero-correct denominator

If the system produced **zero correct answers**, `compute_cost_per_correct` returns
`None` — matching the harness `None`-on-empty-denominator convention (see
[none-empty-denominator.md](none-empty-denominator.md)). This is "metric not
applicable", not zero cost.

```python
# eval/metrics.py
if denominator == 0:
    return None
return numerator / denominator
```

### None summand → 0.0

A record with `generation.cost_usd = None` (price-table miss; see
[cost-accounting.md](cost-accounting.md)) contributes `0.0` to the numerator via
`(r.generation.cost_usd or 0.0)` — the runner's standard convention. This prevents a
single price-table miss from inflating the metric while being consistent with how the
runner accumulates the cost ceiling.

### Caller groups by system before calling

The helper operates on **one system's records** and has no concept of `system`. The
caller (`scripts/routing_evaluation.py`) groups by `gen_ai.system` before invoking
the function for each system. This keeps the helper pure and the grouping logic in
the analysis script where it belongs.

## Usage in the Router Analysis

`cost_per_correct` is the head-to-head metric for the sprint-7 routing evaluation
(`docs/analysis/routing-verdict.md`). The sprint-7 measured result:

| System                          | Cost / correct | Fact recall |
| :------------------------------ | :------------: | :---------: |
| `gemini-2.5-flash-lite` (cheap) |    $0.0007     |    22.9%    |
| `gpt-5-nano-2025-08-07`         |    $0.0030     |    25.6%    |
| `router` (cheap → strong)       |    $0.0061     |    23.4%    |
| `claude-haiku-4-5` (strong)     |    $0.0104     |    23.4%    |

**A null result (routing dominated) is a valid finding.** The metric's job is to
surface whether the router earns its overhead, not to guarantee it does. Here it
showed the router is strictly dominated on both cost and quality by `gpt-5-nano` — a
measurement the harness surfaced that a vibes-based assessment would have missed.

See `docs/analysis/routing-verdict.md` and the archived SDD at
`.claude/sdd/archive/sprint-7/phase-3-routing-evaluation/` for full evidence.

## Related

- `src/enterprise_rag_ops/eval/metrics.py` — `compute_cost_per_correct` implementation
- `tests/eval/test_metrics.py` — cassette-free unit tests (AC-3, AC-4, AC-5)
- [cost-accounting.md](cost-accounting.md) — generation `cost_usd` source, combined-cost router row
- [none-empty-denominator.md](none-empty-denominator.md) — the `None` on zero-denominator convention
- [failure-triage.md](failure-triage.md) — the `failure_mode` classification step
- `docs/analysis/routing-verdict.md` — the sprint-7 routing verdict using this metric
