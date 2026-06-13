# DESIGN: sprint-7/phase-2-router-generator — RouterGenerator

**Sprint/Phase:** sprint-7/phase-2-router-generator | **Date:** 2026-06-04

## Architecture

The phase adds a single new composite generator and wires it into the existing eval
sweep with the smallest possible blast radius. Nothing in the public `Generator` seam,
the `_GENERATOR_FACTORY`, the three concrete generators, or the `EvalRecord` schema
changes (NFR-1, NFR-7).

### Component map

```
                        configs/router.yaml ──load_from_yaml──► RunConfig
                                                                  │  .router: RouterConfig | None   (NEW, FR-6)
                                                                  │  .prices: dict[str, Price]      (existing)
                                                                  ▼
  eval/runner.py  run_evaluation()
    │  if config.router is not None:                                          (NEW branch, FR-8)
    │     router = RouterGenerator(
    │        cheap   = GeminiGenerator(model=router.cheap_model_id),          # existing concrete generator
    │        strong  = AnthropicGenerator(model=router.strong_model_id),      # existing concrete generator
    │        threshold = router.threshold,
    │        prices  = config.prices,
    │        cheap_model_id  = router.cheap_model_id,
    │        strong_model_id = router.strong_model_id,
    │     )
    │     # appended to the swept "models" as a synthetic row (model_id="router", system="router")
    │
    │  cost guard (FR-9, runner.py:200-201):
    │     if gen_stats.cost_usd is None:                                      (CHANGED: was unconditional)
    │         gen_stats.cost_usd = compute_cost_usd(gen_stats, gen_price)
    ▼
  generation/router_generator.py  RouterGenerator   (NEW, FR-1..FR-5, FR-7)
    │  generate_with_stats(context_chunks, question) -> (AnswerWithSources, CallStats, RawCall)
    │     1. cheap_ans, cheap_stats, cheap_raw = cheap.generate_with_stats(...)        # ALWAYS
    │     2. escalate = (cheap_stats.confidence_score is None
    │                    OR cheap_stats.confidence_score < threshold
    │                    OR cheap_ans.answer == ABSTAIN_ANSWER)               (FR-4, ADR-0011 §5)
    │     3. if escalate: strong_ans, strong_stats, _ = strong.generate_with_stats(...)
    │     4. manufacture combined CallStats (FR-5): cheap charged ALWAYS,
    │        strong charged IFF escalated; None summands -> 0.0
    │     5. return (strong_ans if escalate else cheap_ans), combined_stats, cheap_raw  (FR-7)
    │  generate(...) -> AnswerWithSources   # delegates, drops stats/raw (FR-3)
    ▼
  generation/schema.py  ABSTAIN_ANSWER          (imported, unchanged — SSoT sentinel)
  eval/records.py       CallStats, compute_cost_usd, Price   (imported, unchanged)
```

### Data flow & the design crux (Option B-1, FR-5)

`RouterGenerator` is the **single site** that simultaneously holds both sub-`CallStats`
objects and the price table, so it is the correct and only owner of combined cost. On
every call it charges `cheap_cost = compute_cost_usd(cheap_stats, prices.get(cheap_model_id))`;
on escalation it additionally charges `strong_cost = compute_cost_usd(strong_stats,
prices.get(strong_model_id))`. It manufactures one output `CallStats`:

- `model = "router"`, `system = "router"`
- `input_tokens = cheap_in + (strong_in if escalated else 0)`
- `output_tokens = cheap_out + (strong_out if escalated else 0)`
- `latency_s = cheap_lat + (strong_lat if escalated else 0)`
- `cost_usd = (cheap_cost or 0.0) + (strong_cost or 0.0 if escalated else 0.0)`
- `confidence_score = cheap_stats.confidence_score`

This pre-sets `cost_usd`, which the runner's `if gen_stats.cost_usd is None` guard (FR-9)
then treats as final — so the cost-ceiling accumulator tracks the true cheap+strong cost
(NFR-5), and the cheap call is never dropped on an escalated query (the #1 fairness rule,
Bouchard 2026 Q6 / NFR-2).

### Why this shape

- The router conforms **structurally** to `Generator` via `generate` (duck-typed). It
  does not inherit, register in the factory, or touch `interfaces.py` (NFR-1, AC-7).
- `RouterConfig` is an additive optional top-level field on `RunConfig`; a YAML without
  a `router:` block leaves `router is None` (backwards-compatible, AC-8). Removing the
  router later is one field deletion plus the runner branch (NFR-7).
- The cost guard is a **general seam extension** (`if cost_usd is None`), not a
  router-only branch: every existing generator returns `cost_usd=None`, so the guard
  body runs exactly as before for single-model configs (NFR-4, AC-10); the existing
  retrieval-abstain stub pre-sets `cost_usd=0.0` (runner.py:175-182) and the guard now
  correctly preserves that `0.0` instead of recomputing it.

## File Manifest

| File                                                                     | Change                                                                                                                                                                                                                                                                                                                                                                                            | Owner (agent / direct) | Phase order             |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ----------------------- |
| `src/enterprise_rag_ops/eval/config.py`                                  | Add `RouterConfig(BaseModel)` (`cheap_model_id: str`, `strong_model_id: str`, `threshold: float = 1.0`); add optional `router: RouterConfig \| None = None` to `RunConfig`. `ModelConfig.system` Literal + loader untouched. (FR-6, AC-8)                                                                                                                                                         | direct                 | 2 — Config              |
| `src/enterprise_rag_ops/generation/router_generator.py`                  | **New.** `RouterGenerator` composite — `generate_with_stats` (escalation + combined-cost manufacture) and `generate` (delegates). Imports `ABSTAIN_ANSWER` from `generation/schema.py`, `CallStats`/`compute_cost_usd`/`Price` from `eval/records.py`, `RawCall` from `eval/raw_call.py`, `AnswerWithSources` from `generation/schema.py`, `Chunk` from `retrieval/schema.py`. (FR-1..FR-5, FR-7) | direct                 | 3 — Core module logic   |
| `src/enterprise_rag_ops/eval/runner.py`                                  | Construct `RouterGenerator` when `config.router is not None`, append as synthetic `("router","router")` sweep row with synthesized `gen_ai` identity; replace the unconditional cost line (200-201) with the `if gen_stats.cost_usd is None:` guard. (FR-8, FR-9, FR-10)                                                                                                                          | direct                 | 4 — Eval harness wiring |
| `configs/router.yaml`                                                    | **New.** cheap `gemini-2.5-flash-lite`, strong `claude-haiku-4-5-20251001`, `threshold: 1.0`, judge `gpt-5-nano-2025-08-07`, `cost_ceiling_usd: 5.0`, `limit: 20`, `prices` table for cheap+strong+judge. (FR-11, AC-12)                                                                                                                                                                          | direct                 | 2 — Config              |
| `configs/router.dev.yaml`                                                | **New.** Same router block, `limit: 5`, no `cost_ceiling_usd`, dev `run_id`. (FR-11 Should, AC-12)                                                                                                                                                                                                                                                                                                | direct                 | 2 — Config              |
| `tests/generation/test_router_generator.py`                              | **New.** Inject TWO fake `Generator`-shaped sub-generators (count calls + return fixed `(AnswerWithSources, CallStats, RawCall)`); cover AC-1..AC-7. No `unittest.mock` of an LLM SDK or `Generator` (ADR-0006). (FR-12, AC-11)                                                                                                                                                                   | direct                 | 6 — Tests               |
| `tests/eval/test_runner.py` _(or new `test_runner_router.py` if absent)_ | Add cases: router branch produces a row with `gen_ai.system == "router"` / `gen_ai.request.model == "router"` and `generation.cost_usd` equal to the router-manufactured cost (guard did not overwrite); single-model regression (AC-10).                                                                                                                                                         | direct                 | 6 — Tests               |
| `tests/eval/test_config.py` _(or new, if absent)_                        | Add cases: `RouterConfig` validates + `threshold` defaults to `1.0`; `load_from_yaml` parses `configs/router.yaml` / `router.dev.yaml`; YAML without `router:` leaves `router is None`. (AC-8, AC-12)                                                                                                                                                                                             | direct                 | 6 — Tests               |

> No `src/` module gets a new public schema; `interfaces.py`, `records.py`,
> `raw_call.py`, `schema.py`, the three concrete generators, and `_GENERATOR_FACTORY`
> are **read-only** for this phase. No ADR is required (see Risks).

## Implementation Phases

Per the phase-ordering convention (schema → config → core → eval wiring → obs → tests → docs):

1. **Data schema / dataset loading** — none. `CallStats`, `EvalRecord`, `GenAiFields`,
   `RawCall` already carry every field the router needs (`cost_usd`/`confidence_score`
   optional; `system`/`model` are `str`). No schema edit (AC-9).
2. **Config** — `eval/config.py`: `RouterConfig` + optional `RunConfig.router`.
   `configs/router.yaml` + `configs/router.dev.yaml`.
3. **Core module logic** — `generation/router_generator.py`: the `RouterGenerator`
   composite (escalation rule FR-4, combined-cost manufacture FR-5, `generate`/`generate_with_stats`).
4. **Eval harness wiring** — `eval/runner.py`: router-construction branch (FR-8),
   synthesized `gen_ai` identity (FR-10), cost-accounting guard (FR-9).
5. **Observability hooks** — none (Won't: dashboard/observability for the router).
6. **Tests** — `tests/generation/test_router_generator.py` (router unit, two fakes);
   runner + config test additions for AC-8/9/10/12. `make lint test` green (AC-13).
7. **Docs + ADR** — none in this phase. The router/cascade KB pattern and a phase-2 ADR
   are sprint-wide items scheduled **after** this phase lands (see Infrastructure Gaps).

## Infrastructure Gaps

Three-layer check (domain existence, concept coverage, agent alignment), run
independently of DEFINE's Infrastructure Readiness table — conclusion **confirms** DEFINE:
no gap blocks this phase.

| Gap Type           | Area              | Detail                                                                                                                                                                                                                                                                                                                                                                       | Recommendation                                                                |
| ------------------ | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Missing domain     | —                 | All affected tech areas have a KB domain: `rag-generation` (Generator seam, `ABSTAIN_ANSWER`, add-a-generator pattern) and `rag-eval` (cost-accounting, multi-model-runner, eval-record-schema, cassette-replay, stats-capture-seam). No new domain.                                                                                                                         | None                                                                          |
| Missing concept    | `rag-generation`  | The **router/cascade `Generator`-composite** pattern (two injected `Generator`s, escalation rule, combined-cost ownership) is not yet a documented concept/pattern — DEFINE/BRAINSTORM both note `/update-kb rag-generation` is **deferred** to after the phase-2 ADR (SPRINT.md Knowledge Plan). Not a blocker: the design is fully specified in this DESIGN + ADR-0011 §5. | `/update-kb rag-generation` — **after** the phase-2 ADR (post-phase, not now) |
| Missing concept    | `rag-eval`        | The **two-call combined-cost** case (cheap-always + strong-iff-escalated, None→0.0) extends the single-model `cost-accounting` concept. Thin, not absent — `compute_cost_usd` + the `cost_usd: float\|None` precedent cover the primitives. Defer until cost-per-correct-answer stabilizes in phase-3.                                                                       | `/update-kb rag-eval` — **post-phase-3**                                      |
| Missing specialist | generation / eval | No specialist agent owns `src/generation` or `src/eval` (all five existing agents are workflow agents with `kb_domains: []` — `brainstorm/define/design/code-reviewer/kb-architect`). Every manifest file is therefore `direct`. The phase is a single new class + a surgical runner/config edit; the change is small and well-specified — a specialist is not warranted.    | None (no `/new-agent`)                                                        |

**Verdict: no new KB or agent blocks this phase.** The two `/update-kb` items are
intentionally scheduled post-phase (KB documents _stabilized_ knowledge; the
router/cascade pattern stabilizes only once the phase-2 ADR records the decision and
phase-3 measures the verdict). This matches DEFINE's Infrastructure Readiness conclusion.

## Consistency Check

Non-trivial phase (3 `src`/`config` modules edited + 3 test files; DEFINE went through
brainstorm→define edits). Six-pass cross-check of DEFINE↔DESIGN and the constitution
(AGENTS.md § Engineering Behavior + § Conventions, ADR-0011, ADR-0006, KB domains).

**Verdict: ✅ CONSISTENT** — no CRITICAL/HIGH drift. Three LOW notes for the implementer.

| ID  | Severity | Pass               | Location             | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Suggested fix                                                                                                                                                                                                                                                                                                                                                                 |
| --- | -------- | ------------------ | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | LOW      | Coverage           | FR-12 / manifest     | DEFINE names only `tests/generation/test_router_generator.py`. AC-8/9/10/12 (config parse, router JSONL row, runner guard backwards-compat) cannot be exercised purely from the generation unit test — they need runner/config tests. Manifest adds `tests/eval/test_runner.py` + `tests/eval/test_config.py` entries to close the gap.                                                                                                                                                | Implementer: add the AC-8/9/10 assertions to the existing `tests/eval/` files if present, else create them with `__init__.py` per the mirror convention. Not a DEFINE defect — DEFINE's AC list already implies them.                                                                                                                                                         |
| C-2 | LOW      | Ambiguity          | FR-8 / runner sweep  | DEFINE says "append it to the swept systems as a pseudo-model row" but `runner.py` iterates `config.models` (a `list[ModelConfig]`), and `ModelConfig.system` is a `Literal` that excludes `"router"`. A literal `ModelConfig(system="router")` would fail validation. The router must therefore be swept via a parallel synthetic row (e.g. a small internal `(generator, model_id, system)` tuple appended after the `config.models` loop), **not** by constructing a `ModelConfig`. | Implementer: drive the router as a separate iteration unit carrying `model_id="router"`, `system="router"` for the `gen_ai` synthesis (FR-10) — do **not** instantiate `ModelConfig(system="router")`. The `process_one` closure already takes `model.model_id`/`model.system`; pass a duck-typed stand-in or refactor the loop body to take `(model_id, system, generator)`. |
| C-3 | LOW      | Underspecification | FR-7 / runner bronze | The router returns the cheap `RawCall` as `gen_raw`. The runner's bronze write (runner.py:257-275) tags it `model.model_id` = `"router"`, `system` = `"router"` in the bronze meta — which is correct and needs no special-casing, but the strong call's raw is silently discarded (FR-7: deferred, by design).                                                                                                                                                                        | None — confirm in implementation that the cheap `RawCall` flows through the existing bronze path unchanged; strong-raw persistence stays Could-deferred.                                                                                                                                                                                                                      |

Notes on the passes that found nothing:

- **Duplication** — none. FR-4/FR-5 and the BRAINSTORM "Combined-Cost Problem" describe
  the same rule without conflicting phrasing.
- **Constitution alignment** — no violation. The composite is a _named, likely_ seam
  (ADR-0011 §6 explicitly anticipates the router), not "in case"; no speculative scope
  (threshold sweep, new signals, dashboard all explicitly Won't); test layout follows the
  mirror convention; no stranger-test leak (DESIGN is system-only). The cost guard is a
  general seam extension, consistent with § Engineering Behavior "design the seam, do not
  pre-build behind it."
- **Inconsistency** — terminology is stable (`cheap`/`strong`, `escalate`, `confidence_score`,
  `ABSTAIN_ANSWER`) across BRAINSTORM, DEFINE, ADR-0011, and this DESIGN.

## Risks & Trade-offs

- **No ADR in this phase — flagged.** A phase-2 ADR (the router-composite decision:
  Approach B, B-1 combined cost, `system="router"` identity, the cost-guard seam
  extension) is a sprint-wide item scheduled _after_ this phase, per SPRINT.md. The
  decision content is already captured in BRAINSTORM (approaches A/B/C, B-1/B-2/B-3) and
  ratified in DEFINE; this phase ships code, the ADR follows. **Risk if skipped:** the
  cost-guard behavior change (any pre-set `cost_usd` now wins) is a quiet semantic shift
  with no ADR — acceptable because it is backwards-compatible today (NFR-4, AC-10) and
  the BRAINSTORM records the rationale, but the post-phase ADR should name it explicitly.

- **`ModelConfig.system` Literal vs. the `"router"` sweep row (C-2).** The single real
  pitfall for the implementer: do not try to express the router as a `ModelConfig`. Drive
  it as a synthetic iteration unit so the `Literal` never sees `"router"`. This is why
  Approach B (not A) was chosen — A's discriminated-union churn is avoided entirely.

- **Cost guard touches all generators (NFR-4).** Backwards-compat rests on the invariant
  "no current generator pre-sets `cost_usd`." Verified: gemini/anthropic/openai all build
  `CallStats` with `cost_usd` defaulting to `None`; only the retrieval-abstain stub and
  the router pre-set it. AC-10 regression-guards this; keep that test.

- **Weak signal, expected null phase-3 (not a phase-2 risk).** At ~54% escalation the
  router will likely not dominate either single model on cost-per-correct-answer
  (ADR-0011 §6). Phase-2's job is a _correct_ router with fair accounting so phase-3 can
  render that verdict — explicitly accepted in the problem statement; not a design defect.

- **Determinism is testable (NFR-6).** With fixed fake sub-generator outputs and a fixed
  price table, the manufactured `CallStats` is fully deterministic — AC-1/2/5 assert exact
  numeric equality (to tolerance for floats). No nondeterminism enters the router itself.

## Next Step

→ `/implement sprint-7/phase-2-router-generator` — no infrastructure gap blocks it; honor
C-2 (router as a synthetic sweep row, not a `ModelConfig`) and the three LOW consistency
notes. Post-phase: `/update-kb rag-generation` (router/cascade pattern) after the phase-2 ADR.
