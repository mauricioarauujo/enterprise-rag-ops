# Retrieval Metric Aggregation in the Eval Harness

> **Purpose**: How `aggregate_retrieval_metrics` applies the four retrieval metrics
> per question, groups results by category, and skips `None` values — with the dedup
> invariant that must run before scoring.
> **Confidence**: HIGH (codebase — Phase 5)
> **Codebase**: `eval/retrieval_eval.py`, `eval/retrieval_metrics.py`
> **Formulas**: see `rag-retrieval/concepts/retrieval-eval-metrics.md` (not duplicated here)

## Overview

`aggregate_retrieval_metrics` is the eval harness entry point for retrieval scoring.
It takes a question list and a `ranked_results` map (question_id → ranked chunk IDs),
computes the four metrics per question, and returns per-`category` averages.

The metric formulas (Recall@k, Precision@k, MRR, nDCG@k) live in
`rag-retrieval/concepts/retrieval-eval-metrics.md`. This concept documents only the
**harness-level application**: the dedup invariant, None-skipping, and category
aggregation.

## Deduplication Happens Before Every Metric

All four metric functions call `deduplicate_ranked_ids` as their first step.
Chunk IDs (`"doc::0"`, `"doc::1"`) are mapped to doc IDs via
`chunk_id.split("::", 1)[0]`; only the first occurrence per doc ID is kept:

```python
# eval/retrieval_metrics.py
def deduplicate_ranked_ids(ranked_ids: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for rid in ranked_ids:
        doc_id = rid.split("::", 1)[0]
        if doc_id not in seen:
            seen.add(doc_id)
            deduped.append(doc_id)
    return deduped
```

Dedup runs **inside** each metric function — callers do not pre-dedup. All four
functions (`recall_at_k`, `precision_at_k`, `mrr`, `ndcg_at_k`) apply it
identically.

## None-Skipping Rule

Every metric returns `float | None`. `None` means "not applicable" — specifically,
`expected_doc_ids` was empty (the question is unanswerable, so retrieval recall is
undefined). The aggregator **never appends None to the list**:

```python
# eval/retrieval_eval.py — per-question loop
r = recall_at_k(ranked_ids, q.expected_doc_ids, k=k)
p = precision_at_k(ranked_ids, q.expected_doc_ids, k=k)
m = mrr(ranked_ids, q.expected_doc_ids, k=k)
n = ndcg_at_k(ranked_ids, q.expected_doc_ids, k=k)

if r is not None: category_metrics[q.category]["recall"].append(r)
if p is not None: category_metrics[q.category]["precision"].append(p)
if m is not None: category_metrics[q.category]["mrr"].append(m)
if n is not None: category_metrics[q.category]["ndcg"].append(n)
```

If a category has no valid values (e.g. a category where all questions have
empty gold sets), its aggregate is `None` — not `0.0`.

Note: `mrr` also returns `None` when there is no hit in the top-k (not just for
empty expected_doc_ids). Those are also excluded from the mean correctly.

## Per-Category Aggregation

Results are grouped by `Question.category` (the string from the dataset, e.g.
`"single_hop"`, `"multi_hop"`, `"info_not_found"`, `"high_level"`). Averages are
computed only over collected (non-None) values:

```python
# eval/retrieval_eval.py — aggregation
aggregated[cat] = {
    f"recall_at_{k}":    sum(recalls) / len(recalls) if recalls else None,
    f"precision_at_{k}": sum(precisions) / len(precisions) if precisions else None,
    "mrr":               sum(mrrs) / len(mrrs) if mrrs else None,
    f"ndcg_at_{k}":      sum(ndcgs) / len(ndcgs) if ndcgs else None,
}
```

The output keys use the actual `k` value (e.g. `"recall_at_10"`), not a static
string, so changing `k` is reflected in the output without code changes.

## Function Signature

```python
def aggregate_retrieval_metrics(
    questions: Sequence[Question],
    ranked_results: Mapping[str, list[str]],  # question_id → ranked chunk IDs
    k: int = 10,
) -> dict[str, dict[str, float | None]]:      # category → metric name → value
```

## Related

- `rag-retrieval/concepts/retrieval-eval-metrics.md` — metric formulas (SSoT)
- [abstention-scoring.md](abstention-scoring.md) — None on unanswerable questions
- [../concepts/none-empty-denominator.md](none-empty-denominator.md) — None convention
- `eval/retrieval_eval.py`, `eval/retrieval_metrics.py`
