# DESIGN: sprint-7/phase-3-routing-evaluation — Routing Evaluation & Finding

**Sprint/Phase:** sprint-7/phase-3-routing-evaluation | **Date:** 2026-06-13

## Architecture

Phase 3 turns the eval harness back on the router it built in phase 2. It adds **no new
production surface in `src/eval` or `src/generation` beyond one pure helper** — the
sweep, classify, and judge plumbing all shipped already. The phase is: one combined
config → the existing `rag-eval run` (which already emits the router as a synthetic row
alongside the baselines, verified below) → the existing `rag-classify` → one new pure
metric helper → one thin analysis script → an honest write-up.

### Data flow

```
configs/routing-eval.yaml  (3 baselines under models: + a router: block;
   limit: null, cost_ceiling_usd: 10.0, prices for cheap/strong/judge)
        │
        │  uv run rag-eval run --config configs/routing-eval.yaml
        ▼
eval/runner.py  run_evaluation()                       (UNCHANGED — phase-2 code)
   sweep_units = [gpt-5-nano, claude-haiku, gemini-flash-lite]      (config.models)
                 + ("router","router", RouterGenerator(...))        (config.router, FR-8)
   → ONE output JSONL: results/routing-eval.jsonl                   (single output_path)
        │   every row carries generation.cost_usd already final
        │   (baselines: runner cost-guard; router: manufactured combined cost, ADR-0012)
        ▼
make classify RESULTS_FILE=results/routing-eval.jsonl  (rag-classify, UNCHANGED — FR-2)
   → populates failure_mode / fact_recall / did_abstain_e2e on EVERY row,
     including gen_ai.system == "router" (same cascade, FailureMode.CORRECT == "correct")
        │
        ▼
scripts/routing_evaluation.py  (NEW, FR-4/FR-5/FR-9 — pure pandas/json, NO live API)
   1. load classified results/routing-eval.jsonl
   2. OVERLAP ASSERT (FR-5): every gen_ai.system shares the same question_id set → raise on mismatch
   3. group rows by gen_ai.system
   4. per group → eval.metrics.compute_cost_per_correct(group_records)   (NEW helper, FR-3)
   5. print head-to-head table: system | cost_per_correct | fact_recall | total_gen_cost | n_correct
   6. (Should, FR-9) write docs/analysis/routing-cost-quality.png scatter (fact_recall vs cost_per_correct)
        │
        ▼
src/enterprise_rag_ops/eval/metrics.py  (NEW, FR-3 — pure)
   compute_cost_per_correct(records) -> float | None
     = sum(r.generation.cost_usd or 0.0 for r in records)        # gen cost only; judge excluded
       / count(r for r in records if r.failure_mode == "correct")
     None when denominator == 0
        │
        ▼
docs/analysis/routing-verdict.md  (NEW, FR-6 — hypothesis → evidence → verdict)
   + docs/analysis/routing-cost-quality.png  (Should)
```

### The fairness crux (verified against real code)

The entire fairness argument (FR-5 / NFR-2 — same questions, same retrieval, same judge,
same JSONL) rests on the phase-2 runner emitting the router **and** the baselines in one
sweep. **Confirmed in `eval/runner.py`:** `run_evaluation` builds a single
`sweep_units: list[_SweepUnit]` — one unit per `config.models` entry (runner.py:156-162)
**plus** a synthetic `_SweepUnit("router", "router", RouterGenerator(...))` appended when
`config.router is not None` (runner.py:168-190) — then iterates all units writing into one
`output_path = output_dir / f"{config.run_id}.jsonl"` (runner.py:137, 193-194). All four
systems therefore answer the same `load_questions(limit=config.limit)` set (runner.py:151),
through the same single `retriever` (runner.py:127), scored by the same judge
(runner.py:201), in **one JSONL**. The combined-config single-run path AC-1 assumes is
exactly how the shipped runner works — **no gap, no separate router invocation needed.**

### Why the metric helper, not a `report.py` change

`report.py` is unchanged (NFR-1). The cost-per-correct figure is a research finding for
this sprint's verdict, not a standing report column; wiring it into `report.py` would
inject a classify-step dependency into the baseline report pipeline (BRAINSTORM Tension 1
Approach C rationale). The pure helper in `eval/metrics.py` keeps the logic unit-tested
and reusable (the planned `/update-kb rag-eval` cost-per-correct concept and a future
`report.py` import point), while the script stays thin — mirroring the phase-1
`scripts/signal_validation.py` precedent (load JSONL → compute → print/plot, no live API).

## File Manifest

Prescriptive — an Antigravity/Gemini executor needs no extra context. All `direct`: no
specialist agent owns `src/eval` or `src/generation` (all existing agents are workflow
agents with `kb_domains: []`); phases 1 and 2 both shipped `direct`. No specialist is
warranted for one pure helper + one script + configs + a doc.

| File                                     | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Owner (agent / direct) | Phase order      |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------- | ---------------- |
| `configs/routing-eval.yaml`              | **New.** Combined sweep. `models:` = the three baselines (`gpt-5-nano-2025-08-07`/openai, `claude-haiku-4-5-20251001`/anthropic, `gemini-2.5-flash-lite`/google — copy from `baseline.yaml`). `router:` block (`cheap_model_id: gemini-2.5-flash-lite`, `strong_model_id: claude-haiku-4-5-20251001`, `threshold: 1.0`). `judge_model: gpt-5-nano-2025-08-07`. `limit: null` (all 500). `k: 10`. `output_dir: results`. `run_id: "routing-eval"` (→ `results/routing-eval.jsonl`). `cost_ceiling_usd: 10.0` (FR-7). `prices:` map carrying cheap, strong, **and** judge entries (the three from `baseline.yaml` are exactly these). (FR-1, FR-7, AC-1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | direct                 | 2 — Config       |
| `configs/routing-eval.dev.yaml`          | **New.** Identical to `routing-eval.yaml` except `limit: 20` and a distinct `run_id: "routing-eval-dev"` (→ `results/routing-eval-dev.jsonl`, no clobber). Same `router:` block, same `prices`, same `cost_ceiling_usd: 10.0` (a 20-q sweep stays far under it; keeping it identical avoids a second knob). For the FR-10 dev-first pipeline validation. (FR-1, FR-10, AC-1, AC-10)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | direct                 | 2 — Config       |
| `src/enterprise_rag_ops/eval/metrics.py` | **New.** Pure module. `def compute_cost_per_correct(records: Iterable[EvalRecord]) -> float \| None:` — materialise `records` once (it may be an iterator), `numerator = sum((r.generation.cost_usd or 0.0) for r in records)`, `denominator = sum(1 for r in records if r.failure_mode == "correct")`; `return None if denominator == 0 else numerator / denominator`. Imports `EvalRecord` from `enterprise_rag_ops.eval.records`. **Generation cost only** (`r.generation.cost_usd`); judge cost (`r.judge.cost_usd`) is never read. `None` summand → `0.0` (the `(x or 0.0)` convention, runner.py:261). No system field assumed beyond what it sums — caller groups first. Module + function docstrings cite FR-3 / the cost-accounting KB. (FR-3, AC-3, AC-4, AC-5)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | direct                 | 3 — Core         |
| `tests/eval/test_metrics.py`             | **New** (mirrors `src/eval/metrics.py`; `tests/eval/__init__.py` exists). **Cassette-free** — pure arithmetic over constructed `EvalRecord` fixtures, no LLM API (ADR-0006 N/A). Build records via a small `_record(cost, failure_mode)` factory using full `CallStats`/`GenAiFields` kwargs (follow the `tests/eval/test_records.py` direct-construction pattern). Cases: (AC-3) two records, costs 0.10 + 0.30, both `failure_mode=="correct"` → exact `0.20`; mixed correct/incorrect → numerator over **all** records, denominator over correct only; (AC-4) zero-correct group → `None`; (AC-5) a record with `generation.cost_usd=None` mixed with floats → that summand is `0.0`, no crash; single-record correct → its own cost; single-record incorrect → `None`. Judge-cost-ignored: set `judge.cost_usd` to a large value, assert it does not affect the result. (FR-8, AC-3, AC-4, AC-5, AC-11)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | direct                 | 6 — Tests        |
| `scripts/routing_evaluation.py`          | **New** (committed, in the existing top-level `scripts/` dir; no `[project.scripts]` entry — a one-off analysis tool, mirrors `scripts/signal_validation.py`). Pure pandas/json, **no live API** (NFR-3). (1) `RESULTS_PATH = Path("results/routing-eval.jsonl")` (module constant; the dev run is checked by pointing it at the dev JSONL or a small CLI arg — keep it a constant per the signal_validation precedent, with a comment noting the dev path). (2) Load each line as JSON; fail with a clear `SystemExit` if any `failure_mode is None` (classify not run — mirror signal_validation `_load`). (3) **Overlap assert (FR-5):** build `{system: set(question_id)}`; if not all sets equal, `raise SystemExit` (or `AssertionError`) naming the mismatched systems and the symmetric-difference size — **raise, not warn**. (4) Group rows by `gen_ai.system`; reconstruct `EvalRecord` per row (`EvalRecord.model_validate(row)`) or read `generation.cost_usd` / `failure_mode` / `fact_recall` directly and pass `EvalRecord` objects to the helper — prefer `model_validate` so the helper sees real `EvalRecord`s. (5) Per group call `compute_cost_per_correct`; compute `fact_recall` mean, `total_gen_cost = sum(generation.cost_usd or 0)`, `n_correct = count(failure_mode=="correct")`. (6) Print the table `system \| cost_per_correct \| fact_recall \| total_gen_cost \| n_correct` (render `None` as `"N/A"`). (7) (Should, FR-9) write `docs/analysis/routing-cost-quality.png` — matplotlib `Agg`, one point per system, x=`cost_per_correct`, y=`fact_recall`, labelled. (FR-4, FR-5, FR-9, AC-6, AC-7, AC-9) | direct                 | 5 — Obs/analysis |
| `docs/analysis/routing-verdict.md`       | **New.** The honest write-up in the fixed **hypothesis → evidence → verdict** structure matching `docs/analysis/over-abstention.md` / `escalation-signal-validation.md`. (1) **Hypothesis** — does cost-aware routing beat the best single model on cost-per-correct at equal quality? State the ADR-0011 §6 / ADR-0012 prior: a null result is expected at ≈54% escalation. (2) **Evidence** — embed the FR-4 head-to-head table (real numbers from the full sweep), the realized escalation rate on the sweep, the quality-at-cost positioning (fact_recall vs cost_per_correct per system), and reference the FR-9 scatter if built. (3) **Verdict** — the measured answer (likely null) stated plainly, framed as a valid sprint outcome per SPRINT.md criterion 4. Tone/structure follows the two precedent write-ups (hook → metric landscape → reading → implications). Written **last**, from the real full-sweep numbers. (FR-6, AC-8, AC-9)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct                 | 7 — Docs         |
| `docs/analysis/routing-cost-quality.png` | **New (generated by the script, committed — Should).** The FR-9 quality-at-cost scatter, referenced from `routing-verdict.md`. Produced by `scripts/routing_evaluation.py` on the full classified JSONL. (FR-9, AC-9)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct                 | 7 — Docs         |

> **UNCHANGED (read-only this phase, NFR-1):** `eval/report.py`, `eval/records.py`
> (`EvalRecord`/`CallStats` schema), `eval/runner.py`, `eval/config.py` (`RouterConfig`
> shipped phase 2), `eval/classify_cli.py`, the three concrete generators,
> `generation/router_generator.py`, the Makefile (`classify` already takes `RESULTS_FILE`;
> no new target per OQ-2), `pyproject.toml` (matplotlib/pandas already in the dev group
> from phase 1). **No ADR** (Out of Scope — the verdict is a finding, ADR-0011 §6 +
> ADR-0012 cover the design).

## Implementation Phases

Ordered so each step is independently verifiable; explicitly tagged offline/CI-gated vs.
real-sweep. Per the convention (schema → config → core `src/` → eval wiring → obs/analysis
→ tests → docs), with the offline-testable core (config + helper + tests) gating
`make lint test` before any spend.

1. **Data schema / dataset loading** — **none.** `EvalRecord.generation.cost_usd`,
   `failure_mode`, `gen_ai.system`, `question_id`, `fact_recall` all exist (records.py:32,
   76-98). No schema edit (NFR-1, AC-1).
2. **Config** _(offline — `RunConfig.load_from_yaml` parse is CI-checkable)_ —
   `configs/routing-eval.yaml` + `configs/routing-eval.dev.yaml`. Verify with a parse
   assert (AC-1): `router.threshold == 1.0`, `cost_ceiling_usd == 10.0`, `limit is None`
   (full) / `== 20` (dev), `prices` has cheap/strong/judge keys.
3. **Core module logic** _(offline — the CI gate)_ — `src/enterprise_rag_ops/eval/metrics.py`
   :: `compute_cost_per_correct`. Pure; no I/O. Satisfies FR-3.
4. **Eval harness wiring** — **none.** The combined-sweep plumbing (router as a synthetic
   row in one JSONL) shipped in phase 2; FR-1/FR-2 reuse `rag-eval run` and `make classify`
   unchanged (OQ-2).
5. **Observability / analysis** _(offline against a fixture or the dev/cached JSONL)_ —
   `scripts/routing_evaluation.py`: load JSONL → overlap assert (FR-5) → group → helper →
   table → optional scatter. Runs with no network.
6. **Tests** _(offline — the CI gate)_ — `tests/eval/test_metrics.py`, cassette-free.
   Targeted first: `uv run pytest tests/eval/test_metrics.py`, then `make lint test`
   (AC-11). This closes the offline deliverable before any API spend.
7. **Real sweeps + write-up** _(REQUIRES the real, capped API sweep — runs once)_:
   - **(7a) Dev-pipeline run (FR-10/AC-10, ~20 q):** `uv run rag-eval run --config
configs/routing-eval.dev.yaml` → `make classify RESULTS_FILE=results/routing-eval-dev.jsonl`
     → `uv run python scripts/routing_evaluation.py` (pointed at the dev JSONL). Confirms the
     full chain prints a four-row table before the expensive run.
   - **(7b) Full sweep (AC-1, 500 q, ≤ $10):** `uv run rag-eval run --config
configs/routing-eval.yaml` → `make classify RESULTS_FILE=results/routing-eval.jsonl`
     → `uv run python scripts/routing_evaluation.py`. **Runs once** (budget-conscious; SPRINT.md
     sweep-cost mitigation). Per the eval-baseline-run-recipe: build the gold index first
     (`make build-index-gold`), `caffeinate` the machine, consider `--concurrency`.
   - **(7c) Write-up:** `docs/analysis/routing-verdict.md` (+ the committed `.png`), written
     from the 7b numbers. Comes **last** — the verdict needs the real measured table.

> **Offline/CI-gated:** steps 2, 3, 5, 6 (config parse, pure helper, the analysis script run
> against a fixture/dev JSONL, the metric tests). **Requires the real capped sweep:** step 7
> (7a dev, 7b full, 7c write-up). `make lint test` is green at the end of step 6, before any
> spend — the offline core is fully gated independent of the sweep.

## Infrastructure Gaps

Deep three-layer check (domain existence / concept coverage / agent alignment), run against
the actual KB and agent files — **confirms** DEFINE's Infrastructure Readiness table: no gap
blocks this phase.

| Gap Type           | Area              | Detail                                                                                                                                                                                                                                                                                                                                                                                                                           | Recommendation                                           |
| ------------------ | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Missing domain     | —                 | Every affected tech area has a KB domain: `rag-eval` (`cost-accounting`, `multi-model-runner`, `eval-record-schema`, `failure-taxonomy`, `cassette-replay`) covers the metric, the combined sweep, the classify step, and the cassette-free test rationale. `rag-generation` (`router-cascade` via ADR-0012) covers the router cost ownership. No observability work. **No new domain.**                                         | None                                                     |
| Missing concept    | `rag-eval`        | The **cost-per-correct-answer** metric is not yet a documented concept — `cost-accounting.md` deliberately forward-references it as out-of-scope-until-phase-3 (DEFINE Users, BRAINSTORM coverage table). **Not a blocker:** it is standard arithmetic (`sum(gen_cost) / count_correct`), fully specified here in FR-3, and the Sprint-Wide Knowledge Plan schedules the write for **after** the metric stabilizes (this phase). | `/update-kb rag-eval` — **post-phase** (Could, deferred) |
| Missing concept    | `rag-generation`  | The **router-cascade composite** pattern write is scheduled post-ADR-0012-merge. ADR-0012 is merged (phase 2), so it is now unblocked — but it remains a Could-level follow-on, not a phase-3 blocker (the router code + its cost invariant already exist and are documented in `cost-accounting.md`).                                                                                                                           | `/update-kb rag-generation` — **post-phase** (Could)     |
| Missing specialist | eval / generation | No specialist agent owns `src/eval` or `src/generation` (all existing agents are workflow agents with `kb_domains: []`). Every manifest file is `direct`. One pure helper + one analysis script + configs + a doc does not warrant a specialist.                                                                                                                                                                                 | None (no `/new-agent`)                                   |

- **Domain existence:** ✅ `rag-eval` + `rag-generation` cover all areas; no observability layer touched.
- **Concept coverage:** ✅ The primitives exist — `compute_cost_usd` + the `cost_usd: float|None`
  / `None`-on-empty-denominator convention (cost-accounting) cover the helper; `multi-model-runner`
  covers the combined sweep; `failure-taxonomy` covers `failure_mode == "correct"`; `cassette-replay`
  covers why the metric test is cassette-free (it is not LLM-touching). The two deferred concept
  writes are stabilization follow-ons, not blockers.
- **Agent alignment:** ✅ N/A — no specialist owns these modules; `kb-architect` owns the two
  deferred post-phase `/update-kb` writes, consistent with the Sprint-Wide Knowledge Plan.

**Verdict: no new KB, agent, command, or `--deep-research` blocks phase 3.** Matches DEFINE.

## Consistency Check

Multi-file phase (2 configs + 1 `src` module + 1 test + 1 script + 1 doc; DEFINE went
through brainstorm→define with all 5 OQs resolved). Six-pass cross-check of DEFINE↔DESIGN
against the constitution (AGENTS.md § Engineering Behavior + § Conventions + § Testing,
ADR-0011, ADR-0012, ADR-0006, the `rag-eval`/`rag-generation` KB).

**Verdict: ✅ CONSISTENT** — no CRITICAL/HIGH drift. Three LOW notes for the implementer.

| ID  | Severity | Pass               | Location                       | Finding                                                                                                                                                                       | Suggested fix                                                                                                                                                                                                                                                                                               |
| --- | -------- | ------------------ | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | LOW      | Underspecification | FR-4 / script JSONL input path | DEFINE/FR-4 says "loads the classified JSONL" but never pins the path or how the dev vs full JSONL is selected. The signal_validation precedent hard-codes a module constant. | DESIGN pins `RESULTS_PATH = Path("results/routing-eval.jsonl")` as a module constant (matching `signal_validation.py`); the dev validation (AC-10) points the script at `results/routing-eval-dev.jsonl` via a one-line edit or a small optional `argv[1]` override. Implementer's choice; keep it minimal. |
| C-2 | LOW      | Ambiguity          | FR-9 / scatter filename        | DEFINE/FR-9 says a `.png` "under `docs/analysis/`" without a name.                                                                                                            | DESIGN pins `docs/analysis/routing-cost-quality.png` (parallels `escalation-signal-separation.png`). Referenced from `routing-verdict.md`.                                                                                                                                                                  |
| C-3 | LOW      | Inconsistency      | config `run_id` / dev clobber  | The full and dev configs must not write the same JSONL (the phase-1 C-4 `run_id` collision lesson).                                                                           | DESIGN sets full `run_id: "routing-eval"` (→ `results/routing-eval.jsonl`) and dev `run_id: "routing-eval-dev"` (→ `results/routing-eval-dev.jsonl`). Implementer must not reuse one `run_id`.                                                                                                              |

Notes on the passes that found nothing:

- **Duplication** — none. FR-3 (helper) and FR-4 (script grouping) are layered, not
  overlapping; FR-5 (overlap assert) and NFR-2 (fair head-to-head) state the same guarantee
  from requirement vs. constraint angles without conflicting phrasing.
- **Constitution alignment** — ✅ no violation. **Minimal scope** — one pure helper + one
  script + two configs + one doc; `report.py`/schema/runner explicitly unchanged (NFR-1);
  no threshold sweep, no Pareto frontier, no `report.py` column, no correct-path split (all
  Out of Scope). **Clean seam** — the metric is a pure function, not a premature abstraction;
  the router seam it measures is the ADR-0012 one (a named, ratified change, not "in case").
  **Surgical edits** — no existing tested surface touched. **No stranger-test leak** — the
  config, helper, script, and verdict are all system artifacts (no career/budget/private-path
  content). **Conventions** — English; YYYY-MM-DD; tests mirror `src/` into `tests/eval/`
  (existing `__init__.py`), no flat `tests/test_metrics.py` (NFR-5); the metric test is
  **cassette-free** because it touches no LLM API (ADR-0006 applies only to LLM-touching code).
  The analysis script lives in `scripts/` (off the production package surface, signal_validation
  precedent).
- **Coverage** — ✅ all 10 FR + 6 NFR map to ≥1 manifest entry (FR-1→both configs;
  FR-2→reuse `make classify`, no new file, covered by config `run_id` + the recipe;
  FR-3→`eval/metrics.py`; FR-4→`scripts/routing_evaluation.py`; FR-5→script overlap assert;
  FR-6→`routing-verdict.md`; FR-7→`cost_ceiling_usd: 10.0` in `routing-eval.yaml`;
  FR-8→`tests/eval/test_metrics.py`; FR-9→`routing-cost-quality.png` + script;
  FR-10→`routing-eval.dev.yaml` + step 7a). All 11 AC map to a test/parse/run/doc check
  (AC-1→config parse + the full sweep; AC-2→classify reuse; AC-3/4/5→test_metrics;
  AC-6/7→the script; AC-8→routing-verdict.md; AC-9→the .png; AC-10→step 7a; AC-11→`make lint
test`). Reverse: every manifest entry traces to a confirmed component
  (`generation.cost_usd`/`failure_mode`/`fact_recall`/`question_id` at records.py:32,76-98;
  the synthetic router row at runner.py:168-190; `make classify RESULTS_FILE=` at Makefile:7,47-48;
  `RouterConfig` at config.py:25-38; the `scripts/signal_validation.py` precedent — all read
  this session).
- **Inconsistency** — C-3 (`run_id` collision, resolved). Terminology is stable
  (`cost_per_correct`, `gen_ai.system`, `failure_mode == "correct"`, "combined cost", "router"
  row) across DEFINE/DESIGN/ADR-0012; no directive conflicts.

## Risks & Trade-offs

- **Combined-runner emits router + baselines in ONE JSONL — VERIFIED, the highest-value
  check.** The whole fairness argument (FR-5/NFR-2) depends on a single combined sweep. Read
  of `eval/runner.py` confirms it: `run_evaluation` appends the router as a synthetic
  `_SweepUnit("router","router", RouterGenerator(...))` to the same `sweep_units` list as the
  `config.models` baselines (runner.py:168-190) and writes all units to one `output_path`
  (runner.py:137, 193-194), over one question set and one retriever. **No separate router
  invocation is needed; AC-1's single-JSONL assumption is exactly the shipped behavior.** Had
  the router needed a separate run this would have been a CRITICAL gap — it does not.

- **Expected null result (not a design defect).** At ≈54% escalation the router pays cheap-always
  - strong-on-most, so it is expected **not** to dominate either single model on cost-per-correct
    (ADR-0011 §6, ADR-0012). The deliverable is the measured verdict; a null is valid and publishable
    (SPRINT.md criterion 4). The DESIGN does not engineer toward a win.

- **The full sweep runs once (budget).** ≈$4.79 gen + judge overhead across four systems; the
  `$10.0` ceiling (FR-7) is a ≈2× safety halt, not a budget target. The dev-first discipline
  (7a) de-risks a wasted full run. If the ceiling halts mid-run, the boundary record is still
  written (runner cost-guard) but the overlap assert (FR-5) will then **correctly raise** —
  systems would have different `question_id` sets. That is the assert doing its job: re-run
  rather than publish an unfair comparison. Note this in the recipe.

- **`EvalRecord.model_validate` in the script vs. raw dict reads.** The helper takes
  `EvalRecord`s; the script should `model_validate` each JSONL row so the helper sees real
  records (and so `generation.cost_usd` / `failure_mode` access is type-checked). A raw-dict
  shortcut would work but drifts from the helper's contract — prefer `model_validate`.

- **No ADR this phase (correct).** The verdict is a finding; ADR-0011 §6 + ADR-0012 cover the
  design decisions. An ADR would be speculative scope (Out of Scope, § Engineering Behavior).

- **Determinism (NFR-3).** The helper is pure; the script reads a cached JSONL and makes no live
  call, so the table and plot are deterministic given a fixed JSONL. The only non-deterministic
  step is the sweep (real API), run once and cached.

## Next Step

→ `/implement sprint-7/phase-3-routing-evaluation` — no infrastructure gap blocks it. Per the
cross-tool **Implement Contract** (AGENTS.md), implement in **Antigravity / Gemini** against
this `DESIGN.md`: confirm the branch `sprint-7/phase-3-routing-evaluation`, read this manifest +
`DEFINE.md` + the `rag-eval` (`cost-accounting`, `multi-model-runner`, `failure-taxonomy`) KB,
build the **offline core first** (configs → `eval/metrics.py` → `tests/eval/test_metrics.py`,
gate on `make lint test`), then the script, then the **dev pipeline (7a) before the single full
sweep (7b)**, and write `routing-verdict.md` last from the real numbers. Honor the three LOW
consistency notes. Post-phase: `/update-kb rag-eval` (cost-per-correct concept) + `/update-kb
rag-generation` (router-cascade pattern).
