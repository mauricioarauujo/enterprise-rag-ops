# BRAINSTORM: phase-2-router-generator — RouterGenerator

**Sprint/Phase:** sprint-7/phase-2-router-generator | **Date:** 2026-06-04

---

## Problem Statement

Phase 1 validated an escalation signal (hybrid abstention-OR-verbalized-confidence, AUROC
0.685, ~54% escalation rate) and wired it onto `CallStats.confidence_score`. Phase 2 must
now build a `RouterGenerator` that sits behind the existing `Generator` Protocol: answer
with `gemini-2.5-flash-lite` by default and escalate to `claude-haiku-4-5` on the phase-1
signal, then wire it into the runner/config as a system-under-test for the phase-3 sweep.

**The first question this brainstorm must answer honestly:** given AUROC 0.685 (~54%
escalation), should the `RouterGenerator` be built at all? The router will escalate on more
than half of queries, eroding most of the cheap/strong price gap before buying quality.
ADR-0011 explicitly frames "a null phase-3 result as the expected, honest baseline" and
delegates the build/rescope decision here. The answer below argues for building it — but
with eyes wide open on what phase-3 will almost certainly show.

---

## Suggested Research & KB Work

| Topic                                                            | Coverage                                                                                                                                                             | Action                                                                                                                                    |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Router/cascade as a `Generator` composite                        | **Missing** — SPRINT.md Knowledge Plan explicitly deferred `/update-kb rag-generation` (router/cascade pattern) until after the phase-2 ADR.                         | `/update-kb rag-generation` after phase-2 ADR lands (Sprint-Wide plan item).                                                              |
| Combined cost accounting across two model calls                  | **Thin** — `rag-eval` KB covers `compute_cost_usd` and single-model cost accounting (cost-accounting concept), but not the two-call router case.                     | No new KB needed now; design the approach in this phase, then `/update-kb rag-eval` post-phase-3 once cost-per-correct-answer stabilises. |
| `ModelConfig` extension patterns / factory injection             | **Sufficient** — `multi-model-runner` pattern + `rag-eval` index cover the factory dispatch, `ModelConfig` shape, and `RunConfig`. No deep research needed.          | Cite codebase directly.                                                                                                                   |
| Fair cascade evaluation (double-counting, threshold overfitting) | **Sufficient** — Research doc `sprint-7-escalation-signal-research.md` Q6 (Bouchard 2026) covers the pitfalls. ADR-0011 §5 references the operating-point procedure. | Enforce Q6 discipline in phase-3; no new KB needed now.                                                                                   |

No `--deep-research` call needed. The research doc and existing KB domains cover the
design-relevant areas.

---

## Build vs. Rescope — The Honest Assessment

The case **for building it:**

1. The seam is already wired. `CallStats.confidence_score` is live; `GeminiGenerator`
   produces it on every call. The incremental implementation cost is low (one new
   composite class + minor config/factory extension).
2. The portfolio point is the _measured_ decision. A `RouterGenerator` that demonstrably
   underperforms the single-model baselines at phase-3 is a valid, senior result — it shows
   the harness can measure something real, including null outcomes. Skipping the
   build leaves that story unfinished.
3. ADR-0011 §6 explicitly says phase-2 proceeds; ADR-0011 is accepted. Reversing that
   without new evidence would be premature.

The case **against** (or for rescoping):

1. At ~54% escalation the router largely becomes an expensive single-model baseline. Phase-3
   will almost certainly show it dominates neither the cheap model (it calls it twice as
   often) nor the strong model (it calls it half the time). The "win" scenario is narrow.
2. Budget is tight (~5h/week). A full `RouterGenerator` + config/factory wiring + combined
   cost accounting + mirrored tests is a real 2–3h implementation surface, not a trivial seam.

**Recommendation: build it**, because (a) the seam cost is already sunk, (b) the phase-3
verdict is the deliverable the sprint promises, and (c) a null result is publishable.
Frame it explicitly as "measure the cost of a weak signal" not "win on cost."

---

## Approaches Considered

| Approach                                                                                        | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Pros                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Cons                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Effort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| A — Full first-class `"router"` system in `ModelConfig` + factory                               | Add `system: Literal["router"]` to `ModelConfig`; add a `RouterConfig(ModelConfig)` subclass with `cheap_model`, `strong_model`, `threshold` fields; add `"router"` to `_GENERATOR_FACTORY`; factory constructs `RouterGenerator` with two sub-generators injected. Config YAML expresses the router inline in `models:` list. Router computes combined cost itself by looking up both prices from the price table (passed at construction or at call time). | Cleanest config/YAML surface; router appears as a first-class model in the sweep; factory/runner changes are minimal and backwards-compatible.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | `ModelConfig.system` is `Literal["openai", "anthropic", "google"]` — adding `"router"` requires a `Union[ModelConfig, RouterConfig]` discriminated union in `RunConfig.models`; Pydantic discriminated union needs a `type:` discriminator or restructured field; moderate config schema churn. Factory receives a `RouterConfig` not a `ModelConfig` — the `generator_cls(model=model.model_id)` call pattern breaks (router needs two models, not one). Combined cost: router calls `compute_cost_usd` for each sub-call using prices from the table, accumulates into a single `CallStats` it manufactures. Runner's existing `config.prices.get(gen_stats.model)` call would receive the router's "virtual" model id — needs a sentinel price entry or a skip in the runner. This approach has the most config-layer ripple. | L                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| B — Router via composition/injection; router config block separate from `models:` (Recommended) | Keep `ModelConfig` and `_GENERATOR_FACTORY` unchanged. Add a `RouterConfig(BaseModel)` as a new **optional top-level field** on `RunConfig` (`router: RouterConfig                                                                                                                                                                                                                                                                                           | None = None`). `RouterConfig`carries`cheap_model_id`, `strong_model_id`, `threshold: float = 1.0`, and a logical `system: Literal["router"] = "router"`. The runner detects `config.router`and constructs a`RouterGenerator(cheap=GeminiGenerator(...), strong=AnthropicGenerator(...), threshold=...)`directly — no factory lookup. The router is appended to the per-model sweep as a pseudo-model entry with a synthetic`ModelConfig(model_id="router", system="router")`generated by the runner for`EvalRecord.gen_ai`fields. Combined cost:`RouterGenerator.generate_with_stats`makes the cheap call, decides, optionally makes the strong call, then manufactures its own`CallStats`with`cost_usd = cheap_cost + (strong_cost if escalated else 0)` — it owns the price table reference passed at construction. Runner's cost-accounting line (`gen_price = config.prices.get(gen_stats.model)`) receives `cost_usd`already set in the router's`CallStats`and skips (or uses`compute_cost_usd`with`price=None`, which logs a warning — the runner must check for a pre-set `cost_usd` and skip re-computation). | Backwards compatible — `ModelConfig`, `_GENERATOR_FACTORY`, and all existing generator wiring are untouched. Router is constructed by composition (two real `Generator` instances injected) — clean and testable in isolation. Threshold and model ids are explicit in config. Combined cost is owned by the router class itself — the class that has both sub-`CallStats` is the right place.                                                                                                                                                                                                                                                                                                                                                                                                                                   | Runner needs a small branch to handle the router path (construct it, append it to the sweep). Runner's cost-accounting (`compute_cost_usd` call at line 200-201) must detect pre-set `cost_usd` and skip — a 2-line guard. `EvalRecord.gen_ai.system` will carry `"router"` which is a new system value in the JSONL (not in any existing report — needs consideration for phase-3 report rendering). Bronze write path receives `gen_raw` from the router — router can return the cheap call's `RawCall`, or a composite, or `None` (simplest). | M   |
| C — Minimal: router as a thin composite, cost bookkeeping deferred to phase-3 report            | `RouterGenerator` class only — no config/runner wiring. Phase-3 drives it by constructing it directly in a bespoke eval script (not via `rag-eval` config). Combined cost is computed in the phase-3 analysis script by summing cheap + strong costs across records, using the JSONL as the data source.                                                                                                                                                     | Smallest implementation surface; no config/runner changes; router is testable in isolation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Does not satisfy SPRINT.md criterion 1 ("wire it into the runner/config as a system-under-test"). Phase-3 can't reuse `rag-eval` cleanly — it needs a bespoke driver, which is more work, not less. Combined cost is harder to get right post-hoc (e.g., if cheap escalated query's cost is mis-attributed). The portfolio story ("the harness measures the router the same way it measures the baselines") is weaker.                                                                                                                                                                                                                                                                                                                                                                                                           | S (router class), L (phase-3 bespoke driver)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

---

## Recommended Approach

**Approach B** — router by composition, `RouterConfig` as an optional top-level field on
`RunConfig`, runner constructs the `RouterGenerator` directly, combined cost owned by the
router class.

Rationale:

1. **Factory/ModelConfig unchanged** — no Pydantic discriminated union, no `Literal`
   extension, no `_GENERATOR_FACTORY` churn. The three existing generators are untouched.
   A future "remove the router" is one field deletion in `RunConfig`.

2. **Combined cost in the right owner** — `RouterGenerator.generate_with_stats` is the only
   site that holds both `CallStats` objects at the same time. It has the cheap sub-stats,
   the optional strong sub-stats, and the price table (passed at construction from
   `RunConfig.prices`). Manufacturing a single output `CallStats` there — with
   `cost_usd = cheap_cost + (strong_cost if escalated else 0)` and token fields summed — is
   both correct and local. This avoids the biggest research-fairness pitfall (charging only
   the cheap call on escalated queries, per Bouchard 2026 Q6).

3. **Runner change is surgical** — one `if config.router:` block that constructs the
   `RouterGenerator`, plus a 2-line guard in the cost-accounting section to skip
   `compute_cost_usd` when `cost_usd` is already set.

4. **The seam fits** — `RouterGenerator` implements `generate_with_stats` (returns
   `(AnswerWithSources, CallStats, RawCall)`) and `generate` (delegates). It is a valid
   `Generator` Protocol impl (duck-typed; no structural change to `interfaces.py`).

5. **Phase-3 reuses `rag-eval` cleanly** — the router appears as a row in the sweep
   JSONL, comparable to the other models on the same `EvalRecord` schema.

---

## Escalation Rule (per ADR-0011)

The router escalates to the strong model when the cheap answer is NOT trustworthy.
ADR-0011 §5 operating procedure: **escalate unless `confidence_score == 1.0` AND the model
did not abstain** (`answer != ABSTAIN_ANSWER`). The threshold (`1.0`) should be a config
knob on `RouterConfig` (default `1.0` matches the ADR-0011 operating point); sweeping it
is out of scope for this phase (phase-3/out per SPRINT.md).

The router checks:

- `stats.confidence_score` off the cheap `generate_with_stats` call
- `answer.answer == ABSTAIN_ANSWER` (importing `ABSTAIN_ANSWER` from `generation/schema.py`)
- Escalate when `confidence_score is None OR confidence_score < threshold OR answer == ABSTAIN_ANSWER`
  (i.e., escalate unless confidence == threshold (1.0) AND not abstained)

---

## The Combined-Cost Problem (the Design Crux)

This is the most important design decision in the phase. The runner currently calls
`compute_cost_usd(gen_stats, gen_price)` with a single `Price` for the generator's model.
A router makes 1–2 calls with different models at different prices.

**Option B-1 (router owns combined cost — preferred):** `RouterGenerator.generate_with_stats`
receives the price table at construction (`prices: dict[str, Price]`). It calls cheap
`generate_with_stats`, computes `cheap_cost = compute_cost_usd(cheap_stats, prices[cheap_id])`,
optionally calls strong `generate_with_stats`, computes `strong_cost`. It manufactures an
output `CallStats` with:

- `model = "router"` (or `"{cheap_id}+{strong_id}"`)
- `system = "router"`
- `input_tokens = cheap_in + (strong_in if escalated else 0)`
- `output_tokens = cheap_out + (strong_out if escalated else 0)`
- `latency_s = cheap_latency + (strong_latency if escalated else 0)`
- `cost_usd = cheap_cost + (strong_cost if escalated else 0)`
- `confidence_score = cheap_stats.confidence_score`

Runner guard: before `gen_price = config.prices.get(gen_stats.model)`, check if
`gen_stats.cost_usd is not None` and skip the `compute_cost_usd` call — treat a pre-set
cost as final. This is a 2-line change (`if gen_stats.cost_usd is None: ...`).

**Option B-2 (runner owns combined cost — rejected):** Router returns two separate
`CallStats` objects. Runner knows to sum them. Breaks the `generate_with_stats` return
type contract (`tuple[AnswerWithSources, CallStats, RawCall]`) and pushes complex
two-model logic into the runner.

**Option B-3 (phase-3 report does the accounting — rejected):** Router returns only the
cheap `CallStats`, phase-3 analysis script joins and sums. Violates Q6 discipline
(cheap-call cost is mis-attributed on escalated queries mid-run), and breaks the
cost-ceiling guard in the runner (it would track only cheap cost, not the true cost).

**Verdict: B-1.** The router class is the right owner. The runner guard is minimal and
backwards-compatible (a `None` cost_usd is the existing fallback path).

---

## Eval Record Identity (`gen_ai.system` and `model` fields)

`EvalRecord.gen_ai.system` carries the system identifier (used in reports and the JSONL
schema). For the router, there are two options:

- **`"router"` as the system** — clean, explicit, no collision with the three existing
  values. The phase-3 report filters on it distinctly. `EvalRecord.gen_ai.request.model`
  can carry `"router"` or a descriptive string like
  `"gemini-2.5-flash-lite→claude-haiku-4-5"`.
- **Cheap model's system** — misleading; would fold the router into the Gemini row in
  any report that groups by system.

**Decision:** `system = "router"`, `model = "router"` (or the composite string). The runner
synthesizes a `ModelConfig(model_id="router", system="router")` to pass into the
`EvalRecord.gen_ai` constructor. No `ModelConfig.system` `Literal` change needed because
`EvalRecord.gen_ai.system` accepts any `str` (it is `str`, not `Literal`).

---

## Bronze Write Path

The runner's bronze writer calls `bronze_writer.write(...)` with `gen_raw.request` /
`gen_raw.response`. For the router, the natural choice is to return the cheap call's
`RawCall` as the primary `gen_raw` (it is always made). The strong call's raw payload
can be attached as a supplementary write if `persist_bronze` is on — but this is an
optional refinement. Simplest: return cheap `RawCall` always; strong payload is logged
but not bronze-written (it can be added later). Phase-3 does not require the strong raw
payload.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                                                                                                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| **Must**   | `RouterGenerator` class in `generation/router_generator.py` — `generate` and `generate_with_stats` methods; escalation logic (confidence threshold + abstention sentinel); combined-cost `CallStats` manufacture (cheap + conditional strong cost).                                                                             |
| **Must**   | `RouterConfig(BaseModel)` in `eval/config.py` — `cheap_model_id: str`, `strong_model_id: str`, `threshold: float = 1.0`. Optional top-level field `router: RouterConfig                                                                                                                                                         | None = None`added to`RunConfig`. |
| **Must**   | Runner wiring (`eval/runner.py`) — detect `config.router`, construct `RouterGenerator`, append to sweep. Guard `compute_cost_usd` call to skip when `gen_stats.cost_usd` is already set. Synthesize `ModelConfig`-equivalent for `EvalRecord.gen_ai`.                                                                           |
| **Must**   | Router eval config (`configs/router.yaml`) — cheap model `gemini-2.5-flash-lite` + strong model `claude-haiku-4-5`, `threshold: 1.0`, `cost_ceiling_usd: 5.0`, dev-safe `limit: 20`.                                                                                                                                            |
| **Must**   | Mirrored tests (`tests/generation/test_router_generator.py`) — cassette/replay pattern; no mocked LLM; test: no-escalation path (confidence=1.0, not abstained), escalation path (confidence<1.0 or abstained), combined cost correctness (cheap+strong), combined cost when not escalated (cheap only), `generate()` contract. |
| **Should** | `EvalRecord.gen_ai.system = "router"` readable in the phase-3 report without breakage — verify existing report rendering handles an unknown system value gracefully.                                                                                                                                                            |
| **Should** | Dev smoke (`configs/router.dev.yaml`) — 5 questions, no cost ceiling, for rapid iteration.                                                                                                                                                                                                                                      |
| **Could**  | Bronze write path for strong-model raw call when `persist_bronze=True`.                                                                                                                                                                                                                                                         |
| **Could**  | Composite model id string `"gemini-2.5-flash-lite+claude-haiku-4-5"` in `EvalRecord.gen_ai.request.model` for legibility in JSONL forensics.                                                                                                                                                                                    |
| **Won't**  | Threshold sweep (phase-3 work — phase-2 picks one operating point).                                                                                                                                                                                                                                                             |
| **Won't**  | New escalation signals beyond what ADR-0011 defined (confidence + abstention).                                                                                                                                                                                                                                                  |
| **Won't**  | Change to the public `Generator` Protocol seam (`interfaces.py` untouched — SPRINT.md criterion 1).                                                                                                                                                                                                                             |
| **Won't**  | Self-consistency or multi-sample approaches (cost math fails at 2.7× price ratio — ADR-0011).                                                                                                                                                                                                                                   |
| **Won't**  | Anthropic or OpenAI as the cheap model (sprint spec: Gemini cheap, Claude strong).                                                                                                                                                                                                                                              |
| **Won't**  | New eval metrics (cost-per-correct-answer is phase-3 work; phase-2 produces the JSONL row, phase-3 computes the metric).                                                                                                                                                                                                        |
| **Won't**  | Dashboard/observability changes for the router (out of scope for this sprint).                                                                                                                                                                                                                                                  |

---

## Open Questions

1. **Build vs. rescope (human decision).** Given AUROC 0.685 and ~54% escalation rate, the
   recommendation above is to build and measure. If the user's time budget is under pressure
   (or the sprint should close after phase-1 with the ADR as the deliverable), this is the
   moment to rescope. Recommendation: build it — the seam cost is sunk, the portfolio story
   needs the phase-3 sweep. Confirm at `/define` before proceeding.

2. **Combined-cost `CallStats` model/system identity.** Should the router's `CallStats.model`
   be `"router"`, a composite string `"gemini-2.5-flash-lite+claude-haiku-4-5"`, or the cheap
   model id? The choice affects how the phase-3 report groups and labels rows. `"router"` is
   cleanest for filtering; the composite string is more self-documenting in raw JSONL.
   `/define` should pin one.

3. **Runner cost-accounting guard — scope of the change.** The proposed guard (`if
gen_stats.cost_usd is None: gen_stats.cost_usd = compute_cost_usd(...)`) is a 2-line
   change in `runner.py`. But it also changes behavior for all generators: any `CallStats`
   with a pre-set `cost_usd` would skip re-computation. Today no generator pre-sets it
   (they all return `cost_usd=None` and the runner sets it). The guard is backwards-compatible,
   but `/define` should confirm this is the right seam extension rather than a router-specific
   branch.

4. **`RouterConfig` threshold as a `float` vs. a `Literal[1.0]` default.** ADR-0011 says one
   operating point (`confidence == 1.0`) is the calibrated procedure. Making `threshold` a
   float knob allows future experimentation without code change. But if the intent is strictly
   one operating point, a hard-coded default is fine. The question is whether the config YAML
   should expose the threshold at all (making it a documented choice) or silently hardcode it.

5. **What does the router return as `gen_raw` (bronze path)?** Cheapest option: always the
   cheap call's `RawCall`. If the strong call ran, its raw payload is logged but not
   bronze-written unless `persist_bronze` is extended. `/define` should state whether strong
   raw payloads need to be persisted for phase-3 forensics (probably not — phase-3 works from
   the JSONL records).

---

## Next Step

-> `/define sprint-7/phase-2-router-generator`
