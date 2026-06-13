# BRAINSTORM: sprint-7/phase-3-routing-evaluation — Routing Evaluation & Finding

**Sprint/Phase:** sprint-7/phase-3-routing-evaluation | **Date:** 2026-06-05

## Problem Statement

Phase 2 delivered a `RouterGenerator` that composes cheap (Gemini) and strong (Anthropic)
generators with fair combined-cost accounting. Phase 3's job is to measure whether that
router beats each single-model baseline on **cost-per-correct-answer** — the evaluation
harness's own finding back on the router. Per ADR-0011 §6, a null result (routing does not
pay off at ≈54% escalation) is the expected, honest baseline outcome; the deliverable is the
measured verdict plus a write-up, not a guaranteed win.

---

## Suggested Research & KB Work

| Topic                                                                  | KB Coverage                                                                                                                                                                     | Action                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rag-eval` domain (per-fact judge, cost accounting, runner, report.py) | **Sufficient** — concepts/cost-accounting.md has the router cost invariant and a forward-reference to phase-3; patterns/multi-model-runner.md covers the combined-config sweep. | No new KB work needed as a blocker.                                                                                                                                                                                                                                                                                                                                    |
| Cost-per-correct-answer metric definition                              | **Thin** — deliberately deferred in cost-accounting.md ("forward reference: out of scope for phase-2").                                                                         | Flag as **post-implementation** `/update-kb rag-eval` task once the metric stabilizes in this phase. Not a blocker.                                                                                                                                                                                                                                                    |
| Router/cascade composite (rag-generation)                              | **Thin** — REVIEW.md deferred to after the phase-2 ADR.                                                                                                                         | Same: post-ADR-0012-merge `/update-kb rag-generation`. Not a blocker here.                                                                                                                                                                                                                                                                                             |
| Quality-at-cost / Pareto-frontier reporting conventions                | **Missing**                                                                                                                                                                     | **No deep research needed.** Cost-per-correct-answer is standard (cost / count_correct). A light scan confirms no novel methodology is required. No `--deep-research` warranted. The reporting shape (head-to-head table + optional Pareto scatter) follows the phase-1 precedent in `scripts/signal_validation.py` + `docs/analysis/escalation-signal-validation.md`. |
| Cascade eval methodology                                               | **Sufficient** — researched pre-phase-1 (sprint-7 escalation signal research).                                                                                                  | None.                                                                                                                                                                                                                                                                                                                                                                  |

**O4 conclusion:** No blocking KB work. One post-implementation KB write (rag-eval +
cost-per-correct-answer concept; rag-generation + router-cascade pattern) is the natural
follow-on once the ADR-0012 lands and this metric stabilizes. No `--deep-research` is
warranted for this phase.

---

## Approaches Considered

### Design Tension 1: Where the cost-per-correct-answer metric lives

| Approach                                                                                                                                             | Pros                                                                                                                                                                               | Cons                                                                                                                                                                                                                               | Effort |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Extend `report.py` — add a `cost_per_correct` field to `generate_report_data` and a head-to-head table to `render_markdown`/`render_html`         | Single surface for all operational metrics; CI-covered; reusable in future sweeps; consistent with how existing quality + cost tables are generated                                | Requires `failure_mode` to be present in the JSONL (classify step must run before reporting, adding a pipeline dependency); bloats report.py with a "research finding" metric that is currently only needed for the sprint verdict | M      |
| B. Standalone `scripts/` analysis script (phase-1 precedent) — read the classified JSONL, join cost + failure_mode, compute and print/plot the table | Fast, zero blast radius; exactly mirrors `scripts/signal_validation.py` pattern; no change to report.py or any tested surface; a one-off investigation tool fits a one-off finding | Untested, one-shot; if the metric is needed again the logic must be rediscovered or duplicated; does not compose with `render_report`                                                                                              | S      |
| C. New `eval/metrics.py` helper (tested) + thin `scripts/` call + optional report hook                                                               | Metric logic is unit-tested and reusable; script stays thin (just calls the helper); report.py can later import the same helper for a single-surface upgrade path                  | Two-file change; slightly more up-front structure than B; the "optional report hook" is speculative scope unless explicitly required                                                                                               | M      |

**Recommended shape (to confirm at /define):** Approach C — a `compute_cost_per_correct`
helper in `eval/` (small, pure-function, testable), called from a thin `scripts/routing_evaluation.py`
that loads the JSONL, runs the metric, prints the table, and optionally saves a plot. This
keeps `report.py` clean (no classify-step dependency injected into the baseline report
pipeline) while leaving the metric reachable for future integration. The helper is the
planned KB-documented concept once it stabilizes.

---

### Design Tension 2: Sweep design for a fair head-to-head

| Approach                                                                                                                   | Pros                                                                                                                                                                       | Cons                                                                                                                                                                                                   | Effort          |
| -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------- |
| A. Combined config — one YAML with `models: [3 baselines]` + `router:` block, single `rag-eval run` call, one output JSONL | Identical questions/retrieval/judge per question across all systems (the gold standard for fairness); one file to inspect; phase-2's runner already supports this natively | Requires raising the `cost_ceiling_usd` ceiling for a 500-question 4-way sweep; longer wall-clock run                                                                                                  | S (config only) |
| B. Separate runs joined by `question_id`                                                                                   | Reuses existing run JSONLs if baselines were already run; avoids a single long run                                                                                         | Question overlap is not guaranteed (sampling is randomized unless seeded; ceiling may have stopped a prior run early); joining requires extra scripting; post-hoc join is harder to document as "fair" | M               |

**Recommended:** Approach A — a new `configs/routing-eval.yaml` combining all three
baseline models and the router block, `limit: null` for the final run. Dev-iterate with
`limit: 20` on `configs/routing-eval.dev.yaml`. This is the clean path the phase-2 runner
enables, and it sidesteps any "did they see the same questions?" objection.

---

### Design Tension 3: Cost scope for the metric (generation cost only vs gen+judge)

| Approach                                            | Pros                                                                                                                                                                                          | Cons                                                                                                         | Effort  |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------- |
| A. Generation cost only for cost-per-correct-answer | Judge cost is eval overhead identical across all systems, so removing it makes the metric a fair deployment-cost comparison; lines up with "what you'd actually pay per answer in production" | Requires splitting gen vs judge cost from EvalRecord (available: `r.generation.cost_usd`)                    | trivial |
| B. Gen+judge cost                                   | Simpler (total_cost already computed in report.py)                                                                                                                                            | Judge cost is the same fraction for all systems, so it dilutes the signal; misleading as a deployment figure | trivial |

**Recommended:** Approach A — generation cost only in the numerator. The judge is eval
infrastructure, not deployment cost. `EvalRecord.generation.cost_usd` is already the
per-record router-manufactured combined cost. The denominator is `count(failure_mode ==
"correct")` per system. The formula: `cost_per_correct = sum(gen cost) / count(correct)`.
Note: if a system has zero correct answers the metric is undefined (None/N/A, consistent
with the None-convention throughout the harness).

---

## Recommended Approach

**Combined config + eval/ metric helper + scripts/ analysis script.**

1. `configs/routing-eval.yaml` — single combined run config (3 baselines + router, limit:
   null, ceiling: $10 for safety). `configs/routing-eval.dev.yaml` (limit: 20) for
   iteration.
2. `eval/metrics.py` (new, tested) — a `compute_cost_per_correct` pure function: takes a
   list of `EvalRecord`, returns `float | None`. Unit-tested (cassette-free — it is pure
   arithmetic over already-classified records).
3. `scripts/routing_evaluation.py` — loads the classified JSONL, calls the helper per
   system group, prints the head-to-head table, optionally writes a quality-at-cost scatter
   plot (fact_recall vs cost_per_correct per system).
4. `docs/analysis/routing-verdict.md` — the honest write-up: metric table, separation from
   baselines, verdict. Follow the tone/structure of `docs/analysis/over-abstention.md` and
   `docs/analysis/escalation-signal-validation.md`.

This approach minimizes blast radius (report.py unchanged; no schema changes; one new eval/
helper + one new script + one new config + one analysis doc), keeps the metric unit-tested,
and delivers the exact sprint success criteria 3 and 4.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                             |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ----------- | -------------- | --------- |
| **Must**   | `configs/routing-eval.yaml` + `.dev.yaml` (combined sweep config: 3 baselines + router in one run)                                                                               |
| **Must**   | Classify step on the resulting JSONL (`rag-classify` CLI or equivalent) to produce `failure_mode` labels                                                                         |
| **Must**   | `eval/metrics.py` — `compute_cost_per_correct(records) -> float                                                                                                                  | None` helper, with unit tests |
| **Must**   | `scripts/routing_evaluation.py` — head-to-head table: system                                                                                                                     | cost_per_correct              | fact_recall | total_gen_cost | n_correct |
| **Must**   | `docs/analysis/routing-verdict.md` — the honest verdict write-up (null result is a valid and expected outcome per ADR-0011/0012)                                                 |
| **Should** | Quality-at-cost scatter plot (fact_recall vs cost_per_correct per system) saved as a `.png` in `docs/analysis/` — visual equivalent of the phase-1 separation plot               |
| **Should** | Dev-iteration discipline: run `routing-eval.dev.yaml` (20 q) to validate the pipeline end-to-end before the full 500-question sweep                                              |
| **Could**  | Extend `report.py` to render cost-per-correct-answer in the standard HTML/MD report (requires classify pre-step; defer unless the sprint has room)                               |
| **Could**  | `/update-kb rag-eval` — add cost-per-correct-answer concept (scheduled post-phase once the metric stabilizes)                                                                    |
| **Could**  | `/update-kb rag-generation` — add router-cascade composite pattern (scheduled post-ADR-0012-merge)                                                                               |
| **Won't**  | Threshold sweep over escalation thresholds (SPRINT.md explicit Won't — one operating point, measure, stop)                                                                       |
| **Won't**  | A new ADR for the routing evaluation itself — the measurement methodology needs no new ADR (ADR-0011 §6 and ADR-0012 cover the design; the verdict is a finding, not a decision) |
| **Won't**  | Multi-threshold Pareto frontier analysis (deferred to backlog if ever needed)                                                                                                    |
| **Won't**  | Leaderboard submission as part of this phase (already deferred to backlog B-09)                                                                                                  |
| **Won't**  | Re-run any prior baseline JSONL separately and join by question_id — the combined-config single-run approach is the only fair path                                               |

---

## Open Questions

1. **Cost ceiling for the full combined sweep.** The existing `baseline.yaml` has
   `cost_ceiling_usd: 5.0`, which was sufficient for 3-model baselines but a 4-way sweep
   (3 baselines + router, 500 questions, router paying cheap-always + strong-iff-escalated
   at ≈54% escalation) will cost more. What ceiling is appropriate? A rough estimate: Gemini
   ~$0.64, GPT-5 Nano ~$0.89, Haiku ~$1.70 for 500 q, plus router ≈ cheap($0.64) +
   54% × strong($1.70) ≈ $1.56. Combined ≈ $4.79 gen + judge overhead. The $5.0 ceiling may
   be tight; $10.0 or $15.0 seems appropriate. **Needs an explicit number at /define.**

2. **Where does the classify step sit in the pipeline?** The `routing_evaluation.py`
   script requires `failure_mode` to be populated on each record. The classify step
   (`rag-classify` or equivalent) is a separate CLI invocation run after the sweep. Should
   the phase add explicit CLI documentation (e.g., a `make routing-eval` target) to chain
   sweep → classify → analysis? Or is a README-level recipe sufficient? **Needs a decision
   at /define.**

3. **Metric denominator: per-system `n_correct` vs per-question overlap.** The
   cost-per-correct-answer metric groups records by system and computes
   `sum(gen_cost) / count(failure_mode == "correct")` per group. This is correct when all
   systems saw the same questions (hence the combined-config requirement). Should the script
   assert that all systems in the JSONL have the same `question_id` set, or is a warning
   sufficient? **Confirm at /define.**

4. **"Correct" definition for the router row.** The router's `failure_mode` will be set
   by the existing classifier on its `EvalRecord` rows (same schema, same logic). Is
   `failure_mode == "correct"` the right and sufficient correctness gate for the router, or
   does the phase need to surface escalation-specific labels (e.g., "correct-via-cheap" vs
   "correct-via-escalation") for a richer analysis? This is a Should/Could — the Must path
   uses the existing label — but the verdict write-up may be more interesting with the split.
   **Decide scope at /define.**

5. **Deliver the verdict as a null result or keep room for a positive finding?** ADR-0011
   and ADR-0012 both explicitly name a null result as the expected baseline. The write-up
   should frame either outcome as valid. Does the verdict write-up need a specific structure
   (e.g., "hypothesis → evidence → verdict" matching the over-abstention write-up), or is a
   free-form analysis with the metric table sufficient? **Confirm tone/structure contract at
   /define.**

---

## Next Step

-> `/define sprint-7/phase-3-routing-evaluation`
