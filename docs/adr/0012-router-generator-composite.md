# ADR 0012: RouterGenerator — Cheap-Default Cost Router as a `Generator` Composite

## Status

accepted

## Date

2026-06-04

## Context

ADR-0011 picked the inference-time escalation signal (hybrid abstention-OR-verbalized-
confidence, AUROC 0.685, ≈54% escalation) and wired it onto `CallStats.confidence_score`.
Sprint 7 phase 2 builds the `RouterGenerator` that **consumes** that signal: answer with the
cheap `gemini-2.5-flash-lite` by default, escalate to `claude-haiku-4-5` when the cheap answer
is not trustworthy, and expose the router as a system-under-test for the phase-3
cost-per-correct-answer sweep.

The build is the honest, measured baseline ADR-0011 §6 anticipates: at ≈54% escalation the
router is not expected to dominate either single model on cost-per-correct answer. Phase 2's
job is therefore to build the router **correctly — with fair combined-cost accounting** — so
phase 3 renders that verdict on the same `EvalRecord` schema as the baselines. Correctness of
the cost math, not a guaranteed cost win, is the deliverable.

## Decision

### 1. Composite by injection (Approach B), structural `Generator` conformance

`RouterGenerator` (`generation/router_generator.py`) holds **two injected `Generator`
instances** (`cheap`, `strong`), the escalation `threshold`, the price table, and the two
model ids it uses to look prices up. It does **not** inherit, register in
`_GENERATOR_FACTORY`, or touch `interfaces.py`. It conforms to the public `Generator`
Protocol **structurally** (duck-typed via `generate`), so the byte-for-byte Protocol-unchanged
constraint (SPRINT.md criterion 1, ADR-0011 §3) holds. `generate_with_stats` returns the same
`(AnswerWithSources, CallStats, RawCall)` 3-tuple as every sub-generator; `generate` delegates
to it and drops the stats/raw. Approaches A (discriminated-union `ModelConfig` member) and C
(runner-level routing) were rejected — A churns the public `ModelConfig.system` `Literal`, C
scatters routing across the runner.

### 2. The router is the single owner of combined cost (Option B-1)

The router is the only site that simultaneously holds both sub-`CallStats` objects and the
price table, so it is the correct and only owner of combined cost. On every call it computes
`cheap_cost` **always**; on escalation it additionally computes `strong_cost`. It manufactures
one output `CallStats` with `model = "router"`, `system = "router"`, summed tokens/latency, and

```
cost_usd = (cheap_cost or 0.0) + ((strong_cost or 0.0) if escalated else 0.0)
```

`confidence_score` on the output is the cheap call's. This enforces the #1 research-fairness
rule: **the cheap call is always charged on an escalated query, never dropped, never
double-counted.** B-2 (let the runner sum two rows) and B-3 (charge only the answer that
ships) were rejected — B-3 mis-attributes cost and would make the cost-ceiling guard track a
cheap-only figure.

### 3. The runner cost-accounting guard is a general seam extension

The runner's cost line changed from an **unconditional** recompute to a guarded one:

```python
if gen_stats.cost_usd is None:
    gen_stats.cost_usd = compute_cost_usd(gen_stats, config.prices.get(gen_stats.model))
```

**Invariant (the load-bearing decision):** _a generator that pre-sets `cost_usd` owns its
cost — the runner treats it as final and does not recompute._ This is what lets the router's
manufactured combined cost survive (a `"router"` model has no price entry, so an unconditional
recompute would null it). The guard is **backwards-compatible**: all three concrete generators
build `CallStats` without `cost_usd` (it defaults to `None`), so the guard body runs exactly as
before for every single-model config. The retrieval-abstain stub already pre-set `cost_usd=0.0`
and now correctly keeps it (0 tokens × any price = 0.0, so recorded values are unchanged).

### 4. Swept as a synthetic row, never a `ModelConfig`

`RunConfig` gains an optional, additive `router: RouterConfig | None = None`; a config without
a `router:` block leaves it `None` (backwards-compatible). The runner sweeps the router as a
synthetic `_SweepUnit("router", "router", RouterGenerator(...))` — **not** a
`ModelConfig(system="router")`, because `ModelConfig.system` is a `Literal` that excludes
`"router"`. The cheap/strong sub-generators resolve through the **same `_GENERATOR_FACTORY`
seam** the real models use (`"google"` → cheap, `"anthropic"` → strong), which is
`GeminiGenerator`/`AnthropicGenerator` in production and injectable doubles in tests.
`EvalRecord.gen_ai.system` and `gen_ai.request.model` are both `str` (not `Literal`), so the
`"router"` identity needs no schema change.

### 5. `gen_raw` is the cheap call's `RawCall`

The router returns the **cheap** call's `RawCall` as `gen_raw` for the bronze path (the cheap
call is always made). Strong-model raw payloads are not bronze-written this phase — phase 3
works from the JSONL records. A composite/strong raw write is deferred (Could).

## Consequences

- **Cost accounting is fair and testable.** The combined cost is exact and deterministic given
  fixed sub-generator outputs and a price table (asserted in `tests/generation/test_router_generator.py`
  and the runner-row test). Phase 3 can compare the router against the single-model baselines on
  the same `EvalRecord` schema.
- **Minimal blast radius.** `ModelConfig`, `_GENERATOR_FACTORY`, the three concrete generators,
  the `Generator` Protocol, and every prior `results/*.jsonl` are untouched. Removing the router
  later is one field deletion on `RunConfig` plus the runner branch.
- **A subtle invariant now matters more.** Because the cost guard skips any pre-set `cost_usd`,
  a future generator that sets `cost_usd` to a wrong value would have it trusted verbatim. The
  invariant in §3 is the contract; the AC-10 regression test guards the single-model path.
- **Hardcoded cheap=Gemini / strong=Anthropic.** `RouterConfig` carries the model **ids**, but
  the provider **systems** are hardcoded in the runner wiring (scope minimization). A future
  cross-provider router would add `RouterConfig.cheap_system`/`strong_system`. Recorded as a
  known limitation, not a defect.
- **Null phase-3 is the expected baseline.** Per ADR-0011 §6, the weak signal (≈54% escalation)
  means the router likely won't beat either single model on cost-per-correct answer. A null
  phase-3 result is the honest, publishable outcome.
- **Provenance.** Builds on ADR-0011 (escalation signal), ADR-0003 (Generator seam), ADR-0005
  (provider matrix), ADR-0007 (eval record schema). Related: ADR-0006 (cassette/no-mock testing
  — the router tests inject two `Generator`-shaped doubles, not SDK mocks).
