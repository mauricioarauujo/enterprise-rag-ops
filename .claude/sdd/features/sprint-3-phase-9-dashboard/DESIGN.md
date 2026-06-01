# DESIGN: sprint-3-phase-9-dashboard — Streamlit Aggregate Dashboard

**Sprint/Phase:** sprint-3 / phase-9 | **Date:** 2026-06-01

> Stage 2 (DESIGN) for the phase. This is the **cross-tool IMPLEMENT CONTRACT** — the
> implement stage runs in Antigravity / Gemini against this file. The manifest is
> prescriptive enough that an executor needs no extra context. Function signatures for
> `data.py` are given verbatim; write them as specified. The four DEFINE open questions
> are resolved below (§ Resolved Design Decisions) with rationale.

---

## Resolved Design Decisions (the 4 DEFINE open questions)

| #   | Question                  | Decision                                                                                                                                                                                                                                                                                                                                                                                                            | Rationale                                                                                                                                                                                                                                                                                                                                                                                                            |
| --- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Charting primitive**    | **`altair`** for the two multi-series views (failure-mode × model, category × failure-mode grouped bars); **`st.bar_chart`** for the single trivial single-series view if any. Altair ships transitively with Streamlit.                                                                                                                                                                                            | NFR-3: no charting lib beyond what Streamlit bundles. Altair gives grouped/coloured bars that `st.bar_chart` can't express cleanly for `model × failure_mode`. No new explicit dependency — `altair` arrives with `streamlit`.                                                                                                                                                                                       |
| 2   | **Module path**           | **In-package:** `src/enterprise_rag_ops/dashboard/{__init__.py, data.py, app.py}`. `streamlit` becomes a **regular runtime dependency** in `[project].dependencies`.                                                                                                                                                                                                                                                | FR-6 / AC-6 require `import enterprise_rag_ops.dashboard.data` to succeed and be unit-testable. In-package placement makes `data.py` importable by `tests/dashboard/`. The dep is the point for a portfolio dashboard — acceptable per NFR-3 (minimal Streamlit, no _extra_ libs).                                                                                                                                   |
| 3   | **Multi-run union key**   | `data.py` exposes `load_run_records(paths) -> list[EvalRecord]` that **concatenates** records across files. Grouping key stays **`gen_ai.request.model`** (matches `generate_report_data`). Records already carry `run_id`; multi-file is plain concatenation, then existing per-model grouping works. Default Must path discovers tracked `results/*.jsonl` (today: `baseline.jsonl` only).                        | Matches the reuse contract exactly — `generate_report_data` groups by `gen_ai.request.model`, so the dashboard must too, or the summary/cost tables would disagree. Concatenation is the simplest union that keeps both layers consistent. `run_id` is carried for display/disambiguation, not used as the aggregation key (FR-10 guard: same model across runs merges; this is the documented, intended behaviour). |
| 4   | **Phoenix deep-link URL** | Single helper `phoenix_trace_url(...) -> str \| None`. Returns `None` when `PHOENIX_COLLECTOR_ENDPOINT` is absent from env (no live health check — env-presence is the gate, keeping the data layer deterministic per NFR-6). URL format lives in **one place** so a Phoenix-version change is a one-line edit. Classified **Should (FR-11)**, behind NFR-4 graceful degradation. **Does not block any Must view.** | Reuses the existing `PHOENIX_COLLECTOR_ENDPOINT` env convention (see `observability/phoenix_client.py`) rather than inventing `PHOENIX_BASE_URL`. A network health check would make `data.py` non-deterministic (violates NFR-6); env-presence keeps the helper pure and offline-testable. v15 span/trace URL shape is unverified, so the helper returns the project-scoped URL and degrades to `None` when unset.   |

---

## Architecture

**Two-layer split — pure data layer + thin render shell.**

```
results/*.jsonl  (git-tracked: baseline.jsonl)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ dashboard/data.py  — PURE, no `import streamlit` at module load│  ← FR-6 spine, the real coverage
│   discover_results_paths()      → list[Path]   (FR-1)          │
│   load_run_records(paths)       → list[EvalRecord]  (FR-1,10)  │
│   summary_rows(jsonl_path)      → reuse generate_report_data   │  (FR-2) — delegates, no recompute
│   cost_rows(jsonl_path)         → reuse generate_report_data   │  (FR-4)
│   failure_mode_distribution()   → {model:{FailureMode:count}}  │  (FR-3) NEW pivot
│   category_failure_distribution()→ {category:{FailureMode:..}} │  (FR-9) NEW pivot
│   phoenix_trace_url(...)        → str | None                   │  (FR-11) one-place URL, None when off
└──────────────────────────────────────────────────────────────┘
        │ plain dicts / DataFrames
        ▼
┌──────────────────────────────────────────────────────────────┐
│ dashboard/app.py  — THIN shell, the ONLY file importing streamlit│
│   render(paths)  — builds st.tabs: Summary | Failure | Cost     │
│                    | Category(Should) ; sidebar run-select(Should)│
│   main()         — discover paths, call render(); guarded so     │
│                    execution only happens via `streamlit run`    │
└──────────────────────────────────────────────────────────────┘
        │
        ▼  `make dash` → uv run streamlit run src/.../dashboard/app.py
   reviewer's browser (localhost)
```

**Data flow.** `app.py` discovers tracked `results/*.jsonl`, hands paths to `data.py`
pure functions, receives plain data structures, and renders them with Streamlit/Altair.
`data.py` never imports `streamlit` and never touches the network (NFR-6) — so it is the
unit-test surface. `summary_rows` / `cost_rows` **delegate to `generate_report_data`**
(no re-aggregation, proving reuse per AC-2/AC-4). The two `*_distribution` functions are
the **new** pivots `generate_report_data` does not provide; they read the `failure_mode`
field already on each `EvalRecord` (populated by `rag-classify`).

**Where each FR lives:** FR-1 → `discover_results_paths` + `load_run_records`; FR-2 →
`summary_rows` + Summary tab; FR-3 → `failure_mode_distribution` + Failure tab; FR-4 →
`cost_rows` + Cost tab; FR-5 → single-model fallback inside each tab render (no special
branch needed — one model is just a one-row frame); FR-6 → the whole `data.py` purity
contract; FR-7/FR-8 → `Makefile` + `pyproject.toml`; FR-9 → `category_failure_distribution`

- Category tab; FR-10 → sidebar multiselect over `discover_results_paths`; FR-11 →
  `phoenix_trace_url` + opt-in link column.

---

## File Manifest

| File                                           | Change | What it contains                                                                                                                                                                            | Satisfies                 | Owner  | Phase |
| ---------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ------ | ----- |
| `pyproject.toml`                               | modify | Add `"streamlit>=1.40,<2.0"` to `[project].dependencies`. No other dep (altair arrives transitively).                                                                                       | FR-8, AC-7                | direct | 1     |
| `src/enterprise_rag_ops/dashboard/__init__.py` | create | Empty package marker (or one-line docstring). No imports.                                                                                                                                   | FR-6                      | direct | 1     |
| `src/enterprise_rag_ops/dashboard/data.py`     | create | Pure data layer — signatures below. **MUST NOT `import streamlit`** (AC-6). Imports: `pathlib`, `collections`, `os`, `EvalRecord`, `FailureMode`, `generate_report_data`, `load_questions`. | FR-1,2,3,4,9,10,11; NFR-6 | direct | 2     |
| `tests/dashboard/__init__.py`                  | create | Empty package marker.                                                                                                                                                                       | (test layout)             | direct | 2     |
| `tests/dashboard/test_data.py`                 | create | Offline unit tests for every `data.py` function against committed `results/baseline.jsonl`. Assertions tied to AC-2..AC-5, AC-8, AC-9, AC-10. No LLM, no Phoenix, no network.               | AC-2,3,4,5,8,9,10         | direct | 2     |
| `src/enterprise_rag_ops/dashboard/app.py`      | create | Thin Streamlit shell. The **only** file importing `streamlit` / `altair`. `render(paths)` + `main()`; `st.*` calls only inside these, invoked by `streamlit run` (no top-level execution).  | FR-2,3,4,5,9,10,11; AC-1  | direct | 3     |
| `tests/dashboard/test_app.py`                  | create | Smoke test: `import enterprise_rag_ops.dashboard.app` succeeds without starting a server (guarded `main()`); assert `render`/`main` are callable.                                           | AC-6                      | direct | 3     |
| `Makefile`                                     | modify | Add `dash` to `.PHONY`; add help-annotated target (exact body below).                                                                                                                       | FR-7, AC-7                | direct | 3     |
| `docs/dashboard-screenshot.png` + README embed | create | (Could, FR-12) Static screenshot for non-runners. Only if Must+Should done.                                                                                                                 | FR-12                     | direct | 5     |

### `dashboard/data.py` — verbatim function signatures

Write these signatures exactly. All are pure (path/records in, plain data out); none
import or call `streamlit`.

```python
from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path

from enterprise_rag_ops.eval.failure_taxonomy import FailureMode
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.report import generate_report_data

RESULTS_DIR = Path("results")
PHOENIX_ENDPOINT_ENV = "PHOENIX_COLLECTOR_ENDPOINT"


def discover_results_paths(results_dir: Path = RESULTS_DIR) -> list[Path]:
    """Return sorted `*.jsonl` files in `results_dir` (FR-1).

    Default selection for the Must path. Sorted for determinism (NFR-6).
    Returns [] if the directory is absent or empty — callers render an empty-state.
    """


def load_run_records(paths: list[Path]) -> list[EvalRecord]:
    """Concatenate EvalRecords parsed from one or more JSONL files (FR-1, FR-10).

    Parses each line with `EvalRecord.model_validate_json`, skipping blank lines.
    Multi-file union is plain concatenation; per-model grouping downstream keys on
    `gen_ai.request.model` (matches `generate_report_data`). Order is paths-order
    then file-order (deterministic).
    """


def summary_rows(jsonl_path: Path) -> list[dict]:
    """Per-model summary rows — DELEGATES to generate_report_data (FR-2, AC-2).

    Returns `generate_report_data(jsonl_path)["summary"]` unchanged. No metric is
    recomputed here (proves reuse, not reimplementation).
    """


def cost_rows(jsonl_path: Path) -> list[dict]:
    """Per-model cost rollup — DELEGATES to generate_report_data (FR-4, AC-4).

    Returns `generate_report_data(jsonl_path)["costs"]` unchanged. `total_cost=None`
    is passed through untouched; the N/A formatting is the render layer's job
    (see `format_cost` below) — never coerce None to 0.
    """


def failure_mode_distribution(records: list[EvalRecord]) -> dict[str, dict[str, int]]:
    """NEW pivot: counts per FailureMode label, per model (FR-3, AC-3).

    Returns {model: {failure_mode_value: count}} where keys cover ALL 5 FailureMode
    labels (zero-filled), so every model maps every label even at count 0. Reads the
    `record.failure_mode` field already on each EvalRecord (populated by rag-classify);
    records with `failure_mode is None` are skipped (unclassified). Per-model totals
    over the 5 labels equal that model's classified record count.
    """


def category_failure_distribution(
    records: list[EvalRecord],
) -> dict[str, dict[str, int]]:
    """NEW pivot: category × failure-mode counts (FR-9, AC-8).

    Returns {category: {failure_mode_value: count}}, FailureMode labels zero-filled
    per category. `record.category` is the question_type carried on each EvalRecord.
    Records with `failure_mode is None` are skipped. Pure; offline-testable.
    """


def phoenix_trace_url(
    question_id: str,
    *,
    project: str = "enterprise-rag-ops",
    endpoint: str | None = None,
) -> str | None:
    """Single-source Phoenix deep-link builder (FR-11, NFR-4, AC-10).

    `endpoint` defaults to `os.environ.get(PHOENIX_ENDPOINT_ENV)`. Returns None when
    the endpoint is absent/empty (Phoenix not configured) — never a broken link.
    When set, returns a project-scoped URL built in THIS one place so a Phoenix-version
    URL change is a one-line edit. No network call (NFR-6 determinism: env-presence is
    the gate, not a live health check).
    """


def format_cost(total_cost: float | None) -> str:
    """Render helper: USD string or 'N/A' when None (FR-4, AC-4). Never returns '0'.

    Mirrors `eval.report._fmt`/cost formatting. Pure; lives in data.py so the N/A
    contract is unit-testable without Streamlit.
    """
```

> Note on `summary_rows`/`cost_rows` taking `jsonl_path` (single file) while
> `load_run_records` takes a list: this is intentional and matches the reuse contract —
> `generate_report_data` is single-file. For the Must path there is exactly one tracked
> file (`baseline.jsonl`), so the Summary/Cost tabs call `summary_rows(paths[0])` /
> `cost_rows(paths[0])`. The failure-mode pivots operate on the concatenated record list
> (`load_run_records(paths)`), which is where multi-run union actually matters. If/when a
> second tracked run appears, the multi-run summary path calls `summary_rows` per file and
> the app concatenates the row lists — no change to `generate_report_data` needed.

### `Makefile` — exact `dash` target

Add `dash` to the `.PHONY` line, and append this target (help-annotated so it appears in
`make help`):

```make
dash:  ## Launch the Streamlit aggregate dashboard over results/*.jsonl (no Phoenix needed)
	uv run streamlit run src/enterprise_rag_ops/dashboard/app.py
```

### `app.py` — execution-guard contract (AC-6)

`app.py` imports `streamlit as st` (and `altair as alt`) at module top, but **all `st.*`
calls live inside `render(paths)` / `main()`**. Module import must not call any `st.*`
or start a server. Streamlit invokes the script top-to-bottom under `streamlit run`, so
the bottom of the file is:

```python
if __name__ == "__main__":
    main()
```

The smoke test imports the module (which only triggers the `import streamlit` line, not
any rendering). Because importing `streamlit` is cheap and side-effect-free, AC-6's
"smoke import without launching the server" holds. `data.py` is the layer that must have
**zero** `import streamlit`.

---

## Implementation Phases

Ordered smallest-testable-first; each step is its own validateable unit. Phase ordering
follows the convention: config (1) → core module logic + tests (2) → render shell + entry
point (3) → Should (4) → Could (5). (No data-schema, eval-harness, or observability-hook
steps in this phase — the data source and taxonomy already exist.)

1. **Dep + skeleton + failing smoke import.**
   - `pyproject.toml`: add `streamlit`; run `uv sync`; verify `uv run streamlit --version` (AC-7).
   - Create `dashboard/__init__.py`, empty `dashboard/data.py`, empty `dashboard/app.py`,
     `tests/dashboard/__init__.py`.
   - Write `tests/dashboard/test_app.py` smoke import (red until `app.py` defines `main`).
2. **Pure data functions + unit tests (the bulk; fully offline).**
   - Implement all `data.py` functions per the verbatim signatures.
   - Write `tests/dashboard/test_data.py` against `results/baseline.jsonl` (AC-2,3,4,5,8,10).
   - Gate: `uv run pytest tests/dashboard/test_data.py` green. This is the real coverage.
3. **`app.py` render shell + smoke test + `make dash`.**
   - Implement `render(paths)` with `st.tabs`: Summary (FR-2), Failure-mode (FR-3, Altair
     grouped bar by model), Cost (FR-4, `format_cost` → N/A). `main()` discovers paths.
   - Single-model fallback (FR-5): one-row frames render coherently; no comparison-widget
     branch needed.
   - Add `Makefile` `dash` target. Gate: `tests/dashboard/test_app.py` green; manual
     `make dash` with Phoenix stopped renders all three Must tabs (AC-1, AC-11).
4. **Should items.**
   - Category × failure-mode breakdown tab (FR-9, Altair grouped bar; AC-8).
   - Multi-run sidebar `st.multiselect` over `discover_results_paths` (FR-10; AC-9) —
     single-file fallback unchanged.
   - Phoenix deep-link column via `phoenix_trace_url`, rendered only when non-None
     (FR-11, NFR-4; AC-10).
5. **Could (only if time remains).**
   - `docs/dashboard-screenshot.png` + README embed (FR-12). `make dash-screenshot`
     (FR-13) is explicitly out unless all above ship.

---

## Test Strategy

The pure data layer is the real coverage; `app.py` gets only a guarded smoke import. All
data/eval tests run **offline** against committed `results/baseline.jsonl` (no LLM, no
Phoenix, no network) — NFR-6.

| Test                                                  | Asserts                                                                                                                                                                                 | AC    |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| `test_data.py::test_summary_rows_equal_report`        | `summary_rows(baseline)` == `generate_report_data(baseline)["summary"]` (identity — proves reuse, not reimplementation).                                                                | AC-2  |
| `test_data.py::test_failure_mode_distribution_totals` | Each model's counts cover all 5 `FailureMode` labels (zero-filled); per-model total == that model's classified record count.                                                            | AC-3  |
| `test_data.py::test_cost_rows_equal_report`           | `cost_rows(baseline)` == `generate_report_data(baseline)["costs"]`; and `format_cost(None) == "N/A"` (never `"0"`).                                                                     | AC-4  |
| `test_data.py::test_single_model_structure`           | Feed a single-model record set → `failure_mode_distribution` returns a valid one-key dict (no exception, no empty frame); `summary_rows` on a single-model file returns a one-row list. | AC-5  |
| `test_data.py::test_category_failure_distribution`    | `category_failure_distribution(records)` returns category × failure-mode counts; labels zero-filled per category. (Should.)                                                             | AC-8  |
| `test_data.py::test_load_run_records_union`           | Two JSONL files staged in `tmp_path` → `load_run_records([a, b])` returns the concatenation (len == sum); one file returns that file's records unchanged. (Should.)                     | AC-9  |
| `test_data.py::test_phoenix_url_off`                  | With `PHOENIX_COLLECTOR_ENDPOINT` unset (monkeypatch `delenv`), `phoenix_trace_url("qst_0001")` returns `None`. With it set, returns a `str` containing the project. (Should.)          | AC-10 |
| `test_app.py::test_app_import_no_server`              | `import enterprise_rag_ops.dashboard.app` succeeds; `app.main` and `app.render` are callable; import triggers no `st.*` render call / no server.                                        | AC-6  |
| `test_data.py::test_data_module_no_streamlit`         | After `import enterprise_rag_ops.dashboard.data`, `"streamlit" not in sys.modules` (or assert the module has no `streamlit` attribute) — enforces the FR-6 purity seam.                 | AC-6  |

**Manual checks (not unit-tested):** `make dash` with Phoenix stopped renders all Must
tabs (AC-1); single-model comparison shows a single-model summary, not a broken widget
(AC-5 manual half); no second container started (AC-11).

> `test_data.py` should depend on `results/baseline.jsonl` existing (it is git-tracked per
> ADR-0004 cloneable principle). If a future CI strips it, guard with
> `pytest.skip` on absence — but the file IS committed, so the default path runs.

---

## Infrastructure Gaps (3-layer deep check)

| Gap Type              | Area                     | Detail                                                                                                                                                                                                                                                                | Recommendation                                       |
| --------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Missing domain        | —                        | No new technology area. Streamlit is a thin presentation tool; per BRAINSTORM O-gate a ~5h phase's tool gets no KB domain. `observability` + `rag-eval` already cover `FailureMode`, `EvalRecord`, and `generate_report_data`.                                        | **None.** No `/new-kb`.                              |
| Missing concept       | observability / rag-eval | The dashboard reuses documented concepts (failure-taxonomy, eval-record-schema, cost-accounting, eval-report-render). The new `*_distribution` pivots are a thin read over the already-documented `failure_mode` field — not new domain knowledge worth a KB concept. | **None.** No `/update-kb`.                           |
| Missing specialist    | dashboard                | No specialist agent owns `dashboard/`. Existing agents (`kb-architect`, eval/observability specialists) do not list a `dashboard` kb_domain because none exists by design. A thin Streamlit shell does not justify a new specialist for one ~5h phase.                | **None.** Owner = `direct` for all manifest entries. |
| Deliberate new module | `dashboard/`             | `src/enterprise_rag_ops/dashboard/` + `tests/dashboard/` created by this phase.                                                                                                                                                                                       | Created by manifest. Expected, not a gap.            |
| Deliberate new dep    | `streamlit`              | Added to `[project].dependencies` (FR-8). `altair` arrives transitively.                                                                                                                                                                                              | Added by manifest. Expected, not a gap.              |

**Outcome: no new KB domain, no KB concept, and no specialist agent are needed.** The
only "gaps" are the deliberately-created `dashboard/` module and the `streamlit`
dependency, both produced by the manifest. Confirmed.

---

## Consistency Check

This phase touches a new module plus two config files (>2 modules) — full six-pass
self-review run. **Verdict: ✅ CONSISTENT.**

| ID  | Severity | Pass                   | Location                                                                       | Finding                                                                                                                                                                                                                                                                    | Suggested fix                                                                                                                                                 |
| --- | -------- | ---------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | LOW      | Duplication            | FR-2 summary vs FR-4 cost both "source from `generate_report_data`"            | Overlapping reuse phrasing, but they target distinct keys (`summary` vs `costs`). Not a true duplicate.                                                                                                                                                                    | None — resolved by distinct `summary_rows` / `cost_rows` delegating functions.                                                                                |
| C2  | LOW      | Ambiguity              | DEFINE FR-10 "grouping key for union is a `/design`-level decision"            | Was an open placeholder.                                                                                                                                                                                                                                                   | Resolved here (Decision #3): key = `gen_ai.request.model`, union = concatenation.                                                                             |
| C3  | MEDIUM   | Underspecification     | DEFINE Open Q4 "Phoenix URL shape … verify at impl time"                       | URL shape unverified for Phoenix v15.                                                                                                                                                                                                                                      | Resolved by env-presence gate returning `None` (NFR-4); URL format isolated in `phoenix_trace_url` for a one-line fix. Does not block Must.                   |
| C4  | LOW      | Constitution alignment | AGENTS.md § Conventions "new module → new test file"                           | Honoured — `data.py`→`test_data.py`, `app.py`→`test_app.py`, mirrored under `tests/dashboard/`.                                                                                                                                                                            | None.                                                                                                                                                         |
| C5  | LOW      | Constitution alignment | AGENTS.md § Engineering Behavior "seam justified by named change, not in case" | `phoenix_trace_url` single-source seam is justified by a _named, likely_ change (Phoenix version URL drift, ADR-0004 v15 pin) — not speculative. `data.py`/`app.py` split is the FR-6 testability seam, named in DEFINE.                                                   | None — both seams are requirement-anchored.                                                                                                                   |
| C6  | LOW      | Coverage               | DEFINE FR-1..FR-13, NFR-1..NFR-6, AC-1..AC-11                                  | Every FR maps to ≥1 manifest entry (see File Manifest "Satisfies" column); every AC maps to a test or manual check (see Test Strategy). NFR-1/2/5 covered by JSONL-only render + `uv run streamlit run` (no container). NFR-6 covered by `data.py` purity + offline tests. | None — no gap either direction.                                                                                                                               |
| C7  | LOW      | Inconsistency          | Env var name                                                                   | DEFINE/BRAINSTORM mention `PHOENIX_BASE_URL`-style gating loosely; the codebase uses `PHOENIX_COLLECTOR_ENDPOINT`.                                                                                                                                                         | Resolved: design standardises on the existing `PHOENIX_COLLECTOR_ENDPOINT` (matches `observability/phoenix_client.py`) — terminology aligned to code reality. |

No CRITICAL or HIGH findings. No constitution violations. No unresolved drift.

**Constitution cross-check (AGENTS.md + ADR-0004 + KB):** English-only ✅; mirrored test
files ✅; minimal-scope (Must = 3 views + dep + target; Should/Could gated) ✅; seams are
requirement-named not speculative ✅; ADR-0004 cloneable principle preserved (renders from
committed `baseline.jsonl`, Phoenix off) ✅; reuse of `generate_report_data` honours the KB
`eval-report-render` pattern (no re-aggregation) ✅; stranger-test (no personal/Carreira
content) ✅.

---

## Risks & Trade-offs

- **Multi-run merge by model collapses runs with differing eval params.** Concatenating
  `results/*.jsonl` and grouping by `gen_ai.request.model` means two runs of the same model
  with different `k`/prompt would merge silently. **Mitigation:** today only `baseline.jsonl`
  is tracked (single run), so the risk is dormant; FR-10's sidebar selector lets a reviewer
  isolate a run; `run_id` is carried for display. **Not an ADR** — it's the documented,
  intended Must behaviour, revisited only if multi-run side-by-side becomes a real need.
- **Phoenix deep-link URL format is unverified for v15.** Mitigated by NFR-4 graceful
  degradation: `phoenix_trace_url` returns `None` when the env is unset and the format is
  isolated to one function. No broken links ever render. No Must view depends on it.
- **`streamlit` becomes a hard runtime dependency** (not an optional extra). Trade-off
  accepted (Decision #2): it makes `data.py` importable for tests and `make dash` work from
  a plain `uv sync`. For a portfolio dashboard the dep is the deliverable. No ADR warranted —
  it's a conventional, reversible choice consistent with NFR-3.
- **No new ADR is warranted** for this phase: it adds a presentation layer over existing,
  ADR-covered substrate (ADR-0004 tool/boundary, ADR-0007 schema, ADR-0008 taxonomy). The
  design decisions here are tactical, not architectural.

---

## Next Step

→ `/implement sprint-3-phase-9-dashboard` — no infrastructure gaps to address first; start
at Implementation Phase 1 (dep + skeleton + failing smoke import).
