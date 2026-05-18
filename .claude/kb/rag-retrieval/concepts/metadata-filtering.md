# Metadata Filtering

> **Purpose**: Pre- vs post-filter mechanics and how vector store choice affects them.
> **Confidence**: HIGH — research (pillar 3) and LanceDB docs (pillar 2) both confirm
> pre-filter is the default and preferred path; LanceDB's `.where(prefilter=True)`
> is its documented default behavior.
> **MCP Validated**: 2026-05-17

## Overview

The corpus carries `source_type` and `metadata["title"]` on every `Document`. When
queries target a specific source (e.g., "search only Slack"), metadata filtering must
run correctly relative to vector/BM25 scoring to guarantee the right number of
results.

## Pre-filter (default, preferred)

Filter restricts the candidate set **before** vector distance or BM25 scoring begins.

- Guarantees exactly k valid results are returned (all pass the filter).
- Supported by all three candidate stores; implementation differs:
  - **LanceDB**: `.where("source_type = 'slack'", prefilter=True)` — default in
    hybrid search queries. Confirmed by LanceDB docs.
  - **Qdrant**: filterable HNSW — graph traversal skips non-matching nodes.
  - **pgvector**: SQL `WHERE` clause; planner may fall back to sequential scan for
    high-selectivity filters (acceptable for small subsets).

## Post-filter

Filter runs **after** the vector/BM25 top-k is retrieved.

- Faster for non-selective filters (most docs pass).
- Risk: if many top-k candidates fail the filter, the final result set is smaller
  than requested k.
- In LanceDB: `.where(..., prefilter=False)`.

## This Project's Contract

The corpus `Document` model exposes `source_type` as a top-level field and
`metadata` as a freeform dict. Any metadata filter in Phase 2 must use fields
that are indexed in the vector store schema, not the raw `Document.metadata` dict.
Planning the schema before indexing (a Phase 2 design decision) determines which
filters are pre-filterable.

## Codebase Grounding

- `schema.py` — `Document.source_type` is always present; `metadata` is a dict
  with at minimum `title` (from `docs/dataset.md` field mapping).
- 9 source types: `slack`, `gmail`, `linear`, `google_drive`, `hubspot`,
  `fireflies`, `github`, `jira`, `confluence`.

## Related

- [quick-reference.md](../quick-reference.md) — vector store comparison table
- [concepts/hybrid-score-fusion.md](hybrid-score-fusion.md)
