# 2026 Retrieval Frontier

> **Purpose**: Record what the conventional Phase 2 substrate deliberately omits —
> so future sprints can reason about the delta without re-deriving it.
> **Confidence**: MEDIUM — research-only claims for emerging paradigms; not
> cross-validated against pillar 1 (no src/ code yet) or pillar 2 (sparse pillar 2
> coverage on these topics). Treat as directional, not prescriptive.
> **MCP Validated**: 2026-05-17

## What Phase 2 Deliberately Does Not Use

Phase 2 is a **conventional substrate**: BM25 + dense hybrid with RRF. The following
techniques are known to exist but are explicitly out of scope. They are recorded here
so Sprint 2's eval harness can measure the gap and later sprints can layer them in.

## Learned-Sparse Retrievers (SPLADE)

Models like SPLADE project queries and documents into a high-dimensional vocabulary
space using neural language models, enabling synonym expansion within a sparse index.
Result: vocabulary-mismatch benefits of dense models with exact-match speed of BM25.
Not used in Phase 2 because it adds a trained sparse model as a dependency.

## Late-Interaction Models (ColBERT)

ColBERT stores per-token multi-vector representations. At query time, a MaxSim
operator matches query token vectors against document token vectors. Offers
near-cross-encoder precision at lower latency than full cross-encoders, but requires
significantly larger index storage (multi-vector per document). Not used in Phase 2.

## Instruction-Following Embeddings

State-of-the-art embedding models (e.g., Qwen3-Embedding-8B) accept a natural
language instruction prefix that dynamically shapes the embedding toward a target
concept or modality. Meaningful gains in heterogeneous retrieval tasks. Out of scope
for Phase 2; BGE-M3 without instruction prefixes is the baseline.

## BRIGHT Benchmark (vs MTEB/BEIR)

MTEB/BEIR measure lexical (Level 1) and semantic (Level 2) retrieval. BRIGHT
introduces Level 3 — **reasoning-intensive** retrieval, where relevant documents
share no surface or semantic overlap with the query and relevance requires multi-step
logical deduction.

Key finding: models that score ~70 nDCG@10 on MTEB can collapse to below ~20
nDCG@10 on BRIGHT. This is the capability gap the conventional Phase 2 substrate
will have; Sprint 2 should include a BRIGHT-style sample in the eval set to make
the gap visible.

## Phase 2 Contract

Phase 2's retrieval is a deliberate baseline — the eval and observability layers
(Sprints 2–3) exist to measure it and expose the gap with these frontier techniques.
Do not add SPLADE, ColBERT, or instruction-following embeddings to Phase 2.

## Related

- [reranking.md](reranking.md)
- [retrieval-eval-metrics.md](retrieval-eval-metrics.md)
