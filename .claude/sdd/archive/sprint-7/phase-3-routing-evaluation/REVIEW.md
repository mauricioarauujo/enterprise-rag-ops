# Review: sprint-7/phase-3-routing-evaluation — Routing Evaluation & Finding

**Branch:** `sprint-7/phase-3-routing-evaluation` | **Date:** 2026-06-13 | **Verdict:** ✅ READY

## Summary

Phase 3 swept the cost-router against the three single-model baselines through the eval
harness and delivered an honest, measured verdict: **routing does not pay off** — the router
is strictly dominated (Gemini ~9× cheaper per correct at equal quality; GPT-5 Nano 2× cheaper
_and_ highest quality). Mid-phase, the full 500-q sweep kept dying on a single transient
OpenAI judge timeout, so the runner was hardened with transient-error skip + `--resume`
(a deliberate, approved NFR-1 exception, to land as its own `fix(runner)` commit). The code
review (model: sonnet) returned **ALMOST** with one latent bug + two non-blocking notes; all
three are now fixed and `make lint test` is green.

## Mechanical Checks

| Step   | Status | Notes                                             |
| ------ | ------ | ------------------------------------------------- |
| Format | PASS   | `ruff format` + prettier clean                    |
| Lint   | PASS   | `ruff check` — all checks passed                  |
| Tests  | PASS   | **322 passed**, 17 deselected (12 new this phase) |

## Issues

All issues from the code review are resolved.

<details>
<summary>🔴→✅ <code>scripts/routing_evaluation.py</code> — scatter crashed on a None fact_recall</summary>

`_write_scatter` filtered only on `cost_per_correct is not None`; a system with a cost but an
all-`None` `fact_recall` would pass `y=None` to `ax.scatter` → matplotlib `TypeError`. Latent
(the real sweep didn't trigger it) but reachable on a degenerate dev run.
**Fix applied:** filter also requires `r["fact_recall"] is not None`.

</details>

<details>
<summary>⚠️→✅ <code>tests/eval/test_runner.py</code> — stale docstring cross-reference</summary>

The new transient-skip test's docstring referenced a non-existent
`test_runner_partial_results_on_crash`. **Fix applied:** points at the real
`test_runner_flushes_jsonl_early_stop` (the RuntimeError-propagates contrast).

</details>

<details>
<summary>⚠️→✅ missing end-to-end "transient gap → resume fills it" chain test</summary>

The three runner tests proved the halves (gap-on-transient, resume-skips, no-resume-truncates)
but not the chain the `--resume` flag exists for. **Fix applied:** added
`test_runner_transient_then_resume_fills_gap` — pass 1 leaves a q2 gap, pass 2 (resume) fills
exactly that gap (q1 not re-run, no duplicate).

</details>

## Acceptance Criteria

| AC    | Status | Evidence                                                                                                                                                        |
| ----- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1  | ✅     | Combined sweep → one JSONL, 2000 rows = 500 × {openai, anthropic, google, router}, same questions; total $4.43 ≤ $10                                            |
| AC-2  | ✅     | `make classify` populated `failure_mode` on all rows incl. router (456 correct / 789 abstention_error / 607 incomplete / 100 hallucination / 48 retrieval_miss) |
| AC-3  | ✅     | `test_cost_per_correct_exact_*` — gen-cost-only, exact arithmetic                                                                                               |
| AC-4  | ✅     | `test_cost_per_correct_zero_correct_returns_none`                                                                                                               |
| AC-5  | ✅     | `test_cost_per_correct_none_summand_treated_as_zero`                                                                                                            |
| AC-6  | ✅     | Four-row head-to-head table; `None` → `"N/A"`                                                                                                                   |
| AC-7  | ✅     | `_assert_same_questions` raises (frozenset-dedup verified); ran clean on the real same-question sweep                                                           |
| AC-8  | ✅     | `docs/analysis/routing-verdict.md` — hypothesis → evidence → verdict                                                                                            |
| AC-9  | ✅     | `docs/analysis/routing-cost-quality.png` committed + referenced                                                                                                 |
| AC-10 | ✅     | Dev pipeline (20 q) validated end-to-end before the single full sweep                                                                                           |
| AC-11 | ✅     | `make lint test` green; metric tests cassette-free (pure `EvalRecord` fixtures)                                                                                 |

## The Finding

| System (500 q)                  | Cost / correct | Fact recall | Gen cost | Correct |
| :------------------------------ | :------------: | :---------: | :------: | :-----: |
| `gemini-2.5-flash-lite` (cheap) |    $0.0007     |    22.9%    |  $0.074  |   101   |
| `gpt-5-nano-2025-08-07`         |    $0.0030     |    25.6%    |  $0.356  |   119   |
| **`router`**                    |    $0.0061     |    23.4%    |  $0.714  |   118   |
| `claude-haiku-4-5` (strong)     |    $0.0104     |    23.4%    |  $1.230  |   118   |

Null result confirmed at scale: realized escalation ≈52% (cost-derived, consistent with
ADR-0011's calibrated ~54%); no quality dividend; the router is strictly dominated. Valid
sprint outcome per SPRINT.md criterion 4.

## KB Staleness

No existing KB doc is contradicted by the diff. Two **deferred** (not stale) follow-ons,
scheduled by the Sprint-Wide Knowledge Plan for sprint close:

| KB domain        | Action                                                                    |
| ---------------- | ------------------------------------------------------------------------- |
| `rag-eval`       | `/update-kb` — add the `cost-per-correct-answer` concept (now stabilized) |
| `rag-generation` | `/update-kb` — add the router-cascade composite pattern (ADR-0012 merged) |

The runner now also carries a **resume + transient-skip** capability worth a line in
`rag-eval` (`multi-model-runner`) once the fix commit lands.

## ADR

No new ADR. The verdict is a _finding_ (ADR-0011 §6 + ADR-0012 cover the design); routing
evaluation needed no new decision (matches DEFINE Out-of-Scope). The runner hardening is a
robustness fix, not an architectural decision — a `fix(runner)` commit + a KB line suffice.

## Suggested Next Steps

1. **Commit as two units** (review-endorsed; do not squash):
   - `fix(runner): transient-error skip + --resume resumable sweeps` — `runner.py`, `cli.py`, `tests/eval/test_runner.py`
   - `feat(sprint-7/phase-3): routing evaluation — null verdict, cost-per-correct` — configs, `metrics.py`, `test_metrics.py`, `scripts/routing_evaluation.py`, `docs/analysis/*`, SDD artifacts
2. Open the PR(s).
3. **Sprint close** (`/sprint-close sprint-7`): run the two deferred `/update-kb` writes + the runner-resume KB line; archive the phase folder.
