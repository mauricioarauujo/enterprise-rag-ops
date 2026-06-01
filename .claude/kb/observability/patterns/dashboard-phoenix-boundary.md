# Pattern: Dashboard ↔ Phoenix Division of Labour

**Confidence**: HIGH — grounded in `dashboard/data.py`, `dashboard/app.py` (codebase),
ADR-0004 (sprint-3/phase-9).

## When to Use

Reference when deciding **where a given observability view belongs** — the Streamlit
dashboard or Arize Phoenix — or when extending either surface. The two are
complementary, not redundant; putting a view on the wrong side either duplicates Phoenix
or breaks the cloneable-results guarantee.

## The Boundary

| Question the reviewer asks                          | Surface       | Why                                                               |
| --------------------------------------------------- | ------------- | ----------------------------------------------------------------- |
| "Why did _this_ question fail?" (span tree, attrs)  | **Phoenix**   | Per-trace drill-down is Phoenix's native UI (`rag-export-traces`) |
| "Which failure mode dominates, per model/category?" | **Dashboard** | Aggregate / cross-model pivot Phoenix has no built-in view for    |
| "What did the run cost, per model?"                 | **Dashboard** | Cost rollup over the JSONL                                        |
| "Show me the OpenInference attributes on a span"    | **Phoenix**   | Span store is Phoenix's job                                       |

**Rule:** the dashboard owns the **aggregate / cross-model story**; Phoenix owns
**per-trace drill-down**. Do **not** rebuild Phoenix's span explorer in Streamlit
(BRAINSTORM Won't-list; ADR-0004 phased rollout).

## Why the Dashboard Reads JSONL, Not the Phoenix API

The dashboard renders from the git-tracked `results/baseline.jsonl`, **never** by querying
Phoenix. This preserves the ADR-0004 **cloneable-results** invariant: a reviewer who does
`git clone` + `make dash` sees real numbers with **no `docker-compose up` and Phoenix
stopped**. Querying the Phoenix API would couple the dashboard to a running container and
break clone-without-infra. (`results/*.jsonl` is the durable SSoT; Phoenix is a
replayable, opt-in view — see [eval-jsonl-replay](eval-jsonl-replay.md).)

## The Data / Render Split (testability seam)

```
dashboard/data.py   — PURE, no `import streamlit` at module load (the unit-test surface)
        │ plain dicts / DataFrames
        ▼
dashboard/app.py    — THIN shell, the ONLY file importing streamlit/altair
```

`data.py` never imports `streamlit` and never touches the network → it is deterministic
and offline-unit-testable against `results/baseline.jsonl`. `app.py` keeps all `st.*`
calls inside `render(paths)` / `main()`, guarded by `if __name__ == "__main__": main()`,
so importing the module starts no server (the AC-6 smoke test asserts this).

Enforce the purity seam in a test (subprocess avoids `sys.modules` leakage from sibling
tests that do import streamlit):

```python
subprocess.run([sys.executable, "-c",
    "import sys, enterprise_rag_ops.dashboard.data; assert 'streamlit' not in sys.modules"])
```

## Reuse, Don't Re-aggregate

`summary_rows` / `cost_rows` **delegate** to `eval.report.generate_report_data` (single
file → `{summary, costs, categories, k}`) — no metric is recomputed in the dashboard
layer. The **new** pivots are the only dashboard-specific aggregation, reading the
`failure_mode` field already on each `EvalRecord` (populated by `rag-classify`):

```python
from enterprise_rag_ops.dashboard.data import (
    summary_rows, cost_rows,            # delegate to generate_report_data
    failure_mode_distribution,          # {model: {FailureMode: count}}, 5-label zero-filled
    category_failure_distribution,      # {category: {FailureMode: count}}
    load_run_records, discover_results_paths,
)
```

`generate_report_data` groups by `gen_ai.request.model`, so multi-file = concatenate
records (`load_run_records(paths)`) and let per-model grouping work — same key on both
layers, or summary/cost tables disagree.

## The Phoenix Deep-Link Seam

The dashboard links _into_ Phoenix for drill-down but degrades gracefully when Phoenix is
absent. All URL construction lives in one function so a Phoenix-version change is a
one-line edit:

```python
phoenix_trace_url(question_id, *, project="enterprise-rag-ops", endpoint=None) -> str | None
```

- Gated on **env-presence** (`PHOENIX_COLLECTOR_ENDPOINT`), not a live health check → keeps
  `data.py` deterministic (no network). Returns `None` when unset → no broken links render.
- Strips a trailing `/v1/traces` (OTLP collector path) via `str.removesuffix` to reach the
  UI base — mirrors the endpoint normalization in [eval-jsonl-replay](eval-jsonl-replay.md).
- **Known limitation:** currently project-scoped, not per-trace (Phoenix v15 per-span URL
  shape unverified). `question_id` is the marked seam (`TODO(FR-11)` in `data.py`) for the
  one-line upgrade once the format is confirmed.

## Entry Point

```bash
make dash   # uv run streamlit run src/enterprise_rag_ops/dashboard/app.py — no Phoenix needed
```

## Sources

- `src/enterprise_rag_ops/dashboard/data.py`, `src/enterprise_rag_ops/dashboard/app.py`
- `docs/adr/0004-observability-tool.md` (cloneable-JSONL-as-SSoT, phased rollout)
- See also: [eval-jsonl-replay](eval-jsonl-replay.md), [failure-taxonomy](../concepts/failure-taxonomy.md)
