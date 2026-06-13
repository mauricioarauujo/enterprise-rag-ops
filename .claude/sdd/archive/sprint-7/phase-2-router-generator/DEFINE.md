# DEFINE: sprint-7/phase-2-router-generator — RouterGenerator

**Sprint/Phase:** sprint-7/phase-2-router-generator | **Date:** 2026-06-04

## Problem Statement

Phase 1 validated a weak inference-time escalation signal (hybrid abstention-OR-verbalized-
confidence, AUROC 0.685, ~54% escalation rate) and wired it onto `CallStats.confidence_score`
(ADR-0011). Phase 2 builds the `RouterGenerator` that consumes that signal: answer with the
cheap `gemini-2.5-flash-lite` by default, escalate to `claude-haiku-4-5` when the cheap answer
is not trustworthy, and expose it as a system-under-test for the phase-3 sweep.

The build is **user-ratified** (Open Question 1 resolved: build, do not rescope). The
deliverable's value is the _measured verdict_, not a guaranteed cost win. At ~54% escalation
the router calls the cheap model twice as often as a cheap baseline and the strong model half
as often as a strong baseline, so phase-3 is expected to show it dominates neither single model
on cost-per-correct-answer. A null phase-3 result is the honest, publishable baseline ADR-0011
§6 anticipates. Phase 2's job is to build the router correctly — with fair combined-cost
accounting — so phase-3 can render that verdict on the same `EvalRecord` schema as the
baselines.

## Requirements

### Functional

- **FR-1 — `RouterGenerator` class.** New module `src/enterprise_rag_ops/generation/router_generator.py`
  defining `RouterGenerator`, a `Generator`-Protocol-compatible composite. It is constructed
  by **composition/injection** (Approach B): it holds two injected `Generator` instances
  (`cheap`, `strong`), the escalation `threshold: float`, and the price table
  (`prices: dict[str, Price]`) plus the two model ids needed to look prices up. No factory
  lookup inside the class.

- **FR-2 — `generate_with_stats`.** `RouterGenerator.generate_with_stats(context_chunks, question)`
  returns `tuple[AnswerWithSources, CallStats, RawCall]` (the same 3-tuple shape as every
  sub-generator). It: (a) calls `cheap.generate_with_stats(...)`, (b) applies the escalation
  rule (FR-4), (c) calls `strong.generate_with_stats(...)` only when escalating, (d) returns
  the strong answer when escalated else the cheap answer, with the manufactured combined
  `CallStats` (FR-5) and `gen_raw` (FR-7).

- **FR-3 — `generate`.** `RouterGenerator.generate(context_chunks, question)` delegates to
  `generate_with_stats` and returns the **bare `AnswerWithSources`** (the cheap-or-strong
  answer), discarding stats/raw — exactly mirroring the existing generators' `generate`
  delegation. This is what makes `RouterGenerator` a structural `Generator` (duck-typed; no
  change to `interfaces.py`).

- **FR-4 — Escalation rule (ADR-0011 §5).** Read `confidence_score` off the cheap call's
  `CallStats` and the abstention sentinel off the cheap `AnswerWithSources.answer`. Escalate
  when **`confidence_score is None OR confidence_score < threshold OR cheap_answer.answer ==
ABSTAIN_ANSWER`** — equivalently, _do not_ escalate only when `confidence_score == threshold`
  AND the cheap model did not abstain. `ABSTAIN_ANSWER` is imported from
  `generation/schema.py` (the SSoT sentinel). `threshold` defaults to `1.0` (the ADR-0011
  operating point). No threshold sweep (Won't — phase-3/out).

- **FR-5 — Combined-cost `CallStats` manufacture (Option B-1, the design crux).** The router
  is the single owner of combined cost — it is the only site that holds both sub-`CallStats`
  and the price table at once. It computes `cheap_cost = compute_cost_usd(cheap_stats,
prices.get(cheap_model_id))` **always**, and `strong_cost = compute_cost_usd(strong_stats,
prices.get(strong_model_id))` **only when escalated**. It manufactures one output `CallStats`:
  - `model = "router"`, `system = "router"`
  - `input_tokens  = cheap_in  + (strong_in  if escalated else 0)`
  - `output_tokens = cheap_out + (strong_out if escalated else 0)`
  - `latency_s     = cheap_lat + (strong_lat if escalated else 0)`
  - `cost_usd      = cheap_cost + (strong_cost if escalated else 0)` (with `None` summands
    treated as `0.0`, mirroring the runner's `(x or 0.0)` convention)
  - `confidence_score = cheap_stats.confidence_score`
    This enforces the #1 research-fairness rule (Bouchard 2026 Q6): the cheap call is **always**
    charged on an escalated query, never dropped.

- **FR-6 — `RouterConfig` + `RunConfig.router`.** Add `RouterConfig(BaseModel)` to
  `eval/config.py` with `cheap_model_id: str`, `strong_model_id: str`, `threshold: float = 1.0`.
  Add an optional top-level field `router: RouterConfig | None = None` to `RunConfig`.
  `ModelConfig.system` `Literal` and `_GENERATOR_FACTORY` stay **unchanged** (no discriminated
  union, no new `Literal` member).

- **FR-7 — `gen_raw` for the bronze path.** The router returns the **cheap call's `RawCall`**
  as `gen_raw` (the cheap call is always made). Strong-model raw payloads are **not**
  bronze-written in this phase (phase-3 works from the JSONL records). A composite/strong raw
  write is Could-level, deferred.

- **FR-8 — Runner wiring: construct the router.** In `eval/runner.py`, when `config.router is
not None`, construct `RouterGenerator(cheap=GeminiGenerator(model=router.cheap_model_id),
strong=AnthropicGenerator(model=router.strong_model_id), threshold=router.threshold,
prices=config.prices, cheap_model_id=..., strong_model_id=...)` and append it to the swept
  systems as a pseudo-model row. The cheap/strong sub-generators are the existing concrete
  generators (no factory change).

- **FR-9 — Runner wiring: cost-accounting guard (backwards-compatible).** Replace the
  unconditional `gen_stats.cost_usd = compute_cost_usd(gen_stats, gen_price)` (runner.py:200-201)
  with a guard: **`if gen_stats.cost_usd is None: gen_stats.cost_usd = compute_cost_usd(...)`**.
  When the router has already set `cost_usd` (FR-5), the runner treats it as final and skips
  re-computation. Backwards-compat note: today **no generator pre-sets `cost_usd`** (all return
  `None` and the runner fills it), and the existing retrieval-abstain branch already sets
  `cost_usd=0.0` then would be re-computed — the guard preserves both behaviours. The guard is a
  seam extension, not a router-specific branch.

- **FR-10 — Runner wiring: synthesized router `gen_ai` identity.** For the router row, the
  runner synthesizes the `EvalRecord.gen_ai` identity with `system = "router"` and
  `GenAiRequest.model = "router"`. No schema change is needed: `GenAiFields.system` and
  `GenAiRequest.model` are both `str` (verified, `eval/records.py` — not a `Literal`). A
  descriptive composite model string (`"gemini-2.5-flash-lite+claude-haiku-4-5"`) in
  `gen_ai.request.model` is a Could, not required.

- **FR-11 — Router eval config `configs/router.yaml`.** Cheap `gemini-2.5-flash-lite`, strong
  `claude-haiku-4-5-20251001`, `threshold: 1.0`, OpenAI judge (`gpt-5-nano-2025-08-07`),
  `cost_ceiling_usd: 5.0`, dev-safe `limit: 20`, and a `prices` table carrying entries for the
  cheap model, the strong model, and the judge model (all three are needed for cost accounting).

- **FR-12 — Mirrored tests.** `tests/generation/test_router_generator.py` (mirrors `src/`; the
  `tests/generation/` package + `__init__.py` already exist). Uses the cassette/replay or
  fake-sub-generator approach — **no mocked LLM API** (ADR-0006). Because the router composes
  two `Generator` instances, the test injects **two fake/cassetted sub-generators** (this is
  new — prior generator tests faked a single SDK client; the composite is cleaner because it
  injects `Generator`-shaped doubles, not provider SDK doubles).

### Non-functional

- **NFR-1 — Public Protocol byte-for-byte unchanged.** `generation/interfaces.py` (`Generator`
  Protocol = `generate(context_chunks, question) -> AnswerWithSources`) is not edited
  (SPRINT.md criterion 1; ADR-0011 §3). `RouterGenerator` conforms structurally via `generate`.

- **NFR-2 — Combined-cost correctness (fairness).** The cheap call's cost is always included on
  an escalated query; the strong cost is included **iff** escalated. Token/latency fields sum
  the same way. This is the research-fairness invariant (no double-counting, no dropped cheap
  call) — directly testable.

- **NFR-3 — Cassette/replay testing, no mocked LLM API.** Router tests follow ADR-0006: inject
  fake/cassetted sub-generators; never `unittest.mock` the LLM SDK or the `Generator`.

- **NFR-4 — Runner cost-guard backwards-compatibility.** The `if gen_stats.cost_usd is None`
  guard must not change cost figures for any existing single-model config (all current
  generators return `cost_usd=None`, so the guard's body runs exactly as before).

- **NFR-5 — Cost ceiling honored.** Because the router sets the true combined `cost_usd` before
  the runner's ceiling accumulation, the runner's `cost_ceiling_usd` guard tracks the real
  router cost (cheap+strong), not a mis-attributed cheap-only figure (this is _why_ B-3 was
  rejected).

- **NFR-6 — Determinism where testable.** Given fixed fake sub-generator outputs (fixed
  answer, confidence, token counts) and a fixed price table, the manufactured `CallStats`
  (combined cost, tokens, escalation decision) is deterministic and exactly asserted.

- **NFR-7 — Minimal blast radius.** `ModelConfig`, `_GENERATOR_FACTORY`, the three concrete
  generators, and every prior `results/*.jsonl` are untouched. Removing the router later is one
  field deletion on `RunConfig` plus the runner branch.

## Acceptance Criteria

1. **AC-1 (no-escalation path).** Given a cheap sub-generator returning `confidence_score == 1.0`
   and a non-abstaining answer, `generate_with_stats` does **not** call the strong sub-generator;
   the returned answer is the cheap answer; combined `cost_usd == cheap_cost` and tokens/latency
   equal the cheap call's. (Assert the strong fake recorded zero calls.)

2. **AC-2 (escalation on low confidence).** Given a cheap call with `confidence_score < threshold`
   (e.g. `0.0`), the strong sub-generator **is** called; the returned answer is the strong answer;
   `cost_usd == cheap_cost + strong_cost`; tokens/latency are the summed totals.

3. **AC-3 (escalation on abstention).** Given a cheap call whose answer `== ABSTAIN_ANSWER`
   (even if `confidence_score == 1.0`), the router escalates and the strong sub-generator is
   called. Confirms abstention is an OR-trigger independent of confidence.

4. **AC-4 (escalation on missing confidence).** Given a cheap call with `confidence_score is
None`, the router escalates (a non-Gemini cheap generator, or a parse miss, must not silently
   pass through).

5. **AC-5 (combined-cost arithmetic).** With a known price table and known cheap/strong token
   counts, the manufactured `cost_usd` equals `compute_cost_usd(cheap_stats, cheap_price) +
compute_cost_usd(strong_stats, strong_price)` on the escalated path, and exactly
   `compute_cost_usd(cheap_stats, cheap_price)` on the non-escalated path (assert to a numeric
   tolerance). `confidence_score` on the output equals the cheap call's.

6. **AC-6 (`generate` contract).** `RouterGenerator.generate(...)` returns a bare
   `AnswerWithSources` (not a tuple), equal to the cheap-or-strong answer that
   `generate_with_stats` would return for the same inputs.

7. **AC-7 (public Protocol unchanged).** `generation/interfaces.py` is unmodified in the diff,
   and `isinstance(RouterGenerator(...), Generator)` holds under the `@runtime_checkable`
   `Generator` Protocol (structural conformance via `generate`).

8. **AC-8 (`RouterConfig` + `RunConfig.router`).** `RouterConfig` validates
   `{cheap_model_id, strong_model_id, threshold}` with `threshold` defaulting to `1.0`;
   `RunConfig.load_from_yaml` parses a YAML with a top-level `router:` block into
   `RunConfig.router`, and a YAML without it leaves `router is None` (backwards-compatible).

9. **AC-9 (router row in the sweep JSONL).** Running the sweep with `config.router` set produces
   `EvalRecord` rows whose `gen_ai.system == "router"` and `gen_ai.request.model == "router"`,
   with `generation.cost_usd` equal to the router-manufactured combined cost (the runner's
   guard did **not** overwrite it).

10. **AC-10 (runner guard backwards-compat).** For a single-model (non-router) config, the
    runner still computes `generation.cost_usd` exactly as before (regression: an existing
    baseline config's per-record gen cost is unchanged by the guard).

11. **AC-11 (no mocked LLM).** `tests/generation/test_router_generator.py` contains no
    `unittest.mock`/`MagicMock` of an LLM SDK or `Generator`; it injects fake/cassetted
    sub-generators (two of them) per ADR-0006.

12. **AC-12 (`configs/router.yaml` valid + dev smoke).** `RunConfig.load_from_yaml("configs/router.yaml")`
    parses without error, `router.threshold == 1.0`, `cost_ceiling_usd == 5.0`, `limit == 20`,
    and the `prices` table contains entries for cheap, strong, and judge models. A
    `configs/router.dev.yaml` (5 questions, no ceiling) parses for rapid iteration (Should).

13. **AC-13 (`make lint test` green).** Lint and the full test suite pass, including the new
    router tests; no existing test regresses.

> Test layout (convention): `tests/generation/test_router_generator.py` — the `tests/generation/`
> package and its `__init__.py` already exist; no flat `tests/test_router_generator.py`.

## Resolved Open Questions

`AskUserQuestion` was not invoked: the six load-bearing decisions were pre-resolved and ratified
by the orchestrator (build confirmed; Approach B; combined cost = B-1; ADR-0011 escalation rule;
`system="router"`/`model="router"` identity; cheap `RawCall` as `gen_raw`). They are encoded as
fixed requirements above, not re-asked. The remaining BRAINSTORM open questions map as follows:

- **OQ-1 (build vs. rescope)** → resolved: **build** (problem statement; ratified). Null phase-3
  is a valid deliverable.
- **OQ-2 (CallStats model/system identity)** → resolved: `model = "router"`, `system = "router"`;
  composite string is a Could (FR-10).
- **OQ-3 (runner cost-guard scope)** → resolved: backwards-compatible `if cost_usd is None`
  guard, a general seam extension, not a router-only branch (FR-9, NFR-4).
- **OQ-4 (threshold float vs. hardcoded)** → resolved: `threshold: float = 1.0` config knob,
  exposed in `configs/router.yaml`; **no** sweep (Won't).
- **OQ-5 (`gen_raw` bronze)** → resolved: cheap `RawCall` only; strong raw not persisted (FR-7).

No new blocking ambiguity surfaced; nothing requires orchestrator confirmation before `/design`.

## Clarity Score

| Dimension       | Score | Note                                                                                                                                        |
| --------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**     | 3     | Root cause with evidence: weak signal (AUROC 0.685, ~54% escalation, ADR-0011); the value is the measured verdict, framed plainly.          |
| **Users**       | 2     | Named consumers (phase-3 sweep, the eval harness, the portfolio reader judging a measured decision) with workflow impact; no live end-user. |
| **Success**     | 3     | 13 measurable, falsifiable ACs — escalation paths, combined-cost arithmetic, Protocol-unchanged, JSONL row, guard backwards-compat.         |
| **Scope**       | 3     | MoSCoW with an explicit Won't list (threshold sweep, Protocol change, self-consistency, new metrics, dashboard) inherited from BRAINSTORM.  |
| **Constraints** | 3     | All named: Protocol byte-for-byte unchanged, ADR-0006 cassette/no-mock, cost ceiling, B-1 cost ownership, backwards-compat guard, budget.   |

**Total: 14/15 — PASS (≥12).**

## Infrastructure Readiness

| Dependency                                              | KB domain                     | Specialist           | Status                                                                                                  |
| ------------------------------------------------------- | ----------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `RouterConfig` / `RunConfig.router` (config.py)         | rag-eval                      | (multi-model-runner) | Ready — `RunConfig` shape + `load_from_yaml` exist; additive optional field, no churn.                  |
| Cheap sub-generator (`GeminiGenerator`)                 | rag-generation                | —                    | Ready — verbalized confidence on `CallStats.confidence_score` shipped phase-1 (ADR-0011).               |
| Strong sub-generator (`AnthropicGenerator`)             | rag-generation                | —                    | Ready — `generate_with_stats` returns the 3-tuple; default `claude-haiku-4-5-20251001`.                 |
| `CallStats` / `compute_cost_usd` / `Price`              | rag-eval (cost-accounting)    | —                    | Ready — `compute_cost_usd(stats, price)` + `cost_usd: float                                             | None` precedent confirmed in source. |
| `ABSTAIN_ANSWER` sentinel (schema.py)                   | rag-generation                | —                    | Ready — single SSoT sentinel; imported by the router for the OR-trigger.                                |
| `EvalRecord.gen_ai` identity (records.py)               | rag-eval (eval-record-schema) | —                    | Ready — `system` and `request.model` are both `str` (not `Literal`); `"router"` needs no schema change. |
| Cassette/replay testing (ADR-0006)                      | rag-eval (cassette-replay)    | —                    | Ready — pattern established; router needs two sub-generator doubles (new shape, same discipline).       |
| `confidence_score` field (phase-1)                      | rag-eval / rag-generation     | —                    | Ready — live on `CallStats`, populated by the Gemini path only.                                         |
| Runner wiring + cost guard (runner.py:200-201)          | rag-eval (multi-model-runner) | (multi-model-runner) | Ready — guard is a 2-line surgical change; abstain branch already pre-sets `cost_usd`.                  |
| Router/cascade KB pattern (`/update-kb rag-generation`) | rag-generation                | kb-architect         | **Deferred — not a gap.** SPRINT.md Knowledge Plan defers this to **after** the phase-2 ADR.            |

**No new KB or agent blocks this phase.** The router/cascade `Generator`-composite pattern is
intentionally scheduled for `/update-kb rag-generation` _after_ the phase-2 ADR lands (sprint-wide
plan item), and the cost-per-correct-answer metric for `/update-kb rag-eval` post-phase-3. Neither
is a blocker now.

## Next Step

→ `/design sprint-7/phase-2-router-generator`
