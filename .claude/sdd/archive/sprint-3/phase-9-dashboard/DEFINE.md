# DEFINE: sprint-3-phase-9-dashboard — Streamlit Aggregate Dashboard

**Sprint/Phase:** sprint-3 / phase-9 | **Date:** 2026-06-01

> Stage 1 (DEFINE) for the phase. Turns the BRAINSTORM Approach A + MoSCoW into testable
> requirements. All five orchestrator decisions (Approach A, cloneable-results,
> single-model default, optional deep-links, screenshot-as-Could) are baked in below and
> are **not re-opened** here.

---

## Context & Boundary (resolved, not re-litigated)

- **Approach A is chosen.** Aggregate-only Streamlit reading `results/*.jsonl`. Phoenix
  owns per-trace drill-down; the dashboard does **not** rebuild Phoenix's span explorer.
- **Reuse contract.** `eval/report.py::generate_report_data(jsonl_path: Path) -> dict`
  already returns `{k, summary, categories, costs}` — summary metrics (fact recall /
  precision / faithfulness / abstention) and the cost rollup (`costs`: total_cost,
  mean_latency, total_tokens per model) are produced there. The dashboard **reuses** this;
  it must not reimplement aggregation. **Gap:** `generate_report_data` does **not** pivot
  `failure_mode`, so the failure-mode distribution is a **new pure function** that reads
  the `failure_mode` field already present on each `EvalRecord`.
- **Cloneable-results is intact.** `results/baseline.jsonl` is git-tracked (`.gitignore`
  lines 60–63 negate only `baseline.html`, `baseline.md`, `baseline.jsonl`). A fresh
  `git clone` + `make dash` must render real numbers with **no eval re-run and Phoenix not
  running**.

---

## Requirements

### Functional

Each FR is testable and tagged with its MoSCoW level.

| FR    | MoSCoW | Requirement                                                                                                                                                                                                                                                                                                           |
| ----- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-1  | Must   | **Load + parse.** Discover the `results/*.jsonl` file(s) to display and parse them into `EvalRecord`s, reusing `generate_report_data(jsonl_path)` for summary/cost/category aggregation. Default selection = all git-tracked JSONL in `results/` (today: `baseline.jsonl` only).                                      |
| FR-2  | Must   | **Summary-metrics view.** Render per-model fact recall, fact precision, faithfulness, abstain precision, abstain recall — sourced from `generate_report_data(...)["summary"]`. No metric is recomputed in the dashboard layer.                                                                                        |
| FR-3  | Must   | **Failure-mode distribution view.** Render counts per `FailureMode` label (the 5 StrEnum values), per model, read from the `failure_mode` field already on each record. This pivot lives in a **new pure function** in the dashboard data module (it is not produced by `generate_report_data`).                      |
| FR-4  | Must   | **Cost rollup.** Render total cost (USD), mean latency, total tokens per model — sourced from `generate_report_data(...)["costs"]`. `None` total_cost (missing price) renders as `N/A`, never `0`.                                                                                                                    |
| FR-5  | Must   | **Graceful single-run behaviour.** With exactly one JSONL present (the committed `baseline.jsonl`), every view renders a coherent single-model summary. The multi-model comparison view must degrade to a single-model display — no error, no empty/broken comparison widget.                                         |
| FR-6  | Must   | **Testability seam.** All JSONL → view-model transformation (dicts / DataFrames) lives in **pure, importable, non-Streamlit functions** in `dashboard/data.py`. These take paths/records as input and return plain data structures, with **zero** `import streamlit` at module load. `app.py` is a thin render shell. |
| FR-7  | Must   | **`make dash` entry point.** A `make dash` target launches the app via `uv run streamlit run <app path>`. Added to `.PHONY` and `help`.                                                                                                                                                                               |
| FR-8  | Must   | **`streamlit` dependency.** Add `streamlit` to `pyproject.toml`. No extra charting library is added unless it is already pulled transitively by Streamlit (`altair` ships with Streamlit; `pandas` is already a direct dep).                                                                                          |
| FR-9  | Should | **Per-category failure-mode breakdown** (category × failure-mode counts) — the cross-cut Phoenix cannot show. Pure function in `dashboard/data.py`, rendered as a grouped/bar or table view.                                                                                                                          |
| FR-10 | Should | **Multi-run selection.** When >1 JSONL exists in `results/`, a sidebar control lets the reviewer pick which run(s) to display. Single-run remains the default fallback (FR-5). Grouping key for union is a `/design`-level decision (see Open Questions).                                                             |
| FR-11 | Should | **Phoenix deep-links.** Per failed-question or per-failure-mode row, an opt-in link to Phoenix. Shown only when Phoenix is reachable; absent/disabled otherwise (see NFR-4). Never blocks any Must view.                                                                                                              |
| FR-12 | Could  | **Committed screenshot** (`docs/dashboard-screenshot.png` or `assets/`) embedded in the README for reviewers who do not run the app. Does **not** pull a Playwright/headless-capture target into Must scope.                                                                                                          |
| FR-13 | Could  | **`make dash-screenshot`** headless-capture target — only if time remains after all Must + Should.                                                                                                                                                                                                                    |

**Won't (this phase):** rebuild Phoenix's per-trace span explorer; query the Phoenix API
as a data source; real-time/streaming data; auth or non-localhost deployment; a second
Docker container / compose service for the dashboard; custom CSS theming beyond Streamlit
defaults. (Verbatim from BRAINSTORM § Scope Won't.)

### Non-functional

| NFR   | Requirement                                                                                                                                                                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NFR-1 | **Cloneable from a fresh clone.** `git clone` + `make dash` renders real numbers from the committed `results/baseline.jsonl` with no eval re-run. (ADR-0004 cloneable-results principle.)                                                   |
| NFR-2 | **No Phoenix required to render.** Every Must view renders with the Phoenix container stopped. Phoenix is opt-in for drill-down only.                                                                                                       |
| NFR-3 | **Budget / minimal-Streamlit-only.** ~5h phase. Honour the roadmap guard "CLI + minimal Streamlit only" — no frontend framework, no custom CSS/theming, no charting lib beyond what Streamlit ships. Every Must FR is justified vs. budget. |
| NFR-4 | **Graceful Phoenix deep-link degradation.** If the Phoenix URL format is unreliable or Phoenix is down, the dashboard still works and simply omits/disables the links (degrades Approach A → Approach B). Broken links must never render.   |
| NFR-5 | **8 GB-hardware budget / no second container.** `make dash` runs the Streamlit dev server directly via `uv run` — no extra Docker container or compose service. Must coexist with an 8 GB dev box.                                          |
| NFR-6 | **Determinism of data layer.** Given the same JSONL input, `dashboard/data.py` functions return identical structures (no wall-clock / RNG / network), so they are unit-testable against `results/baseline.jsonl`.                           |

---

## Acceptance Criteria

Acceptance favours what a Streamlit phase **can** actually verify: the pure data-prep
functions (unit-testable) and a smoke import of the app shell. The app's visual rendering
is validated by a manual launch check, not by unit tests.

| AC    | Maps to      | Criterion                                                                                                                                                                                                                                                                                     |
| ----- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1  | FR-1, NFR-1  | With only `results/baseline.jsonl` present and Phoenix stopped, `make dash` launches the app and all three Must views (summary, failure-mode, cost) render without error.                                                                                                                     |
| AC-2  | FR-2         | A `dashboard/data.py` function returns the per-model summary rows (fact recall / precision / faithfulness / abstain precision / recall) for `baseline.jsonl`, and a unit test asserts the values equal `generate_report_data(...)["summary"]` (proves reuse, not reimplementation).           |
| AC-3  | FR-3         | A pure function `failure_mode_distribution(records) -> {model: {FailureMode: count}}` returns counts whose total per model equals the record count for that model, covers all 5 `FailureMode` labels (zero-filled), and a unit test asserts this on `baseline.jsonl`.                         |
| AC-4  | FR-4         | A `dashboard/data.py` function returns cost-rollup rows equal to `generate_report_data(...)["costs"]`; a unit test asserts `total_cost=None` renders/serialises as `N/A` (not `0`).                                                                                                           |
| AC-5  | FR-5         | A unit test feeds a single-model record set to the comparison data function and asserts it returns a valid single-model structure (no exception, no empty frame). Manual: the comparison view shows a single-model summary, not a broken widget.                                              |
| AC-6  | FR-6, NFR-6  | `import enterprise_rag_ops.dashboard.data` succeeds with **no** `streamlit` import triggered; all `data.py` functions are pure (path/records in, plain data out). A smoke test imports the `app` module without launching the server (guarded so `streamlit run` is the only execution path). |
| AC-7  | FR-7, FR-8   | `make dash` exists in `.PHONY` + `help`; `streamlit` resolves after `uv sync`; `uv run streamlit --version` succeeds.                                                                                                                                                                         |
| AC-8  | FR-9         | (Should) `category_failure_distribution(records)` returns category × failure-mode counts; unit-tested on `baseline.jsonl`.                                                                                                                                                                    |
| AC-9  | FR-10        | (Should) With two JSONL files staged in a temp dir, the run-selection data function returns the union keyed per `/design`'s chosen key; with one file it returns that single run unchanged.                                                                                                   |
| AC-10 | FR-11, NFR-4 | (Should) With Phoenix stopped, no deep-link is rendered and no view errors; the deep-link helper returns `None`/empty when Phoenix is unreachable.                                                                                                                                            |
| AC-11 | NFR-2, NFR-5 | All Must views render with the Phoenix container stopped and no second container started; `make dash` uses `uv run streamlit run` only.                                                                                                                                                       |

**Test layout convention.** Tests mirror `src/` into subdirs: `tests/dashboard/__init__.py`

- `tests/dashboard/test_data.py` (pure data functions) and `tests/dashboard/test_app.py`
  (smoke import). Never a flat `tests/test_dashboard.py`.

---

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                  |
| ----------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause + evidence: Phoenix lacks the aggregate / failure-mode-by-category / cross-model story; BRAINSTORM + ADR-0004 ground the boundary.                         |
| Users       | 3     | Named role + workflow: a reviewer who `git clone`s and runs `make dash` to see real numbers without eval re-run or Phoenix; opt-in drill-down via Phoenix deep-links. |
| Success     | 3     | Measurable, falsifiable ACs (AC-1…AC-11), pinned to the reuse contract and the cloneable/Phoenix-off invariants.                                                      |
| Scope       | 3     | Full MoSCoW with explicit Won't list carried from BRAINSTORM; screenshot kept as Could; no scope invented beyond it.                                                  |
| Constraints | 3     | All constraints named as NFRs: cloneable, Phoenix-off, 5h/minimal-Streamlit, graceful deep-link degradation, 8 GB / no-second-container, deterministic data layer.    |

**Total: 15/15 — PASS (≥12).** No clarifying questions required; the five orchestrator
decisions resolved the previously-open items.

---

## Infrastructure Readiness

| Dependency                      | KB domain     | Specialist         | Status                                                                                  |
| ------------------------------- | ------------- | ------------------ | --------------------------------------------------------------------------------------- |
| `streamlit` (new dep)           | observability | (none — thin tool) | Missing dep, added by FR-8. BRAINSTORM O-gate: no KB domain for a ~5h phase's tool. OK. |
| `dashboard/` module (new)       | —             | (none)             | New module + `tests/dashboard/`. Created by this phase. OK.                             |
| `results/*.jsonl` (data source) | rag-eval      | (none)             | `baseline.jsonl` git-tracked + present. Cloneable invariant holds. OK.                  |
| `generate_report_data` (reuse)  | rag-eval      | (none)             | Exists in `eval/report.py`, tested. Reuse contract intact. OK.                          |
| `FailureMode` / `failure_mode`  | observability | (none)             | `eval/failure_taxonomy.py` enum + field populated on records by `rag-classify`. OK.     |
| Phoenix deep-links (optional)   | observability | (none)             | Opt-in only; NFR-4 covers degradation. Not a blocking dependency. OK.                   |

**No `/new-kb` or `/new-agent` needed.** The BRAINSTORM research/KB gate already cleared KB
work (Streamlit is inline-context7 territory; `generate_report_data` and the failure
taxonomy are KB-covered under `rag-eval` / `observability`). No missing domain or
specialist.

---

## Open Questions (for `/design` only — not requirement-level)

1. **Charting primitive** — `st.bar_chart` (zero extra dep) vs `altair` (ships with
   Streamlit, richer grouped bars for the category × failure-mode view). Pick at design,
   honouring NFR-3 (no charting lib beyond Streamlit's own deps).
2. **Module path** — `src/enterprise_rag_ops/dashboard/app.py` (in-package, importable for
   the smoke test; makes `streamlit` a runtime dep) vs top-level `dashboard/app.py`
   (`streamlit` as an optional extra). FR-6's smoke-import AC nudges toward in-package.
3. **Multi-run union key** (FR-10) — union all `results/*.jsonl` keyed on
   `run_id` + `gen_ai.request.model`, vs explicit single-file pick. Risk: mixed `run_id`s
   with differing eval params shown side-by-side could mislead. Design decides the key and
   the guard.
4. **Phoenix deep-link URL shape** (FR-11) — verify the v15 per-span/trace URL format at
   design/impl time; if unstable, hide links behind a flag per NFR-4.

---

## Next Step

→ `/design sprint-3-phase-9-dashboard`
