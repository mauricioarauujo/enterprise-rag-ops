# BRAINSTORM: sprint-3-phase-9-dashboard — Streamlit Dashboard

**Sprint/Phase:** sprint-3 / phase-9 | **Date:** 2026-06-01

---

## Problem Statement

Sprint 3's exit criterion is: "a reviewer can click a failed trace, see WHY it failed
(retrieval miss vs hallucination vs format)." Arize Phoenix — already deployed and
populated by `rag-export-traces` — satisfies the per-trace drill-down half of that bar
out of the box. The question this phase must answer is: what does a custom Streamlit
dashboard add that Phoenix does not, and where exactly does the boundary sit?

The honest answer is that the gap Streamlit fills is the **aggregate / cross-model
story**: cost rollups, failure-mode breakdown by category, and side-by-side model
comparison, all readable from `results/*.jsonl` with no container running. Phoenix has
no built-in "failure mode by category" pivot or multi-run cost comparison. Streamlit
fills that gap while the cloneable-results principle (ADR-0004) rules out building a
dashboard that requires Phoenix to be up.

---

## Suggested Research & KB Work

| Topic                                                                | Coverage                                    | Action                                                                                                                                             |
| -------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Streamlit basics (layout, `st.dataframe`, `st.bar_chart`, `st.tabs`) | Thin — not in KB                            | No dedicated KB entry needed; Streamlit is simple enough for inline context7 lookup at impl time. Do NOT write a KB domain for a ~5h phase's tool. |
| `generate_report_data()` reuse contract                              | Sufficient — readable in `eval/report.py`   | None needed; grounded by direct code read.                                                                                                         |
| Phoenix deep-link URL format (span/trace IDs)                        | Thin                                        | Verify at impl time: `http://localhost:6006/projects/{project}/spans/{span_id}`. If unstable, omit deep-links from MVP.                            |
| Failure taxonomy + EvalRecord schema                                 | Sufficient — KB `observability/` + ADR-0008 | None needed.                                                                                                                                       |

No `--deep-research` needed. Streamlit dashboard over JSONL is well-understood
territory and the data layer already exists.

---

## Approaches Considered

| Approach                                                       | Phoenix role                                                                                                            | Streamlit role                                                                                                                                      | Data source                                                     | "Click a failed trace → why"                                                                                                                        | Effort |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **A. Aggregate-only Streamlit + Phoenix for drill-down**       | Owns per-trace explorer (already works). Reviewer opens Phoenix manually for span detail.                               | Aggregate views only: cost rollups, failure-mode bar chart, model comparison table. Deep-link buttons open Phoenix for the selected trace/question. | Pure JSONL — no Phoenix required to render the dashboard.       | Met by Phoenix (already deployed). Dashboard adds the "which models fail more at retrieval miss in category X" story that Phoenix lacks.            | S      |
| **B. Minimal static dashboard (no Phoenix dependency at all)** | Not referenced. Dashboard shows aggregates + a per-question table with failure_mode, metrics. No trace drill-down link. | Aggregate + per-question table. Failure mode is a plain string column; reviewer reads metrics directly.                                             | Pure JSONL.                                                     | Partially met: reviewer sees WHAT failed (failure_mode tag) but no span-level WHY. Sprint exit criterion is arguably not fully met without Phoenix. | XS     |
| **C. Phoenix-query dashboard (Streamlit queries Phoenix API)** | Phoenix is the data source. Streamlit queries Phoenix REST/gRPC for spans, scores.                                      | Richer trace explorer within Streamlit: span tree, attribute display.                                                                               | Phoenix running required. Violates cloneable-results principle. | Fully met within Streamlit — but at the cost of a Phoenix dependency and significant impl complexity.                                               | L      |

---

## Recommended Approach

**Approach A** — aggregate-only Streamlit that deep-links to Phoenix for per-trace
detail.

Rationale:

1. **Exit criterion coverage.** Phoenix already satisfies "click a failed trace → see
   WHY." Approach A formalises this by adding deep-link buttons from the aggregate view
   into Phoenix for the traces that failed. The reviewer flow becomes: open Streamlit →
   see the failure-mode breakdown → click a retrieval-miss row → Phoenix opens at that
   span. No duplication of Phoenix's trace explorer in Streamlit.

2. **Cloneable principle preserved.** The dashboard renders from JSONL; Phoenix need
   not be running to view cost rollups or failure charts. A reviewer who does `git clone`
   and `make dash` sees real numbers immediately. Phoenix is opt-in for drill-down.

3. **5h budget is respected.** The data layer (`generate_report_data`, `EvalRecord`,
   `failure_mode` field) already exists and is tested. Streamlit is a thin presentation
   layer on top — four or five `st.tabs` wrapping existing aggregations. Approach B
   underdelivers on the exit criterion; Approach C blows the budget.

4. **Division of labour is explicit and non-duplicating.** Phoenix = per-span trace
   tree, OpenInference attributes, score annotations. Streamlit = aggregate metrics,
   failure distribution charts, model-vs-model comparison, cost totals — the cross-run
   story Phoenix does not tell.

**Deep-link caveat:** Phoenix's internal URL format for spans may not be stable across
versions. If at impl time the deep-link URL is unreliable, drop the deep-link buttons
silently — Approach A degrades gracefully to Approach B without changing the aggregate
views.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                                                                                                                                                                                                                           |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | Streamlit app (`src/enterprise_rag_ops/dashboard/app.py`) that reads one or more `results/*.jsonl` files and renders: (1) summary metrics table (fact recall, precision, faithfulness, abstention, cost — reusing `generate_report_data`), (2) failure-mode bar chart (counts per FailureMode label, per model), (3) cost rollup table (total cost USD, mean latency, total tokens per model). |
| Must     | `make dash` Makefile target (launches `streamlit run`) — the reviewer's entry point.                                                                                                                                                                                                                                                                                                           |
| Must     | `streamlit` added to `pyproject.toml` dependencies (plus `altair` or `plotly` only if already pulled in by Streamlit's own deps — no extra charting lib).                                                                                                                                                                                                                                      |
| Should   | Per-category failure-mode breakdown (heatmap or grouped bar: category x failure mode). This is the data Phoenix cannot show and directly demonstrates the eval harness's value.                                                                                                                                                                                                                |
| Should   | Multi-run selector: if multiple JSONL files exist in `results/`, a sidebar dropdown lets the reviewer pick which run(s) to display. Single-run is the fallback default.                                                                                                                                                                                                                        |
| Should   | Deep-link buttons from a failed-question row to Phoenix (`http://localhost:6006/…`) — shown only when Phoenix is running (verified by a lightweight health check or simply documented as opt-in).                                                                                                                                                                                              |
| Could    | A static screenshot (`docs/dashboard-screenshot.png`) committed to the repo so reviewers who do not run the app still see it in the README.                                                                                                                                                                                                                                                    |
| Could    | `make dash-screenshot` target using Playwright headless capture — only if time allows after the above.                                                                                                                                                                                                                                                                                         |
| Won't    | Rebuild Phoenix's per-trace span explorer in Streamlit. Phoenix already does this; duplicating it violates the division-of-labour principle and burns the budget.                                                                                                                                                                                                                              |
| Won't    | Real-time streaming data or websocket connections. Dashboard reads static JSONL.                                                                                                                                                                                                                                                                                                               |
| Won't    | Authentication, user accounts, or any deployment beyond `localhost`.                                                                                                                                                                                                                                                                                                                           |
| Won't    | A second Docker container or docker-compose service for the dashboard. `make dash` runs the Streamlit dev server directly via `uv run`.                                                                                                                                                                                                                                                        |
| Won't    | Custom CSS theming or fancy frontend beyond Streamlit defaults. The roadmap explicitly gates this: "CLI + minimal Streamlit only."                                                                                                                                                                                                                                                             |
| Won't    | Querying Phoenix's API from Streamlit. Data source is JSONL only.                                                                                                                                                                                                                                                                                                                              |

---

## Open Questions

1. **Deep-link URL stability.** What is the Phoenix v15 per-span URL format, and is it
   stable enough to hard-code in the dashboard? (`/projects/{project}/spans/{span_id}`?
   `/traces/{trace_id}`?) If it changes between Phoenix versions, deep-links should be
   omitted or hidden behind a feature flag rather than causing broken links for reviewers.

2. **Multi-run vs single-run default.** The two existing JSONL files
   (`baseline.jsonl`, `baseline-anthropic.jsonl`) are separate single-model runs. Should
   the dashboard load all `results/*.jsonl` by default and union the records (treating
   `run_id` + `gen_ai.request.model` as the grouping key), or should the reviewer
   explicitly pick one file? Unioning simplifies the "model comparison" story but risks
   showing mixed run_ids in misleading ways if the eval parameters differed.

3. **Streamlit entry point location.** Should the app live at
   `src/enterprise_rag_ops/dashboard/app.py` (inside the package, importable) or as a
   top-level `dashboard/app.py` (outside the package, simpler but inconsistent with the
   module layout)? The `make dash` target can point either way; this affects whether
   `streamlit` becomes a hard runtime dependency or an optional extra in `pyproject.toml`.

4. **Screenshot in README.** Is a committed screenshot (`docs/` or `assets/`) required
   for the portfolio signal, given that reviewers cloning the repo will not have
   `results/` data without running the full eval? If yes, the screenshot becomes a Must
   item and a `make dash-screenshot` target enters scope.

---

## Infrastructure Gaps

- `streamlit` is not yet a dependency — must be added to `pyproject.toml` (main or an
  `[optional-dependencies]` extra group named `dashboard`).
- `make dash` target does not exist — must be added to `Makefile`.
- A `src/enterprise_rag_ops/dashboard/` module directory (with `__init__.py` +
  `app.py`) must be created. No existing test file for it — `tests/dashboard/` will be
  needed (at minimum a smoke import test).

---

## Next Step

→ `/define sprint-3-phase-9-dashboard`
