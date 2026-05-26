# HTML + Markdown Eval Report Rendering

> **Purpose**: How `report.py` aggregates JSONL records and renders the evaluation
> output — zero extra dependencies, `None`→"N/A" propagation, dynamic `k`, and
> per-category breakdown.
> **Confidence**: HIGH (codebase — `eval/report.py`)

## When to Use

Add a new report section, change aggregation logic, or debug a `N/A` cell that should
have a value.

## Two-Stage Shape

```
generate_report_data(jsonl_path) → dict
    ↳ summary_data   — per-model fact_recall/precision/faithfulness + abstention
    ↳ category_data  — per-category × per-model retrieval + judge aggregates
    ↳ cost_data      — per-model total_cost, mean_latency, total_tokens
    ↳ k              — from records[0].k (never hard-coded)

render_markdown(data) → str   (string.Template substitution)
render_html(data)     → str   (string.Template substitution)
```

`render_report(jsonl_path, output_dir)` calls both and writes `<stem>.md` and
`<stem>.html`. No external templating dep — `string.Template` from stdlib only.

## `None` → "N/A" Propagation

`_fmt(val, pct=False)` centralizes all value formatting:

```python
def _fmt(val: float | None, pct: bool = False, decimals: int = 3) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%" if pct else f"{val:.{decimals}f}"
```

Every table cell goes through `_fmt`. A missing-price cost or an all-abstention
category renders "N/A" rather than crashing or showing 0.

## Per-Category Breakdown

The 10 EnterpriseRAG-Bench categories are derived from the loaded questions, not
hard-coded:

```python
categories = sorted({q.category for q in questions})
for cat in categories:
    ranked_results = {r.question_id: r.retrieval_ranked_ids for r in cat_recs}
    retrieval_aggs = aggregate_retrieval_metrics(cat_qs, ranked_results, k=k)
    # k comes from the record, not a literal — so k=5 → Recall@5 headers
```

## Same-Family Judge Bias Warning

The output embeds a caveat about using OpenAI-family judge to score OpenAI-family
answers — styled as an alert box in HTML and a `> [!WARNING]` block in Markdown.
Any committed `results/baseline.{html,md}` must carry this caveat.

## Cost "N/A" on Partial Missing Prices

```python
has_missing_price = any(
    r.generation.cost_usd is None or r.judge.cost_usd is None for r in recs
)
total_cost = None if has_missing_price else sum(...)
```

If any single record for a model has a `None` cost, the model's total is `N/A` —
a partial sum would be misleadingly low.

## Adding a New Section

1. Add aggregation logic in `generate_report_data`, return under a new key.
2. Add a `_fmt`-using render block in `render_markdown` and `render_html`.
3. Add the `$new_key` substitution variable to both `Template` strings.
4. No new deps — `string.Template` only.

## Related

- `eval/report.py`
- [../concepts/eval-record-schema.md](../concepts/eval-record-schema.md)
- [multi-model-runner.md](multi-model-runner.md)
- `eval/retrieval_eval.py` — `aggregate_retrieval_metrics`
