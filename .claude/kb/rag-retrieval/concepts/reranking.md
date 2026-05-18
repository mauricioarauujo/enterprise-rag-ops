# Reranking

> **Purpose**: Cross-encoder reranking as an optional second stage and when to skip it.
> **Confidence**: HIGH for the reranker architecture taxonomy and skip criteria
> (research is the primary source; no significant conflict with pillar 2). Model
> latency figures from research: MEDIUM (not cross-checked against current benchmarks).
> **MCP Validated**: 2026-05-17

## Overview

The hybrid retriever (Stage 1) optimizes for broad recall at speed. A cross-encoder
reranker (Stage 2) re-scores a small candidate list with full query-document
attention, improving precision at the cost of latency. Reranking is **optional** for
the Phase 2 smoke gate — the smoke test only requires Recall@k > 0.

## Reranker Architecture Taxonomy

| Type                       | How it works                   | Precision          | Latency         | Notes                         |
| -------------------------- | ------------------------------ | ------------------ | --------------- | ----------------------------- |
| Cross-encoder              | Full query+doc attention joint | High               | O(n) candidates | ms-marco-MiniLM, BGE-Reranker |
| Late-interaction (ColBERT) | MaxSim token vectors           | Near cross-encoder | Lower           | Large multi-vector index      |
| Listwise LLM               | LLM re-orders candidate set    | Exceptional        | Very high       | API cost; Sprint 3+           |

## Recommended Models

| Model                  | Size        | Latency (100 candidates) | Hardware   | License    |
| ---------------------- | ----------- | ------------------------ | ---------- | ---------- |
| BGE Reranker v2-m3     | 568M params | ~80–200 ms               | A10/L4 GPU | Apache 2.0 |
| ms-marco-MiniLM-L-6-v2 | 22M params  | ~50–80 ms                | CPU        | Apache 2.0 |

**Default**: BGE Reranker v2-m3 for multilingual / multi-source robustness. Fallback
to MiniLM on CPU-only or strict latency budget.

## Skip Criteria

Skip reranking when any of these hold:

1. End-to-end latency budget is tight and Stage 1 already consumes a large share.
2. Top-1 normalized dense similarity exceeds **0.90** (treated as an effective exact
   match; reranking adds no meaningful precision gain at this confidence level).
3. Score margin between rank-1 and rank-10 is very large (clear winner; ranks stable).
4. Query is a pure exact-match lookup (Jira key, error code) and BM25 returns a
   high-confidence hit.

## Phase 2 Scope

Reranking is **out of scope for the smoke gate**. Include it as an optional
composable step in the retrieval pipeline so it can be toggled in Sprint 2's
systematic eval without a redesign.

## Related

- [hybrid-score-fusion.md](hybrid-score-fusion.md)
- [patterns/hybrid-retrieve-fuse.md](../patterns/hybrid-retrieve-fuse.md)
- [frontier-2026.md](frontier-2026.md)
