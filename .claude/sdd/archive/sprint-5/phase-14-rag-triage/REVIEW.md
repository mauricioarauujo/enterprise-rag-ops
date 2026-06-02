# Review: sprint-5/phase-14-rag-triage — rag-triage Core

**Branch:** `sprint-5/phase-14-rag-triage` | **Date:** 2026-06-01 | **Verdict:** ✅ READY

## Summary

A pure, offline groupby-aggregate over the classified eval JSONL plus the `rag-triage`
CLI. Implemented via `agy` (Antigravity/Gemini) against the `DESIGN.md` contract; reviewed
in Claude Code with the `code-reviewer` agent (sonnet). The core logic was correct on
first pass — the only findings were test-fidelity (two tests gave false confidence) and
three nits, all now fixed. All 16 ACs are met and the gate is green.

## Mechanical Checks

| Step   | Status | Notes                                            |
| ------ | ------ | ------------------------------------------------ |
| Format | PASS   | `make format` (auto-applied; pre-commit hook)    |
| Lint   | PASS   | `ruff format --check` + `ruff check` + prettier  |
| Tests  | PASS   | `make lint test` — **244 passed, 17 deselected** |

## Issues

All issues from the `code-reviewer` pass were resolved in commit (review-fixes). None were
blocking.

<details>
<summary>⚠️ AC-13 determinism test only proved serializer idempotency — <code>test_triage.py</code></summary>

The test called `compute_triage` once and serialized the same report twice — proving
`_report_to_dict` is idempotent on a frozen dataclass (trivially true), not that two
independent `compute_triage` passes produce byte-identical JSON (the real risk: dict/set
iteration-order leaking across invocations). **Fixed:** now runs two independent
`compute_triage(records, gold)` calls and compares `json.dumps(...)` of each. (The output
is structurally deterministic anyway — the `clusters.sort(...)` at `triage.py:110`
dominates insertion order — but the test now actually falsifies the claim.)

</details>

<details>
<summary>⚠️ AC-15 offline guarantee was a tautology — <code>test_triage.py</code></summary>

The original test just asserted `compute_triage` runs on in-memory objects — it would pass
even if `triage.py` imported `openai` at the top. **Fixed:** the test now imports
`enterprise_rag_ops.eval.triage` in a **clean subprocess** and asserts `openai` is not in
`sys.modules` — a falsifiable check that the pure core's import graph constructs no LLM
client. (An in-process `sys.modules` check was rejected: `test_openai_judge.py` sorts
before `test_triage.py`, so `openai` is already imported in the shared pytest process. The
`requests`/`httpx` checks were dropped — those are pulled legitimately by `datasets` via
the `Question` type import in `questions.py`, not by any triage network use.)

</details>

<details>
<summary>💬 AC-14 stored <code>exit_code</code> but never asserted it — <code>test_triage.py</code></summary>

The dry-run test asserted stdout content and "no file written" but never checked the
exit code AC-14 requires. **Fixed:** added `assert exit_code == 0`.

</details>

<details>
<summary>💬 Redundant <code>list()</code> wrapping — <code>triage.py:90,113</code></summary>

`sorted(list(set(...)))` — `sorted()` takes any iterable; the `list()` is a no-op and
the DESIGN spelled it `sorted({...})`. **Fixed:** both sites now use a set comprehension
`sorted({r.gen_ai.request.model for r in ...})`.

</details>

<details>
<summary>💬 <code>json.dump</code> missing explicit <code>sort_keys=False</code> — <code>triage_cli.py:136</code></summary>

Default is `False`, so output was already deterministic (controlled by `_report_to_dict`'s
fixed key order). **Fixed:** added `sort_keys=False` explicitly so the fixed-order intent
is self-documenting and a future `sort_keys=True` edit (which would silently reorder keys
and break Phase 15's schema assertions) is an obvious regression.

</details>

## Acceptance Criteria

| AC    | Status | Evidence                                                                  |
| ----- | ------ | ------------------------------------------------------------------------- |
| AC-1  | ✅     | `test_ac1_and_ac3_cluster_key_count_rate` — one cluster per `(fm,cat)`    |
| AC-2  | ✅     | `test_ac2_record_category_authoritative` — record's category wins         |
| AC-3  | ✅     | `test_ac1_and_ac3...` — `rate==c/N`; counts sum to N                      |
| AC-4  | ✅     | `test_ac4_empty_input` — empty report, no `ZeroDivisionError`             |
| AC-5  | ✅     | `test_ac5_sort_and_tiebreak` — count desc, `(fm,cat)` asc tiebreak        |
| AC-6  | ✅     | `test_ac6_dominant_cluster` — `dominant == clusters[0]`                   |
| AC-7  | ✅     | `test_ac7_representative_determinism` — lexicographic-min `question_id`   |
| AC-8  | ✅     | `test_ac8_missing_gold_representative` — `""` when id absent from gold    |
| AC-9  | ✅     | `test_ac9_fail_fast_on_unclassified` — `ValueError` names first offender  |
| AC-10 | ✅     | `test_ac10_models_seen` — sorted-unique at cluster + report scope         |
| AC-11 | ✅     | `test_ac11_schema_version` — constant present in serialized output        |
| AC-12 | ✅     | `test_ac12_json_shape_and_atomic_write` — shape + temp-file cleanup       |
| AC-13 | ✅     | `test_ac13_deterministic_bytes` — **two independent passes** byte-equal   |
| AC-14 | ✅     | `test_ac14_stdout_summary_dry_run` — table printed, no file, exit 0       |
| AC-15 | ✅     | `test_ac15_offline_guarantee` — **subprocess import: no LLM client**      |
| AC-16 | ✅     | `test_ac16_console_script_and_help` + verified `uv run rag-triage --help` |

## KB Staleness

None. Changed files map to `rag-eval` (`eval-record-schema`) and `observability`
(`failure-taxonomy`). Both concepts were read against the diff: triage **consumes** the
documented `EvalRecord` fields (`failure_mode`, `category`, `gen_ai.request.model`) and the
5-label taxonomy as produced strings — it changes no API, enum, or constraint either
domain documents. The `eval-triage` cluster→issue contract remains correctly **deferred to
Phase 15** (lands with `/update-kb rag-eval` after ADR-0009), per the SPRINT knowledge plan.

## ADR

None for Phase 14 — it reuses confirmed schemas and house patterns and introduces no new
architectural seam. The schema/issue-drafting decision is **ADR-0009, owned by Phase 15**
(per BRAINSTORM + DEFINE dependency table).

## Suggested Next Steps

1. **Open the PR** for `sprint-5/phase-14-rag-triage` → `main` (CI re-runs `make lint test`
   - smoke).
2. Proceed to **`/brainstorm sprint-5/phase-15-triage-to-issues`** — the action-loop
   payoff phase that consumes `triage.json` (the `schema_version="1.0"` contract this phase
   established) and writes **ADR-0009**.
3. _(Personal)_ Nudge the Carreira-repo track `estudos/enterprise_rag_ops/sprint-5.md` —
   Phase 14 shipped.
