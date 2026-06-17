# Review: sprint-8/phase-2-root-cause-linkage — Per-Fact Root-Cause Attribution

**Branch:** `sprint-8/phase-2-root-cause-linkage` | **Date:** 2026-06-17 | **Verdict:** ✅ READY

## Summary

Adds a pure leaf module `eval/root_cause.py` (the `classify_fact_gap` predicate +
`rollup` over a record's `per_fact`) and wires it into both consumers — a new dedicated
"Root-Cause Attribution" section in `report.py` (SC-2) and an additive
`attribute_root_cause` capability on `failure_taxonomy.py` (SC-3). The change is
strictly additive: the 5-label cascade, `FailureMode` members, `is_*` helpers, and the
7-column category table are untouched. `make lint test` is green (345 passed) and the
code-reviewer found no blocking issues. All 15 acceptance criteria are met.

## Mechanical Checks

| Step   | Status | Notes                                                                 |
| ------ | ------ | --------------------------------------------------------------------- |
| Format | PASS   | `ruff format --check` + prettier — 137 files already formatted        |
| Lint   | PASS   | `ruff check src tests` — all checks passed                            |
| Tests  | PASS   | 345 passed, 17 deselected in ~19s; `test_root_cause.py` (9) all green |

Scope note: `origin/main...HEAD` is empty (phase reached `/review` pre-commit, per SDD).
Review ran against the **working tree** — `git diff HEAD` + untracked `root_cause.py` /
`test_root_cause.py`.

## Issues

No blocking issues. Both non-blocking observations from the code-reviewer were **fixed on
this branch**.

<details>
<summary>✅ FIXED — Degraded-rollup invariant now fully documented — `root_cause.py:60-71`</summary>

The `per_fact=None` path returns `RootCauseRollup(has_per_fact=False)`, so both the
degraded case and the "some facts failed" case carry `no_failed_facts=False`; the
distinction rides entirely on `has_per_fact`. The class docstring previously stated only
the positive ("`no_failed_facts` True iff evidence exists but zero facts failed").

**Fix applied:** the `RootCauseRollup` docstring now states the corollary explicitly —
`no_failed_facts` is False whenever `has_per_fact=False` (degraded, flag meaningless), so
`has_per_fact` is the sole degraded-vs-failed discriminator — and notes that the report
re-derives "zero gaps" from `denom == 0` rather than reading the flag.

</details>

<details>
<summary>✅ FIXED — `no_failed_facts` lack-of-consumer documented in code + KB — `root_cause.py:60-71`</summary>

Neither `report.py` nor `failure_taxonomy.py` reads `no_failed_facts`; the report
re-derives the `0.0%` decision from `denom == 0`. The field is correct per FR-2 and is a
forward-looking hook for a future per-record breakdown.

**Fix applied:** the rationale is now captured both in the `RootCauseRollup` docstring and
in the `observability` KB (quick-reference Common Pitfalls + the failure-taxonomy concept),
so the field's purpose and the report's re-derivation are no longer implicit.

</details>

## Acceptance Criteria

| #   | Criterion                                                | Status | Evidence                                                                          |
| --- | -------------------------------------------------------- | ------ | --------------------------------------------------------------------------------- |
| 1   | `present` → `None`                                       | ✅     | `test_present_fact_returns_none`                                                  |
| 2   | failed + `doc_id None` → `retrieval_gap` (both verdicts) | ✅     | `test_failed_fact_none_doc_is_retrieval_gap` (parametrized)                       |
| 3   | failed + retrieved doc → `generation_gap`                | ✅     | `test_failed_fact_retrieved_doc_is_generation_gap`                                |
| 4   | defensive: non-None out-of-set → `retrieval_gap`         | ✅     | `test_failed_fact_out_of_set_doc_is_retrieval_gap_defensive`                      |
| 5   | output domain over verdict × membership matrix           | ✅     | `test_output_domain_over_matrix`                                                  |
| 6   | rollup counts + `no_failed_facts` semantics              | ✅     | `test_rollup_counts_mixed_facts`, `test_rollup_zero_failed_facts_*`               |
| 7   | `per_fact=None` degrades (distinct from zero-gaps)       | ✅     | `test_rollup_per_fact_none_degrades`                                              |
| 8   | `generate_report_data` has `root_cause` key + split      | ✅     | `test_root_cause_key_in_report_data`                                              |
| 9   | both renderers emit dedicated block; 7-col table intact  | ✅     | `test_root_cause_section_rendered_md_and_html`                                    |
| 10  | N/A vs 0.0% rendered distinctly                          | ✅     | `test_root_cause_na_vs_zero_pct`                                                  |
| 11  | taxonomy-surface attribution (SC-3)                      | ✅     | `test_attribute_root_cause_at_taxonomy_surface`                                   |
| 12  | no reclassification — cascade byte-identical             | ✅     | `test_classify_unchanged_no_reclassification`                                     |
| 13  | `aggregate.py` unmodified; 5 members; no new ADR         | ✅     | verified: no diff on `aggregate.py`, `len(FailureMode)==5`, no `docs/adr/` change |
| 14  | `test_root_cause.py` exists, offline, reuses fixtures    | ✅     | pure-Python factories, no network/LLM mock                                        |
| 15  | `make lint test` green                                   | ✅     | 345 passed                                                                        |

## KB Staleness

KB sync was **applied on this branch** as part of the phase (per the `/review` on-branch
convention) — not deferred to post-merge.

| KB File                                                      | What Changed                                                                                      | Impact                                                         | Action taken                                                                                                                   |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `observability/patterns/failure-classifier-cascade.md`       | New leaf `root_cause.py` consumed by the taxonomy surface                                         | Pattern didn't mention the per-fact root-cause leaf            | ✅ Applied — added "Per-Fact Root-Cause Attribution" section + `attribute_root_cause` entry point + `root_cause.py` in Sources |
| `observability/concepts/failure-taxonomy.md`                 | New additive `attribute_root_cause` capability + per-fact `retrieval_gap`/`generation_gap` signal | Concept presented the taxonomy as answer-level aggregates only | ✅ Applied — additive section; explicit that the 5-label `classify()` cascade is unchanged                                     |
| `observability/index.md`, `observability/quick-reference.md` | Discoverability of the new material; stale "per-fact detail excluded from `EvalRecord`" invariant | Lookup tables/invariants out of date                           | ✅ Applied — root-cause lookup table, Common Pitfalls row, corrected invariant                                                 |
| `.claude/kb/_index.yaml`                                     | Domain description + `last_updated`                                                               | Registry currency                                              | ✅ Applied — bumped to 2026-06-17                                                                                              |

## Knowledge Capture

| What was learned                                                                                                                                                                                                                      | KB domain       | Action taken                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ----------------------------------------------------------------- |
| The real per-fact root-cause signal is `supporting_doc_id` None-vs-non-None on a **failed** fact — a non-None set-intersection is tautological because phase-1's FR-5 guard collapses out-of-set doc ids to `None` before persistence | `observability` | ✅ Applied on branch (failure-taxonomy concept + cascade pattern) |
| Null-discipline at the report seam: degraded (`per_fact=None`) → N/A vs "evidence, zero gaps" → 0.0%, derived via `any_evidence` flag + `denom == 0`, never collapsing a missing signal to "zero"                                     | `observability` | ✅ Applied on branch (quick-reference + concept)                  |

## ADR

None. Per AC-13 / FR-5 the change is additive — no architectural decision was made (the
Option-2c redefinition of `is_retrieval_miss` and any ADR-0008 amendment remain a
deferred backlog item). No new ADR required.

## Suggested Next Steps

The KB sync and both non-blocking nits are already applied on this branch. Remaining:

1. **Commit** the phase as one unit — code + tests + KB + REVIEW.md — in Conventional
   Commits format, e.g.
   `feat(sprint-8/phase-2): per-fact root-cause attribution (retrieval_gap vs generation_gap)`,
   then open the PR.
