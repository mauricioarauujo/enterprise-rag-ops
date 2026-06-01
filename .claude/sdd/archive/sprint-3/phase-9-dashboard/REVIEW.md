# Review: sprint-3-phase-9-dashboard — Streamlit Aggregate Dashboard

**Branch:** `sprint-3/phase-9-dashboard` | **Date:** 2026-06-01 | **Verdict:** ✅ READY

## Summary

A minimal Streamlit dashboard over the eval JSONL — summary metrics, failure-mode
distribution, cost rollups, and a category × failure-mode breakdown — rendered from the
git-tracked `results/baseline.jsonl` with no Phoenix container required. The data/render
split is honoured (pure `data.py` is the test surface; `app.py` is a guarded shell), the
reuse contract holds (`summary_rows`/`cost_rows` delegate to `generate_report_data`), and
the cloneable principle (ADR-0004) is intact. Implemented via Antigravity/Gemini against
`DESIGN.md`, reviewed + polished + gate-verified in Claude Code. The three cheap review
fixes are applied; remaining items are documented non-blocking follow-ups.

## Mechanical Checks

| Step   | Status | Notes                                             |
| ------ | ------ | ------------------------------------------------- |
| Format | PASS   | pre-commit `make format` clean                    |
| Lint   | PASS   | ruff (src + tests)                                |
| Tests  | PASS   | 218 passed, 17 deselected (9 new dashboard tests) |

## Issues

<details>
<summary>⚠️ <code>phoenix_trace_url</code> used a fragile <code>[:-10]</code> slice — FIXED</summary>

`data.py:128` — the `/v1/traces` strip used a hard-coded slice length, fragile to a
path-prefixed endpoint. **Fixed:** replaced with `str.removesuffix("/v1/traces")`
(Python 3.12 available), self-documenting and length-agnostic.

</details>

<details>
<summary>⚠️ <code>question_id</code> is structurally a no-op in <code>phoenix_trace_url</code> — documented, deferred</summary>

`data.py:108,130` — the deep-link is project-scoped, so every failed-row link resolves to
the same Phoenix project page, not a per-question trace (FR-11 is "per-question" in intent
only). This is intentional per DESIGN (Phoenix v15 per-trace URL shape unverified). **Fixed
the lost-intent risk:** added `# TODO(FR-11)` at `data.py:130` marking `question_id` as the
one-line seam for when the URL shape is confirmed. No behavioural change now.

</details>

<details>
<summary>⚠️ <code>test_single_model_structure</code> (AC-5) had a vacuous <code>len(dist) &lt;= 1</code> assertion — FIXED</summary>

`tests/dashboard/test_data.py` — the test could pass without exercising the zero-fill path
if the chosen model had all-`None` failure modes. **Fixed:** now selects a model guaranteed
to have a classified record and asserts `list(dist.keys()) == [target_model]` and 5-label
zero-fill (`== 1`, not `<= 1`).

</details>

<details>
<summary>⚠️ Empty-JSONL crashes the app (uncaught <code>ValueError</code>) — non-blocking follow-up</summary>

`app.py` Summary/Cost tabs — `generate_report_data` raises `ValueError` on an empty file;
a user who selects an empty `results/run2.jsonl` in the sidebar crashes the app. Out of the
current Must scope (only `baseline.jsonl` is tracked, and it is non-empty). **Follow-up:**
wrap the per-path `summary_rows`/`cost_rows` calls in `try/except ValueError` → `st.info`.
Not gating.

</details>

<details>
<summary>⚠️ Mixed-classification edge cases untested — non-blocking</summary>

`tests/dashboard/test_data.py` — no test covers a model whose records are all
`failure_mode=None` (such a model is correctly absent from the distribution). The committed
baseline has all records classified, so the case can't arise today. Worth a synthetic-record
test if a partially-classified run ever ships. Not gating.

</details>

## Acceptance Criteria

| AC    | Status | Evidence                                                                                      |
| ----- | ------ | --------------------------------------------------------------------------------------------- |
| AC-1  | PASS   | Headless launch (`PHOENIX_COLLECTOR_ENDPOINT` empty) → `/_stcore/health` = ok, no traceback   |
| AC-2  | PASS   | `test_summary_rows_equal_report` — identity vs `generate_report_data["summary"]`              |
| AC-3  | PASS   | `test_failure_mode_distribution_totals` — 5-label zero-fill, per-model totals                 |
| AC-4  | PASS   | `test_cost_rows_equal_report` + `format_cost(None) == "N/A"`                                  |
| AC-5  | PASS   | `test_single_model_structure` (strengthened to non-vacuous `== 1`)                            |
| AC-6  | PASS   | `test_data_module_no_streamlit` (subprocess: streamlit not in sys.modules) + app smoke import |
| AC-7  | PASS   | `make dash` in `.PHONY` + help; `streamlit>=1.40` resolves                                    |
| AC-8  | PASS   | `test_category_failure_distribution`                                                          |
| AC-9  | PASS   | `test_load_run_records_union` — concatenation + order preserved                               |
| AC-10 | PASS   | `test_phoenix_url_off` — `None` when unset; valid URL (incl. `/v1/traces` strip) when set     |
| AC-11 | PASS   | `make dash` uses `uv run streamlit run` only; no second container                             |

## Knowledge Capture Suggestions

| What was learned                                                                                                                                                                                                                                                                                                                                                                                    | Suggested KB domain | Action                                                                                                                                                              |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The **aggregate-dashboard ↔ Phoenix division of labour**: Phoenix owns per-trace drill-down; a Streamlit dashboard over the cloneable JSONL owns the aggregate/cross-model story (failure-mode-by-category, cost rollups). The boundary, and _why_ the dashboard reads JSONL not the Phoenix API (cloneable-from-clone, NFR), is now load-bearing and will be referenced by Sprint 4 (README/blog). | `observability`     | `/update-kb observability` — add a thin **`dashboard-phoenix-boundary`** pattern (≤ pattern line budget). Proposed, not yet applied — see Harness suggestion below. |

## KB Staleness

None. The diff consumes existing APIs unchanged (`generate_report_data`, `FailureMode`,
`EvalRecord`, `PHOENIX_COLLECTOR_ENDPOINT`) — no API/enum/constraint the `rag-eval` or
`observability` KB documents was altered.

## ADR

No new ADR. The dashboard is a presentation layer over decisions already recorded:
ADR-0004 (Phoenix tool + cloneable-JSONL-as-SSoT, Phase 1–3 rollout), ADR-0007 (eval-record
schema), ADR-0008 (failure taxonomy). The "don't rebuild Phoenix's explorer" decision flows
directly from ADR-0004's phased-rollout rationale — DESIGN concluded the same.

## Suggested Next Steps

1. **Open the PR** for `sprint-3/phase-9-dashboard` → `main` (squash; the branch is one
   logical change). This is the last phase of Sprint 3 → `/sprint-close` follows after merge.
2. **(Optional, before PR)** Apply the thin `/update-kb observability` boundary pattern if
   you want the KB current at merge; otherwise fold it into `/sprint-close`'s knowledge loop.
3. **Deferred follow-ups** (not gating, track for Sprint 4 polish): empty-JSONL guard in the
   render tabs; per-trace Phoenix deep-link once the v15 URL shape is confirmed (seam already
   marked at `data.py:130`).
