# router-cascade-composite

> **Purpose**: Compose two `Generator`s into a cheap-default / escalate-on-low-trust cost router (an LLM cascade) that is itself a structural `Generator` and owns its combined cost.
> **MCP Validated**: 2026-06-05

## When to Use

- Serving most queries with a cheap model and escalating only low-trust answers to a strong model — the classic LLM cascade (FrugalGPT, Chen/Zaharia/Zou 2023; "confidence-gated escalation").
- Adding a routing/cascade strategy to the eval sweep **without** churning the `Generator` Protocol, `_GENERATOR_FACTORY`, or `ModelConfig`.
- Any composite that must manufacture one fair, combined cost figure from two sub-calls.

## Implementation

`RouterGenerator` (`generation/router_generator.py`, ADR-0012) holds **two injected `Generator` instances** and conforms to the seam **structurally** via `generate` — no inheritance, no `_GENERATOR_FACTORY` registration, `interfaces.py` untouched.

```python
ROUTER_MODEL_ID = "router"   # synthetic identity; not a real provider/model
ROUTER_SYSTEM = "router"

class RouterGenerator:
    def __init__(self, cheap, strong, prices, cheap_model_id, strong_model_id, threshold=1.0):
        self._cheap, self._strong = cheap, strong          # injected Generators
        self._prices = prices                               # price table (single owner)
        self._cheap_model_id, self._strong_model_id = cheap_model_id, strong_model_id
        self._threshold = threshold

    def generate(self, context_chunks, question):
        # Drops stats/raw, exactly like the concrete generators — this is what makes
        # RouterGenerator a structural Generator (duck-typed; interfaces.py unchanged).
        result, _, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(self, context_chunks, question):
        cheap_ans, cheap_stats, cheap_raw = self._cheap.generate_with_stats(
            context_chunks, question
        )

        # Escalation rule (ADR-0011 §5): escalate UNLESS confident AND not abstaining.
        # Missing confidence → escalate (a non-Gemini cheap gen or a parse miss must not
        # silently pass through).
        escalate = (
            cheap_stats.confidence_score is None
            or cheap_stats.confidence_score < self._threshold
            or cheap_ans.answer == ABSTAIN_ANSWER
        )

        # Combined cost: cheap ALWAYS, strong IFF escalated. None summand → 0.0.
        cheap_cost = compute_cost_usd(cheap_stats, self._prices.get(self._cheap_model_id))
        if escalate:
            strong_ans, strong_stats, _ = self._strong.generate_with_stats(
                context_chunks, question
            )
            strong_cost = compute_cost_usd(strong_stats, self._prices.get(self._strong_model_id))
        else:
            strong_ans, strong_stats, strong_cost = None, None, None

        answer = strong_ans if escalate else cheap_ans

        combined_stats = CallStats(
            input_tokens=cheap_stats.input_tokens + (strong_stats.input_tokens if escalate else 0),
            output_tokens=cheap_stats.output_tokens + (strong_stats.output_tokens if escalate else 0),
            latency_s=cheap_stats.latency_s + (strong_stats.latency_s if escalate else 0.0),
            model=ROUTER_MODEL_ID,
            system=ROUTER_SYSTEM,
            cost_usd=(cheap_cost or 0.0) + ((strong_cost or 0.0) if escalate else 0.0),
            confidence_score=cheap_stats.confidence_score,   # the cheap call's signal
        )
        return answer, combined_stats, cheap_raw   # gen_raw = the cheap call's RawCall
```

## Three load-bearing decisions

1. **Structural conformance, not inheritance.** The router is a `Generator` because it has a matching `generate`/`generate_with_stats` — duck-typed. It is never a `ModelConfig` (whose `system` is a `Literal` that excludes `"router"`); the runner sweeps it as a synthetic `_SweepUnit("router", "router", RouterGenerator(...))`. `interfaces.py`, `_GENERATOR_FACTORY`, and the three concrete generators are byte-for-byte unchanged.
2. **Single-owner combined cost.** The router is the **only** site holding both sub-`CallStats` objects and the price table, so it is the only correct owner of combined cost. It charges cheap always, strong iff escalated, and maps `None` summands → `0.0`. Because `"router"` has no price-table entry, the runner must **not** recompute — see the cost-guard invariant in `rag-eval`.
3. **`gen_raw` is the cheap call's `RawCall`.** The cheap call always runs, so its raw payload is the stable bronze artifact. The strong call's raw is not bronze-written this phase (deferred).

## Configuration

| Setting           | Default | Description                                                             |
| ----------------- | ------- | ----------------------------------------------------------------------- |
| `threshold`       | `1.0`   | Escalate when `confidence_score < threshold` (ADR-0011 operating point) |
| `cheap_model_id`  | —       | Injected; used to look up the cheap price (production: Gemini)          |
| `strong_model_id` | —       | Injected; used to look up the strong price (production: Anthropic)      |

**Known limitation (ADR-0012):** cheap=Gemini / strong=Anthropic provider _systems_ are hardcoded in the runner wiring; `RouterConfig` carries only the model **ids**. A cross-provider router would add `cheap_system`/`strong_system`.

## Wiring (eval sweep)

`RunConfig` gains an optional additive `router: RouterConfig | None = None` (omit → `None`, backwards-compatible). The runner appends the synthetic router row only when set; the cheap/strong sub-generators resolve through the **same `_GENERATOR_FACTORY`** the real models use (`"google"` → cheap, `"anthropic"` → strong; injectable doubles in tests).

## Measured Outcome (sprint-7/phase-3)

The harness swept all four systems (500 questions, identical retrieval, same judge) and
produced this head-to-head (`docs/analysis/routing-verdict.md`):

| System                        | Cost / correct | Fact recall | Gen cost (500 q) |
| ----------------------------- | :------------: | :---------: | :--------------: |
| `gemini-2.5-flash-lite`       |    $0.0007     |    22.9%    |      $0.074      |
| `gpt-5-nano-2025-08-07`       |    $0.0030     |  **25.6%**  |      $0.356      |
| **`router`** (cheap → strong) |    $0.0061     |    23.4%    |      $0.714      |
| `claude-haiku-4-5`            |    $0.0104     |    23.4%    |      $1.230      |

**Verdict: the router is strictly dominated.** It sits at 8.7× the cheap model's
cost-per-correct with no quality dividend — the best single model on quality (GPT-5 Nano)
is also 2× cheaper. Two causes: (1) the escalation signal was too weak (AUROC 0.685) to
reliably target the queries that needed upgrading — confirmed at scale, ≈52% escalated
as ADR-0011 predicted; (2) the dominant model (`gpt-5-nano`) was not a constituent of the
router, so the routing axis was wrong regardless of signal quality. A null phase-3 result
was the expected honest baseline per ADR-0011 §6; the phase-3 finding confirmed it.

This is a valid sprint result: the harness rendered a measured verdict on a
plausible architecture and rejected it with numbers.

## See Also

- [generator-seam](../concepts/generator-seam.md) — the Protocol; what structural conformance and "localized swap" mean
- [add-a-generator](add-a-generator.md) — the sibling recipe for a _concrete_ provider (registers in the factory; the router deliberately does not)
- [stats-capture-seam](../../rag-eval/concepts/stats-capture-seam.md) — the `generate_with_stats` 3-tuple the router composes
- [combined-cost-accounting](../../rag-eval/concepts/cost-accounting.md) — the combined-cost rule and the runner cost-guard invariant
- ADR-0012 (`docs/adr/0012-router-generator-composite.md`) — the decision record
- ADR-0011 (`docs/adr/0011-escalation-signal.md`) — the escalation signal this consumes
- `docs/analysis/routing-verdict.md` — full head-to-head analysis and reproduce steps
