# SPRINT 1: Substrate

**Sprint:** sprint-1 | **Date:** 2026-05-17 | **Status:** closed (2026-05-22)

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

## Sprint-Wide Knowledge Plan

Research lands _before_ a phase's brainstorm/ADR; KB work lands _after_ its ADR.

| Knowledge area          | Kind          | Action                                  | Timing                                                                   |
| ----------------------- | ------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| Retrieval design        | research      | `/new-kb rag-retrieval --deep-research` | Done — Deep Research consumed; `rag-retrieval` KB built (survey shape)   |
| Retrieval stack         | KB (refocus)  | `/update-kb rag-retrieval`              | **After ADR-002** — collapse the comparison matrices to the chosen stack |
| Data loading / HF       | tech-agnostic | none — notes in `docs/dataset.md`       | Phase 1 (done)                                                           |
| rag-eval, observability | —             | out of sprint scope                     | Deferred to Sprint 2 / Sprint 3                                          |

**Note on sequencing.** The `rag-retrieval` KB was built before Phase 2's decisions
(SPRINT.md flagged it as a Phase 2 prerequisite), so it is currently a neutral
_survey_ of the design space — the right input for ADR-002, but broader than a KB's
steady state. Once ADR-002 records the vector store / fusion / chunking choices,
`/update-kb rag-retrieval` refocuses it: comparison matrices collapse to "chosen: X —
see ADR-002", the chosen-path patterns and tech-agnostic fundamentals stay.

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

## Retrospective

### What worked

- **The SDD cadence held across all three phases.** `/brainstorm → /define → /design →
/implement → /review` ran end-to-end for ingest, retrieval, and generation; every
  phase landed a `REVIEW.md` and an accepted ADR.
- **The seams paid for themselves.** The `VectorStore` / `Retriever` / `Generator`
  Protocols meant Phase 3's attribution fix (feed the ranked chunk, not the doc's title
  chunk) was a localized change — add `HybridRetriever.retrieve_chunks`, swap
  `fetch_chunks_by_doc_ids` → `fetch_chunks_by_chunk_ids` — not a rewrite. This is the
  "name the seam, design for the likely swap" principle working as intended.
- **The offline-CI invariant was real, not aspirational.** `StubEmbedder` and
  `StubGenerator` kept `make verify` network-free (no 568 MB model download, no OpenAI
  call) across 107 tests, while live smoke gates ran the real path separately.
- **Live smoke gates earned their place.** `make smoke` against the real OpenAI API
  surfaced three bugs the offline suite structurally could not: `gpt-5-nano` rejecting
  `temperature=0`, the wrong-chunk attribution bug, and faithful-abstention dominating
  a subset-limited corpus. None were reachable with stubs.

### What slipped vs. the plan

- **Branch discipline.** Phases 1–2 were implemented on `main` (uncommitted), then moved
  to feature branches before the PR. Both reviews flagged it as a process note. Phase 3
  followed the convention from the start.
- **Phase 2 verdict never flipped.** `phase-2-retrieval/REVIEW.md` still reads
  🟡 ALMOST. Its two blocking stranger-test items (ADR-002 budget clause, BRAINSTORM
  "portfolio" framing) were resolved before the PR #3 merge — verified at close time —
  but the verdict line was not updated. Recorded here rather than rewritten in the
  archived artifact; treat Phase 2 as shipped.
- **The smoke gate had to be redesigned mid-phase.** The dev subset (100 docs/source)
  holds gold docs for only 3 of 500 benchmark questions, so a flat `len(sources) >= 1`
  would have passed only via hallucinated citations. Reworked to a two-tier gate
  (valid answer on all 10; attribution only on the in-context subset) — a refinement
  the plan didn't anticipate, but a stronger check.

### Scope changes

- **Retrieval Protocols widened in Phase 3** (`VectorStore.fetch_chunks_by_chunk_ids`,
  `Retriever.retrieve_chunks`) — driven by the live-smoke attribution bug, not planned.
  The doc-level `retrieve` was preserved unchanged as the Sprint 2 eval contract.
- **ADR renumber.** Generation took ADR-003, pushing the planned observability ADR to
  ADR-004 and the LLM-matrix ADR to ADR-005.
- **Performance tech-debt deferred to Sprint 2** — `load_retriever` re-chunks the corpus
  at load (position↔chunk_id drift risk vs. the BM25 sidecar) and BGE-M3 encode cost.
  Recorded in the Sprint 2 planning notes, not addressed here (substrate scope).

## Sprint Close

**Phases shipped: 3 / 3 planned.** All merged to `main`.

| Phase                 | Verdict                            | Merge |
| --------------------- | ---------------------------------- | ----- |
| `phase-1-data-ingest` | ✅ READY                           | PR #2 |
| `phase-2-retrieval`   | ✅ shipped (REVIEW line stale 🟡)¹ | PR #3 |
| `phase-3-generation`  | ✅ READY                           | PR #4 |

¹ Blocking items resolved before merge (verified at close); REVIEW.md verdict line was
not flipped. See Retrospective.

**Success criteria — all met.** Reproducible `make download-data` at a pinned HF
revision; hybrid retriever passing the `expected_doc_ids` recall smoke; `make smoke`
running the end-to-end `rag-ask` CLI on 10 questions with cited sources (two-tier gate);
ADR-001 (eval framework, thin deferral), ADR-002 (retrieval architecture), and ADR-003
(generation) written and accepted.

### Knowledge loop (recommendations — pre-Sprint-2, not run at close)

- **`/new-kb rag-generation`** — capture the four Phase 3 lessons: the `Generator`
  Protocol + `StubGenerator` CI pattern; OpenAI structured-outputs (`response_format`
  json_schema `strict`) + Pydantic defensive re-validation as the attribution mechanism;
  the ranked-chunk context-assembly pattern (feed the winning chunk per doc, not the
  title chunk — doc-dedup must retain the winning `chunk_id`); and the two-tier smoke
  gate for a subset-limited corpus (faithful abstention is correct, not a bug).
- **`/update-kb rag-retrieval`** — refresh for the Phase 3 Protocol widening only. The
  dense-path persistence refocus (the Phase 2 staleness item) already landed in the
  2026-05-20 update; what remains stale is the `VectorStore` contract (KB describes 2
  methods; code now has 3) and the new `Retriever.retrieve_chunks`. Cross-link to
  `rag-generation`.

### ADR sweep

ADR-001/002/003 all shipped and accepted. One minor gap: Phase 1's
empty-content **skip-and-count** policy (records failing `Document` validation are
skipped, counted, and logged at WARNING) was flagged in Phase 1's review to fold into
ADR-002 and did not land there — it is only partially implied by `dataset.md`'s
"no empty `text`" output guarantee. Low priority; a one-line note in `dataset.md` or a
future ADR addendum suffices. Not blocking.

### Archive

`.claude/sdd/features/sprint-1/` → `.claude/sdd/archive/sprint-1/` (this commit).
