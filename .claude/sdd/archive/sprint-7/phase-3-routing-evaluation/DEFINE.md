# DEFINE: sprint-7/phase-3-routing-evaluation — Routing Evaluation & Finding

**Sprint/Phase:** sprint-7/phase-3-routing-evaluation | **Date:** 2026-06-13

## Problem Statement

Phases 1 and 2 are merged. ADR-0011 picked a **weak** inference-time escalation signal
(hybrid abstention-OR-verbalized-confidence, AUROC 0.685, ≈54% escalation) and ADR-0012
built a `RouterGenerator` behind the `Generator` Protocol with **fair combined-cost
accounting** (cheap always charged, strong charged iff escalated; the router owns the
combined `cost_usd`). Phase 3 is the harness rendering its own verdict back on the
router: sweep the router against the three single-model baselines through the eval
harness and measure **cost-per-correct-answer** (and quality-at-cost) per system, then
write an honest verdict.

The escalation economics are known going in. At ≈54% escalation the router pays the cheap
model on every query plus the strong model on more than half — so it is **expected not to
dominate** either single model on cost-per-correct (ADR-0011 §6, ADR-0012 Consequences).
A **null result** (routing does not beat the best single model on cost at equal quality)
is the **expected, valid, publishable** outcome. The deliverable is the _measured_ verdict
plus a write-up (SPRINT.md success criteria 3 and 4), not a guaranteed cost win.

## Users / Stakeholders

- **The portfolio reader (primary).** A hiring reviewer judging a _measured_ architectural
  decision. They read `docs/analysis/routing-verdict.md` and the head-to-head table and
  see the harness paying off: routing was built, swept, and judged with numbers — the
  senior signal is the rigor, not the win. Needs: a fair head-to-head (same questions,
  same retrieval, same judge across all four systems) and an honest verdict that frames a
  null result as a valid finding.
- **The eval harness (the system under test on itself).** The same `EvalRecord` schema,
  classifier, and judge that scored the three baselines now score the router row. No new
  judge, no schema change — the router is "just another system" in the combined sweep.
- **The `eval/metrics.py` consumer (future).** `compute_cost_per_correct` is a pure,
  unit-tested helper. After this phase it is the KB-documented `cost-per-correct-answer`
  concept (`/update-kb rag-eval`, Could) and the natural import point if `report.py` later
  grows a cost-per-correct column (Could) — but neither is built here.
- **`/update-kb` follow-ons (deferred, not gaps).** `rag-eval` (cost-per-correct concept)
  and `rag-generation` (router-cascade composite) writes are scheduled by the Sprint-Wide
  Knowledge Plan for **after** this phase / after ADR-0012 lands (ADR-0012 is merged, so
  the rag-generation write is now unblocked but still Could-level, not a phase-3 blocker).

## Requirements

### Functional

- **FR-1 — Combined-sweep config (`configs/routing-eval.yaml` + `.dev.yaml`).** A single
  combined run config: `models:` with the three baselines (`gpt-5-nano-2025-08-07`,
  `claude-haiku-4-5-20251001`, `gemini-2.5-flash-lite`) **plus** a `router:` block
  (`cheap_model_id: gemini-2.5-flash-lite`, `strong_model_id: claude-haiku-4-5-20251001`,
  `threshold: 1.0` — the ADR-0011 operating point). One `rag-eval run` call → **one output
  JSONL** in which all four systems answer the **same questions** with the **same
  retrieval and the same judge** (the fairness gold standard; BRAINSTORM Tension 2 Approach
  A). `prices` carries entries for the cheap, strong, and judge models. The full config
  uses `limit: null` (all 500) and the raised ceiling (FR-7); `configs/routing-eval.dev.yaml`
  uses `limit: 20` for end-to-end pipeline iteration before the full run.

- **FR-2 — Classify step on the sweep JSONL.** The sweep emits unclassified records; the
  existing `rag-classify` CLI (`make classify RESULTS_FILE=results/routing-eval.jsonl`,
  console script `enterprise_rag_ops.eval.classify_cli:main`) runs on the output to populate
  `failure_mode` (and `did_abstain_e2e`, `fact_recall`, etc.) on every record, including the
  `gen_ai.system == "router"` rows. No new classify code — the router row uses the **same
  schema, same classifier, same `FailureMode.CORRECT == "correct"` definition** as the
  baselines.

- **FR-3 — `eval/metrics.py` :: `compute_cost_per_correct(records) -> float | None`.** A
  **new** module `src/enterprise_rag_ops/eval/metrics.py` with a **pure** function over an
  iterable of already-classified `EvalRecord`. It computes:

  ```
  cost_per_correct = sum(r.generation.cost_usd for r in records)
                     / count(r for r in records if r.failure_mode == "correct")
  ```

  - **Numerator: generation cost only** (`EvalRecord.generation.cost_usd`) — the
    router-manufactured combined cost for the router rows, the single-call cost for the
    baselines. Judge cost is **excluded**: it is eval overhead, identical across systems,
    and not a deployment figure (BRAINSTORM Tension 3 Approach A).
  - **Denominator:** `count(failure_mode == "correct")` over the passed records.
  - **`None` when the denominator is 0** (zero correct answers → undefined), consistent
    with the harness `None`-on-empty-denominator convention. A `None` summand in the
    numerator is treated as `0.0`, mirroring the runner's `(x or 0.0)` convention.
  - **Caller groups by system before calling** — the helper operates on one system's
    records; per-system grouping lives in the script (FR-4). The helper does not assume a
    system field beyond what it sums.

- **FR-4 — `scripts/routing_evaluation.py` (head-to-head table).** A thin analysis script
  (mirrors the `scripts/signal_validation.py` precedent): loads the classified JSONL,
  groups records by `gen_ai.system`, calls `compute_cost_per_correct` per group, and prints
  a head-to-head table with columns **`system | cost_per_correct | fact_recall |
total_gen_cost | n_correct`**. It loads from the JSONL only — **no live API call** at
  analysis time (deterministic given the cached run).

- **FR-5 — Overlap guard (fairness assertion).** Before computing the metric,
  `routing_evaluation.py` **asserts** that every system in the JSONL shares the **same
  `question_id` set**. A mismatch raises (not warns) with a clear message. The single-run
  combined-config design (FR-1) guarantees this by construction; the assert is a
  defence-in-depth fairness guarantee — a cost-per-correct comparison across systems that
  saw different questions is not a fair comparison, so silently proceeding would undermine
  the verdict (BRAINSTORM Q3 resolved to assert).

- **FR-6 — `docs/analysis/routing-verdict.md` (the honest verdict).** A committed write-up
  in the **fixed "hypothesis → evidence → verdict" structure** matching
  `docs/analysis/over-abstention.md` / `escalation-signal-validation.md`:
  1. **Hypothesis** — does cost-aware routing beat the best single model on
     cost-per-correct at equal quality? (with the ADR-0011/0012 prior: a null result is
     expected at ≈54% escalation).
  2. **Evidence** — the FR-4 head-to-head table; the realized escalation rate on the sweep;
     the quality-at-cost positioning (fact_recall vs cost_per_correct per system);
     optionally the FR-9 scatter plot.
  3. **Verdict** — the measured answer (likely null), stated plainly, framed as a valid
     sprint result per SPRINT.md criterion 4. Tone/structure follows the two precedent
     write-ups (hook → metric landscape → reading → implications).

- **FR-7 — Cost ceiling raised to `$10.0` for the full 4-way sweep.** `routing-eval.yaml`
  sets `cost_ceiling_usd: 10.0`. The BRAINSTORM estimate for the full 500-question 4-way
  sweep is ≈$4.79 generation (Gemini $0.64 + GPT-5 Nano $0.89 + Haiku $1.70 + router
  ≈$1.56) **plus judge overhead** across all four systems; the existing `$5.0` ceiling
  (sized for 3 baselines) is tight once judge cost and the router's fourth system are added.
  `$10.0` gives ≈2× headroom over the gen estimate while still **halting a runaway** (the
  ceiling guard is the safety mechanism, not a budget target). `$15.0` was considered and
  rejected as looser than needed for a single run on a budget-conscious owner. (BRAINSTORM
  Q1 resolved → `$10.0`.)

- **FR-8 — Mirrored unit tests for `eval/metrics.py`.** `tests/eval/test_metrics.py` (mirrors
  `src/`; `tests/eval/` + `__init__.py` already exist). **Cassette-free** — the helper is
  pure arithmetic over constructed `EvalRecord` fixtures (no LLM API, so no cassette is
  required; ADR-0006 applies to LLM-touching code, which this is not). Cases: known
  records → exact `cost_per_correct`; zero-correct group → `None`; a `None`
  `generation.cost_usd` summand → treated as `0.0`; single-record and multi-record groups.

- **FR-9 — Quality-at-cost scatter plot (Should).** `routing_evaluation.py` optionally
  writes a `fact_recall` vs `cost_per_correct` scatter (one point per system) as a `.png`
  under `docs/analysis/` — the visual equivalent of the phase-1 separation plot, referenced
  from `routing-verdict.md`.

- **FR-10 — Dev-iteration discipline (Should).** Validate the full pipeline (sweep →
  classify → script → table) end-to-end on `configs/routing-eval.dev.yaml` (20 q) **before**
  the single full 500-question sweep. The full sweep runs **once** for the final numbers
  (budget-conscious owner; SPRINT.md sweep-cost risk mitigation).

### Non-functional

- **NFR-1 — Minimal blast radius.** New surface only: `configs/routing-eval.yaml` +
  `.dev.yaml`, `src/enterprise_rag_ops/eval/metrics.py`, `tests/eval/test_metrics.py`,
  `scripts/routing_evaluation.py`, `docs/analysis/routing-verdict.md` (+ optional `.png`).
  **`report.py` is unchanged. No `EvalRecord` schema change. No runner change** (the
  `router:` config plumbing shipped in phase 2). No change to any existing tested surface.

- **NFR-2 — Fair head-to-head.** The metric is only valid when all systems saw identical
  questions/retrieval/judge — guaranteed by the single combined run (FR-1) and enforced by
  the overlap assert (FR-5). Generation-cost-only numerator (FR-3) makes it a deployment-cost
  comparison, not an eval-overhead-diluted one.

- **NFR-3 — Determinism (analysis is offline).** `compute_cost_per_correct` is a pure
  function; `routing_evaluation.py` reads the cached JSONL and makes **no** live API call.
  Given a fixed input JSONL, the table and plot are deterministic. The only non-deterministic
  step is the sweep itself (real API), which is run once and cached.

- **NFR-4 — Cost ceiling honored.** The full sweep runs under `cost_ceiling_usd: 10.0`
  (FR-7); the runner's ceiling guard halts past it (boundary record still written, per the
  cost-accounting KB). The router's manufactured combined `cost_usd` is the figure the
  ceiling accumulates (ADR-0012 §3 invariant — already shipped).

- **NFR-5 — Test mirror + house structure.** `tests/eval/test_metrics.py` (no flat
  `tests/test_metrics.py`); `tests/eval/` carries `__init__.py` (exists). `make lint test`
  is the gate. The analysis script lives in `scripts/` (the `signal_validation.py`
  precedent — a one-off investigation tool, not production package surface).

- **NFR-6 — `None`-convention consistency.** `cost_per_correct` is `None` (rendered "N/A")
  when a system has zero correct answers, matching the harness-wide `None`-on-missing /
  `None`-on-empty-denominator convention (`compute_cost_usd`, report propagation).

## Acceptance Criteria

Offline-checkable except AC-1 (the single full sweep is the real, capped deliverable).
The metric/script/assert ACs need no network — they run on constructed `EvalRecord`
fixtures or the cached sweep JSONL.

1. **AC-1 — Combined sweep produces one JSONL with all four systems on the same questions,
   under the ceiling.** `RunConfig.load_from_yaml("configs/routing-eval.yaml")` parses
   (3 baseline `models:` + a `router:` block, `threshold == 1.0`, `cost_ceiling_usd ==
10.0`, `limit is None`, `prices` has cheap/strong/judge entries). Running it emits a
   single JSONL with `gen_ai.system` values `{gpt-5-nano…, claude-haiku…, gemini…,
"router"}`, each covering the same `question_id` set; total cost ≤ $10. `routing-eval.dev.yaml`
   parses with `limit == 20` for iteration. (Checked: config parse asserts offline; the
   run is the capped deliverable, verified by row counts per system + cost log.)

2. **AC-2 — Classify populates `failure_mode` on every row, router included.** After
   `make classify RESULTS_FILE=results/routing-eval.jsonl`, every record (including the
   `system == "router"` rows) has a non-`None` `failure_mode`, and `correct` is exactly
   `failure_mode == "correct"`. (Checked: no `None` `failure_mode` in the classified JSONL;
   router rows classified by the same cascade as baselines.)

3. **AC-3 — `compute_cost_per_correct` is correct and pure.** Given a list of constructed
   `EvalRecord` with known `generation.cost_usd` and `failure_mode`, the function returns
   `sum(gen_cost) / count(failure_mode == "correct")`, using **generation cost only**
   (judge cost on the record is ignored). (Checked: exact equality on a hand-computed
   fixture in `tests/eval/test_metrics.py`.)

4. **AC-4 — Zero-correct → `None`.** A record group with no `failure_mode == "correct"`
   returns `None` (not `0`, not a divide-by-zero error). (Checked: fixture asserts `None`.)

5. **AC-5 — `None` cost summand treated as `0.0`.** A group containing a record with
   `generation.cost_usd is None` does not crash; that summand contributes `0.0` to the
   numerator. (Checked: mixed `None`/float fixture.)

6. **AC-6 — Head-to-head table renders all four systems.** `scripts/routing_evaluation.py`
   on the classified JSONL prints a table with one row per `gen_ai.system` and columns
   `system | cost_per_correct | fact_recall | total_gen_cost | n_correct`. (Checked: table
   has four rows; values match the per-group helper output; `cost_per_correct` shows "N/A"
   for any zero-correct system.)

7. **AC-7 — Overlap guard asserts, not warns.** Given a JSONL where two systems have
   **different** `question_id` sets, `routing_evaluation.py` **raises** with a message
   naming the mismatch (it does not silently compute). Given a JSONL where all systems share
   the same set, it proceeds. (Checked: a mismatched fixture raises; a matched one passes.)

8. **AC-8 — `routing-verdict.md` is the structured honest verdict.** `docs/analysis/routing-verdict.md`
   exists and is organized **hypothesis → evidence → verdict**: it states the hypothesis
   (routing beats the best single model on cost-per-correct at equal quality), presents the
   head-to-head table + realized escalation rate as evidence, and states the measured
   verdict — framing a null result as a valid sprint outcome (SPRINT.md criterion 4).
   (Checked: the three sections present; the table embedded; the verdict explicit.)

9. **AC-9 — Quality-at-cost scatter (Should).** If FR-9 is built, a `fact_recall` vs
   `cost_per_correct` `.png` (one point per system) is committed under `docs/analysis/` and
   referenced from `routing-verdict.md`. (Checked: artifact present + referenced — Should,
   not Must.)

10. **AC-10 — Dev-pipeline validated before the full run (Should).** The full pipeline
    (sweep → classify → script → table) is run on `routing-eval.dev.yaml` (20 q) and prints
    a four-row table before the single 500-q sweep. (Checked: dev run produces a table;
    documentation/recipe notes the dev-first discipline.)

11. **AC-11 — `make lint test` green; metric tests are cassette-free.** Lint and the full
    suite pass, including `tests/eval/test_metrics.py`; no existing test regresses. The
    metric tests use constructed `EvalRecord` fixtures and **no** LLM API / no cassette
    (the helper is pure arithmetic — ADR-0006 does not apply). Tests mirror `src/`
    (`tests/eval/test_metrics.py`, no flat file).

> Test layout (convention): `tests/eval/test_metrics.py` — `tests/eval/` + its
> `__init__.py` already exist; no flat `tests/test_metrics.py`.

## Resolved Open Questions

`AskUserQuestion` is unavailable to this subagent. The BRAINSTORM's five open questions are
resolved below from the read context to BRAINSTORM/SPRINT/ADR-aligned defaults and encoded
as fixed requirements. None changes the MUST surface or requires orchestrator confirmation
before `/design`; OQ-1 (the ceiling number) is the only judgment call flagged as an
**unconfirmed assumption** for a quick skim, since it is a spend figure.

- **OQ-1 (BRAINSTORM Q1) Cost ceiling for the full 4-way sweep → `$10.0`.** The BRAINSTORM
  estimate is ≈$4.79 generation + judge overhead across four systems; `$5.0` (sized for 3
  baselines) is tight. `$10.0` gives ≈2× headroom over the gen estimate while still halting
  a runaway; `$15.0` is looser than a single budget-conscious run needs. Encoded as FR-7 /
  AC-1. _Unconfirmed assumption — low risk (a ceiling is a safety halt, not a budget; the
  expected actual spend is well under it); flagged for an orchestrator skim because it is a
  dollar figure._

- **OQ-2 (BRAINSTORM Q2) Where the classify step sits → reuse the existing `make classify`
  target via a README/recipe; no new `make routing-eval` target.** The Makefile already has
  `eval-baseline` (`rag-eval run --config …`) and `classify` (`rag-classify --results
$(RESULTS_FILE)`, with a `RESULTS_FILE ?=` override). The sweep→classify→analysis chain is
  three existing invocations (`rag-eval run --config configs/routing-eval.yaml` →
  `make classify RESULTS_FILE=results/routing-eval.jsonl` → `uv run python
scripts/routing_evaluation.py`). A new `make routing-eval` target would only re-wrap
  existing targets for a **one-off** sweep — not warranted; the lighter README-level recipe
  matches repo precedent (the `scripts/signal_validation.py` phase-1 flow is documented, not
  Makefile-targeted). Encoded as FR-2. _Resolved to the lighter option per the brief; no
  new Makefile surface._

- **OQ-3 (BRAINSTORM Q3) Overlap guard — assert vs warn → assert.** The cost-per-correct
  head-to-head is only a **fair** comparison if all systems saw the same questions. The
  combined-config single run guarantees this by construction, but a downstream re-run on a
  hand-edited or partial JSONL could violate it silently. An assert (raise) is the safer
  choice for a fairness claim that the verdict write-up rests on. Encoded as FR-5 / AC-7.
  _Resolved: assert._

- **OQ-4 (BRAINSTORM Q4) Router "correct" definition → `failure_mode == "correct"` is the
  Must path; the correct-via-cheap vs correct-via-escalation split is Could.** The router
  row carries the same `EvalRecord` schema and is classified by the same cascade as the
  baselines, so `failure_mode == "correct"` is the right and sufficient correctness gate for
  the Must head-to-head. A richer split (which correct answers came from the cheap path vs
  the escalated path) would make the write-up more interesting but requires deriving the
  escalation decision per record (not a field on `EvalRecord` today) — Could-level, deferred,
  not required for criteria 3/4. _Confirmed: Must uses the existing label; split is Could._

- **OQ-5 (BRAINSTORM Q5) Verdict write-up structure → fixed "hypothesis → evidence →
  verdict".** Matching `over-abstention.md` / `escalation-signal-validation.md` gives a
  consistent, skimmable portfolio artifact and forces the honest-null framing into a named
  "verdict" section. Encoded as FR-6 / AC-8. _Resolved: structured form._

## Infrastructure Readiness

Both KB domains exist and the BRAINSTORM coverage table rates them **Sufficient** for this
phase — confirmed below (not re-derived). No new KB, agent, command, or `--deep-research`
blocks phase 3.

| Dependency                                                                                  | Type   | KB domain                                                    | Specialist           | Status                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `RunConfig.router` + `RouterConfig` + `models:` combined config                             | config | rag-eval (`multi-model-runner`)                              | (multi-model-runner) | **Ready** — shipped phase 2 (ADR-0012); the runner sweeps the router as a synthetic row alongside `models:`. A combined config is a config-only artifact.                                  |
| `RouterGenerator` + fair combined `cost_usd` on `EvalRecord.generation`                     | module | rag-generation (router-cascade) + rag-eval (cost-accounting) | —                    | **Ready** — shipped phase 2; cost-accounting.md documents the combined-cost owner + the runner cost-guard invariant; router row carries the manufactured combined `cost_usd`.              |
| `rag-classify` CLI (`classify_cli:main`) + `make classify`                                  | CLI    | rag-eval (`failure-taxonomy`)                                | —                    | **Ready** — console script + Makefile target with `RESULTS_FILE` override exist; classifies the router row by the same cascade (`FailureMode.CORRECT == "correct"`).                       |
| `EvalRecord` schema (`generation.cost_usd`, `failure_mode`, `gen_ai.system`, `question_id`) | data   | rag-eval (`eval-record-schema`)                              | —                    | **Ready** — `system`/`model` are `str` (`"router"` needs no schema change); `generation.cost_usd` is the per-record gen cost; no schema change this phase.                                 |
| `eval/metrics.py` (new) `compute_cost_per_correct`                                          | module | rag-eval (`cost-accounting` → forward-ref)                   | —                    | **New, ready to build** — cost-accounting.md explicitly forward-references cost-per-correct as out-of-scope-until-phase-3; pure arithmetic over classified records, no new dependency.     |
| `scripts/routing_evaluation.py` (new)                                                       | script | rag-eval                                                     | —                    | **New, ready to build** — mirrors the `scripts/signal_validation.py` phase-1 precedent (load JSONL → compute → print/plot); pandas/matplotlib already present from phase-1 tooling.        |
| Cassette/replay testing (ADR-0006)                                                          | tests  | rag-eval (`cassette-replay`)                                 | —                    | **N/A for the metric** — `eval/metrics.py` is pure arithmetic over constructed records (no LLM API), so unit tests are cassette-free. The single sweep is a real (capped) run, not a test. |
| `/update-kb rag-eval` (cost-per-correct concept)                                            | KB     | rag-eval                                                     | kb-architect         | **Deferred (not a gap)** — Sprint-Wide Knowledge Plan schedules this for **when the metric stabilizes (≈ phase 3 end)**; Could-level follow-on, not a phase-3 blocker.                     |
| `/update-kb rag-generation` (router-cascade composite)                                      | KB     | rag-generation                                               | kb-architect         | **Deferred (not a gap)** — scheduled post-ADR-0012; ADR-0012 is now merged so it is unblocked, but it remains a Could-level follow-on, not a phase-3 blocker.                              |

**No new KB, agent, command, or `--deep-research` needed for phase 3.** Cost-per-correct is
standard arithmetic (cost ÷ count*correct); the reporting shape (head-to-head table +
optional Pareto scatter) follows the phase-1 `scripts/signal_validation.py` precedent. Both
`rag-eval` and `rag-generation` exist and are Sufficient. The two `/update-kb` writes are
the natural \_follow-on* once the metric stabilizes, scheduled by the sprint plan — not
blockers.

## Out of Scope (Won't — Phase 3)

Inherited from the BRAINSTORM MoSCoW Won't list:

- **Threshold sweep over escalation thresholds** — one operating point (`threshold: 1.0`),
  measure, stop (SPRINT.md explicit Won't; the signal is bimodal so a sweep is degenerate).
- **A new ADR for the routing evaluation** — ADR-0011 §6 and ADR-0012 cover the design; the
  verdict is a _finding_, not a decision.
- **Multi-threshold Pareto frontier** — deferred to backlog if ever needed.
- **Leaderboard submission** — already deferred to backlog B-09.
- **Re-running any prior baseline JSONL separately and joining by `question_id`** — the
  combined-config single-run is the only fair path (BRAINSTORM Tension 2 Approach A); a
  post-hoc join is rejected.
- **Extending `report.py` with a cost-per-correct column** — Could; deferred unless the
  sprint has room. `report.py` is unchanged this phase (NFR-1).
- **Correct-via-cheap vs correct-via-escalation split** — Could (OQ-4); the Must path uses
  `failure_mode == "correct"`.

## Clarity Score

| Dimension       | Score | Note                                                                                                                                                                                                                                                                                                                 |
| --------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**     | 3     | Root cause with evidence: a weak signal (AUROC 0.685, ≈54% escalation, ADR-0011/0012) means routing is _expected not to dominate_ on cost-per-correct; the deliverable is the measured verdict. The cost math (gen-only numerator, count-correct denominator, `None` on zero) is anchored in the cost-accounting KB. |
| **Users**       | 3     | Named roles + workflow impact: the portfolio reader (judges a measured decision), the eval harness scoring the router on its own schema, the future `eval/metrics.py`/`report.py` consumer, the deferred `/update-kb` follow-ons.                                                                                    |
| **Success**     | 3     | 11 measurable, falsifiable ACs: capped four-system sweep on the same questions, classify-populates-router-row, exact cost-per-correct arithmetic (incl. zero-correct→`None` and `None`-summand), four-row head-to-head table, overlap-assert-not-warn, structured verdict, dev-first discipline, `make lint test`.   |
| **Scope**       | 3     | MoSCoW inherited from the BRAINSTORM with an explicit Won't list (threshold sweep, new ADR, separate-run join, Pareto frontier, leaderboard, report.py change, correct-path split). All five open questions resolved to fixed requirements.                                                                          |
| **Constraints** | 3     | All named: minimal blast radius (report.py + schema + runner unchanged), gen-cost-only numerator, fairness via single run + overlap assert, `$10` ceiling, `None`-convention, cassette-free pure-metric tests (ADR-0006 N/A), test mirror, budget-conscious dev-first-then-one-full-run.                             |

**Total: 15/15 — PASS (≥12).** The five BRAINSTORM open questions all resolved from the read
context to BRAINSTORM/SPRINT/ADR-aligned defaults with no blocking ambiguity. OQ-1 (the
`$10` ceiling) is the single unconfirmed assumption flagged for an orchestrator skim — a
low-risk safety figure, not a budget commitment. No `AskUserQuestion` was needed.

## Next Step

→ `/design sprint-7/phase-3-routing-evaluation`
