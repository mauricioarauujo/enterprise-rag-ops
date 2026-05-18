# Hybrid Score Fusion

> **Purpose**: Algorithms for merging BM25 and dense ranked lists into one ranking.
> **Confidence**: HIGH for RRF structure and k=60 default (research + LanceDB docs
> confirm RRF is their default reranker; k=60 is the industry-standard constant cited
> across multiple sources). HIGH for DBSF clamping expression (recovered from PDF
> rendering). Convex combination: HIGH for formula structure; alpha is intentionally
> unspecified — research states it requires continuous calibration.
> **MCP Validated**: 2026-05-17

## Overview

BM25 scores are unbounded floats; dense similarity scores are typically bounded
[-1, 1] or [0, 1]. Combining them naively inflates BM25. Three fusion strategies
handle this mismatch differently.

## Reciprocal Rank Fusion (RRF) — Default

RRF ignores raw scores entirely and operates on rank positions:

```
RRF_score(doc) = sum over each ranked list L:
                   1 / (k + rank_of_doc_in_L)
```

- `k = 60`: the industry-standard smoothing constant. Dampens the dominance of
  top-ranked documents so that consensus across lists matters more than a single
  extreme rank. Confirmed: research (pillar 3), LanceDB docs default (`RRFReranker()`
  with no explicit k), Microsoft Azure AI Search documentation.
- **No calibration needed** — works out of the box when score distributions differ.
- **Over-fetch**: each retriever must return 3–5× the final target k before RRF to
  guarantee sufficient candidate overlap.

**Conflict note**: The research states k=60 as the "industry standard." LanceDB's
`RRFReranker()` uses RRF by default but does not expose k in its Python constructor
(confirmed by LanceDB docs). No conflict on the algorithm; k default is consistent.

## Convex Combination

Normalize BM25 and dense scores to [0, 1] via MinMax scaling, then blend:

```
Score_convex(d) = α · S_dense(d) + (1 − α) · S_sparse(d)
```

- `α ∈ [0, 1]` has no fixed recommended value. The research states it "requires
  continuous calibration to match corpus vocabulary characteristics." Treat as a
  tunable hyperparameter, not a constant.
- Requires stable, comparable score distributions. Brittle when index composition
  changes.

## Distribution-Based Score Fusion (DBSF)

For each retriever's result set, compute per-query mean μ and standard deviation σ.
Clamp each raw score x to a normalized value n, then sum across retrievers:

```
L = μ − 3σ,  U = μ + 3σ

n(x) = 0              if x < L
n(x) = (x − L)/(U−L)  if L ≤ x ≤ U
n(x) = 1              if x > U

Score_DBSF(d) = Σᵢ nᵢ(d)   (sum over each retrieval system i)
```

- More adaptive than convex combination; no α to tune.
- Preferred over convex when score magnitudes are consistent across queries.

## Recommendation for Phase 2

Use **RRF with k=60**. Rationale: no hyperparameter tuning, robust to outlier
scores from either retriever, confirmed by both research and LanceDB production docs.
Convex combination and DBSF are alternatives when score magnitudes are calibrated.

## Related

- [lexical-vs-semantic.md](lexical-vs-semantic.md)
- [patterns/hybrid-retrieve-fuse.md](../patterns/hybrid-retrieve-fuse.md)
