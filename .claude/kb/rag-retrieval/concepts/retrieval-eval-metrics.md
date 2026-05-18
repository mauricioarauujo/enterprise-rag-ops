# Retrieval Evaluation Metrics

> **Purpose**: Recall@k, Precision@k, MRR, nDCG — formulas, scope, and the
> document-level deduplication invariant that makes them valid.
> **Confidence**: HIGH — formulas are standard IR theory; research (pillar 3)
> and multiple IR references agree. Metric formulas themselves were lost to image
> export but are recovered from standard IR definitions (not from the research file).
> The deduplication requirement is HIGH confidence (research + logic from the
> parent-child chunking pattern).
> **MCP Validated**: 2026-05-17

## Overview

`questions` in EnterpriseRAG-Bench carries `expected_doc_ids` — a set of ground-truth
`Document.id` values per query. Phase 2 must score retrieval at **document level**, not
chunk level, because multiple child chunks from the same parent document may appear in
the top-k results.

## Deduplication Invariant (non-negotiable)

Before computing any metric, map each retrieved chunk to its parent `Document.id` and
retain only the **first occurrence** per doc ID (preserving rank order). Skipping this
step artificially deflates recall and inflates precision.

```
Retrieved chunks:  [chunk_101a, chunk_101b, chunk_102a, chunk_103a]
Mapped doc IDs:    [doc_101,    doc_101,    doc_102,    doc_103   ]
Deduplicated:      [doc_101,               doc_102,    doc_103   ]
```

The deduplicated list is what all formulas below operate on.

## Metric Formulas

Let `R` = `expected_doc_ids` for a query. Let `D_k` = deduplicated top-k doc IDs.

### Recall@k

```
Recall@k = |R ∩ D_k| / |R|
```

Measures fraction of ground-truth documents captured. Primary Phase 2 smoke-test
signal — must be > 0 for the smoke gate to pass.

### Precision@k

```
Precision@k = |R ∩ D_k| / k
```

Measures fraction of retrieved positions that are relevant.

### Mean Reciprocal Rank (MRR)

```
MRR = (1/|Q|) * sum_q ( 1 / rank_of_first_hit_q )
```

Evaluates the position of the first correct document across queries `Q`. Sensitive
to whether the top-1 result is relevant.

### nDCG@k

```
DCG@k  = sum_{i=1}^{k} rel_i / log2(i + 1)
         where rel_i = 1 if D_k[i] in R, else 0
IDCG@k = DCG@k of a perfect ranking (all hits at top)
nDCG@k = DCG@k / IDCG@k
```

Penalizes relevant documents appearing lower in the ranked list. Best overall ranking
quality signal for Sprint 2.

## Evaluation Depth

Default evaluation window: **k = 10**. The research frames this as an effective proxy
for standard LLM context limits — deep enough to capture most relevant documents
without rewarding systems that pad results.

## Abstention

If the top-ranked vector's cosine similarity falls below **0.45**, the retriever
must return an empty result list (reject as unanswerable) rather than feeding
irrelevant context to the LLM. This gates the pipeline before generation, not after.

## Codebase Grounding

- `Document.id` (= dataset `doc_id`) is the deduplication key — `schema.py`.
- `expected_doc_ids` lives in the dataset `questions` config, Sprint 2 scope.
- Phase 2 exit gate: a smoke test asserting Recall@k > 0 on a fixed question subset.

## Related

- [patterns/expected-doc-ids-smoke.md](../patterns/expected-doc-ids-smoke.md)
- [chunking-strategies.md](chunking-strategies.md)
