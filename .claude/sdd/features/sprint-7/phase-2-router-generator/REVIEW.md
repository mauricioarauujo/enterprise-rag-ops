# Review: sprint-7/phase-2-router-generator — RouterGenerator

**Branch:** `sprint-7/phase-2-router-generator` | **Date:** 2026-06-04 | **Verdict:** ✅ READY

## Summary

The `RouterGenerator` composite, its config/runner wiring, two eval configs, and full
test coverage (13/13 ACs) are correct and pass the mechanical gate. The code-review pass
(code-reviewer, sonnet) returned ALMOST with one actionable consistency issue — the router
branch used bare `gen_factory["google"]`/`["anthropic"]` while the real-model path uses
`.get()` + a clear `ValueError`. That fix has been applied; everything else is a
non-blocking note for the deferred phase-2 ADR. The work is **uncommitted** (working-tree

- untracked files), so `origin/main...HEAD` is empty — review was run against the working
  tree.

## Mechanical Checks

| Step   | Status | Notes                                              |
| ------ | ------ | -------------------------------------------------- |
| Format | PASS   | `make format` applied (whitespace/line-wrap only)  |
| Lint   | PASS   | `ruff check` clean                                 |
| Tests  | PASS   | 309 passed, 17 deselected — re-run green after fix |

## Issues

<details>
<summary>✅ FIXED — Router factory access used <code>[]</code> instead of <code>.get()</code> (runner.py:174-176)</summary>

The real-model sweep (`runner.py:156`) uses `gen_factory.get(model.system)` with an
explicit `ValueError("Unsupported system type: ...")`. The router branch used bare `[]`,
which yields an opaque `KeyError: 'google'` on any `generator_classes` override omitting
`"google"`/`"anthropic"`. **Fix applied** (`runner.py:170-176`): resolve `cheap_cls`/
`strong_cls` via `.get()` and raise a descriptive `ValueError` when either is missing —
consistent with the existing pattern. Gate re-run green.

</details>

<details>
<summary>⚠️ NON-BLOCKING — <code>gen_factory["google"]/["anthropic"]</code> hardcoding is the load-bearing wiring trade-off (runner.py)</summary>

The runner encodes "cheap = Gemini, strong = Anthropic" (FR-8); `RouterConfig` carries the
model **ids** but the **system** mapping is hardcoded. Correct and intentional for phase 2
(NFR-7 scope minimization), but a future cheap/strong on a different provider would need
`RouterConfig.cheap_system`/`strong_system`. **Name this in the phase-2 ADR.**

</details>

<details>
<summary>⚠️ NON-BLOCKING — <code>_SweepUnit.generator</code> is typed <code>object</code> (runner.py:60)</summary>

Typing it as the `Generator` Protocol would self-document intent and let a type-checker
catch a non-conforming generator. Low priority (the Protocol is duck-typed). Optional
follow-up.

</details>

<details>
<summary>⚠️ NON-BLOCKING — <code>StubGenerator</code> pre-sets <code>cost_usd=0.0</code>, so the cost guard silently skips stub-based runner tests</summary>

Pre-existing behavior. Because `0 tokens × any price = 0.0`, recorded values are identical
to the old unconditional-recompute path, so no test changes. But the new guard makes the
invariant ("a generator that pre-sets `cost_usd` owns its cost") more load-bearing — the
phase-2 ADR should state it explicitly.

</details>

## Acceptance Criteria

| AC    | Status | Evidence                                                                                        |
| ----- | ------ | ----------------------------------------------------------------------------------------------- |
| AC-1  | ✅     | `test_no_escalation_when_confident_and_not_abstaining` — strong call_count == 0                 |
| AC-2  | ✅     | `test_escalation_on_low_confidence` — strong called, summed tokens/latency/cost                 |
| AC-3  | ✅     | `test_escalation_on_abstention_even_when_confident` — OR-trigger independent of conf            |
| AC-4  | ✅     | `test_escalation_on_missing_confidence` — `confidence_score is None` escalates                  |
| AC-5  | ✅     | `test_combined_cost_arithmetic_{escalated,not_escalated}` — exact `compute_cost_usd`            |
| AC-6  | ✅     | `test_generate_returns_bare_answer_{no_escalation,escalated}` — bare `AnswerWithSources`        |
| AC-7  | ✅     | `test_router_is_structural_generator` + `interfaces.py` not in diff                             |
| AC-8  | ✅     | `test_router_config_threshold_defaults_to_one`, `test_run_config_without_router_block_is_none`  |
| AC-9  | ✅     | `test_runner_router_row_cost_not_overwritten` — `gen_ai.system/model=="router"`, cost preserved |
| AC-10 | ✅     | `test_runner_cost_guard_backwards_compat_single_model` — `None`→computed (2e-5)                 |
| AC-11 | ✅     | `FakeGenerator`/`StubGenerator` subclasses; zero `unittest.mock`/SDK doubles (ADR-0006)         |
| AC-12 | ✅     | `test_run_config_parses_router{,_dev}_yaml` — knobs, ceiling, limit, 3 prices present           |
| AC-13 | ✅     | `make lint test` → 309 passed, lint clean                                                       |

**13/13 covered.** Reviewer independently confirmed cost manufacture (FR-5/NFR-2),
escalation boolean (FR-4), cost guard (FR-9/NFR-4), C-2 avoidance, Protocol-unchanged, and
the stranger test (no personal context in any tracked file).

## Knowledge Capture Suggestions

| What was learned                                                                                                    | Suggested KB domain | Action                                                                                          |
| ------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------- |
| Router/cascade `Generator`-composite pattern (two injected generators, escalation rule, single-owner combined cost) | rag-generation      | `/update-kb rag-generation` — **deferred to after the phase-2 ADR** (sprint plan)               |
| Two-call combined-cost accounting (cheap-always + strong-iff-escalated, `None`→0.0; runner cost-guard invariant)    | rag-eval            | `/update-kb rag-eval` — **deferred to post-phase-3** (cost-per-correct-answer stabilizes there) |

Both are intentionally scheduled post-phase per SPRINT.md — not gaps. KB documents
_stabilized_ knowledge; the pattern stabilizes once the ADR records it and phase-3 measures
the verdict.

## KB Staleness

None. The diff is purely **additive** — `RouterConfig`/`RunConfig.router` are new optional
fields; `ModelConfig`, the `system` `Literal`, `_GENERATOR_FACTORY`, `CallStats`,
`compute_cost_usd`, and the `Generator` Protocol are unchanged. No KB-documented API, enum,
or constraint was altered.

## ADR

**Recommended (already planned).** This phase made architectural decisions not yet in
`docs/adr/`: the router-composite (Approach B), B-1 combined-cost ownership,
`system="router"`/`model="router"` identity, and the **cost-guard semantic shift** (any
generator that pre-sets `cost_usd` now owns it — the runner no longer unconditionally
recomputes). The phase-2 ADR is a sprint-wide item scheduled after this phase lands; it
should explicitly name the cost-guard invariant and the cheap=Gemini/strong=Anthropic
hardcoding (issues above).

## Suggested Next Steps

1. **Commit** the change set (Conventional Commits, e.g. `feat(sprint-7/phase-2): RouterGenerator — cheap-default cost router with fair combined-cost accounting`) and open the PR.
2. **Write the phase-2 ADR** (router composite + cost-guard invariant) — naming the two non-blocking notes above.
3. Continue the sprint per SPRINT.md (phase-3 cost-per-correct-answer sweep consumes the `router` row).
