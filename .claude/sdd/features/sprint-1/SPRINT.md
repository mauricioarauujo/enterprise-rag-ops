# SPRINT 1: Substrate

**Sprint:** sprint-1 | **Date:** 2026-05-17 | **Status:** active

## Goal

Build an end-to-end baseline RAG pipeline over EnterpriseRAG-Bench: deterministic data
ingest and document indexing, hybrid retrieval (BM25 + dense), and a generation layer
that attributes every answer to its sources. This is the conventional substrate the
eval and observability layers (Sprints 2–3) will measure — correctness and
reproducibility matter here, not sophistication.

## Phase Breakdown

| Phase | Intent                                                                                         | Slug                  |
| ----- | ---------------------------------------------------------------------------------------------- | --------------------- |
| 1     | Data loading and document indexing; `make download-data` against a pinned HF dataset revision  | `phase-1-data-ingest` |
| 2     | Hybrid retriever (BM25 + dense) with an `expected_doc_ids` smoke test; write ADR-001 + ADR-002 | `phase-2-retrieval`   |
| 3     | Generation layer with source attribution; end-to-end `rag-ask` CLI; `make smoke` exit gate     | `phase-3-generation`  |

Planned breakdown, not a contract — each phase refines on `/brainstorm`.

## Sprint-Wide KB & Research

- **rag-retrieval — missing.** No KB domain exists for hybrid retrieval (BM25 + dense
  fusion, chunking strategy, `expected_doc_ids` scoring, vector-store choice). Phase 2
  re-derives this and it recurs in Sprint 2's recall@k metrics. Action: run `/new-kb
rag-retrieval` before `/brainstorm sprint-1/phase-2-retrieval`. Deep research not
  required — codebase + Context7 (rank_bm25, sentence-transformers, Qdrant/LanceDB)
  cover it.
- **Data loading / HF datasets — sufficient.** Hugging Face `datasets` loading with a
  pinned revision is well-trodden; no KB needed for Phase 1. Capture dataset
  field-level notes in `docs/dataset.md` instead.
- **rag-eval, observability — out of sprint scope.** Deferred to Sprint 2 / Sprint 3
  respectively; do not build now.

## Success Criteria

- `make download-data` fetches the EnterpriseRAG-Bench dataset at a pinned HF revision,
  reproducibly.
- The hybrid retriever passes a smoke test asserting `expected_doc_ids` recall on a
  fixed question subset.
- `make smoke` runs the end-to-end `rag-ask` CLI on 10 questions and returns, for each,
  an answer plus its cited sources.
- ADR-001 (eval framework) and ADR-002 (retrieval architecture + vector store) are
  written and accepted, capturing the _why_ at decision time.

## Risks

- **Dataset scale / access.** EnterpriseRAG-Bench spans 500K+ documents; ingest and
  indexing may exceed local resources. Mitigate by working a bounded subset for the
  smoke gate and pinning the HF revision so the corpus is stable.
- **Retrieval-stack indecision stalls Phase 2.** Vector-store choice (Qdrant vs
  LanceDB) and reranker scope can churn. Mitigate by forcing the call in ADR-002 and
  keeping rerank optional for the smoke gate.
- **Substrate scope creep.** The substrate is deliberately conventional; multi-hop
  agents and rerank tuning belong to later stretch work, not Sprint 1.
- **ADR timing drift.** `docs/adr/README.md` currently says the first ADR lands in
  Sprint 2; the sprint track places ADR-001/002 in Phase 2 here. Update that README
  when ADR-001 is written.
