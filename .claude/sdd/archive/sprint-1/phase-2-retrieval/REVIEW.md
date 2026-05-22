# Review: sprint-1/phase-2-retrieval — Hybrid Retrieval

**Branch:** `main` (uncommitted) | **Date:** 2026-05-19 | **Verdict:** 🟡 ALMOST → ✅ resolved at merge

> **Resolution (2026-05-22, sprint-1 close).** The two 🔴 blocking stranger-test items
> below were both fixed before the PR #3 merge — verified at close: ADR-002:17 reworded
> to "This is a substrate sprint — the retriever must work and be maintainable, not
> exotic", and the BRAINSTORM "portfolio" framing replaced with system-level rationale.
> The non-blocking polish (#1 deferred import, #2 `load_retriever` test) was also folded
> in. The verdict line was never flipped at the time; Phase 2 shipped as **✅ READY**.

## Summary

Implementation is correct, all 14 acceptance criteria are covered by either unit
tests or the local-only smoke gate, and `make lint` + `make test` pass clean
(72 tests). Two stranger-test violations in tracked files block the commit
until reworded; everything else is non-blocking polish.

## Mechanical Checks

| Step              | Status  | Notes                                                                                                                |
| ----------------- | ------- | -------------------------------------------------------------------------------------------------------------------- |
| Format            | PASS    | `ruff format --check` clean; prettier clean.                                                                         |
| Lint              | PASS    | `ruff check` — all checks passed.                                                                                    |
| Tests             | PASS    | `make test` — 72 passed, 5 deselected (`corpus` + `smoke`).                                                          |
| `retrieval-smoke` | NOT RUN | Not part of `make verify` by design; would require 568 MB BGE-M3 download. Validate locally before merging Sprint 1. |

## Issues

<details><summary>🔴 BLOCKING — Stranger test: <code>docs/adr/0002-retrieval-architecture.md:17</code></summary>

> `- Solo project on a 60-hour budget — the retriever must work, not be exotic.`

This is personal context (Mauricio's time budget), not system context — a stranger learns nothing about the system from the budget clause. Per `CLAUDE.local.md` § Public vs. personal, the rationale lines should live in the private track, not the public ADR.

**Fix:** rephrase to the system reason. Suggested:

```
- This is a substrate sprint — the retriever must work and be maintainable, not exotic.
```

</details>

<details><summary>🔴 BLOCKING — Stranger test: <code>.claude/sdd/features/sprint-1/phase-2-retrieval/BRAINSTORM.md:104,105,110</code></summary>

`.claude/sdd/` is tracked (verified against `.gitignore`). Three lines carry personal-career framing:

- L104: `… demonstrates production realism for portfolio`
- L105: `… overkill for this scale; no clear portfolio signal`
- L110: `The portfolio signal comes from the eval harness (Sprint 2), not …`

**Fix:** drop "portfolio" framing and restate as product/engineering rationale. e.g. on L104 strip the trailing "demonstrates production realism for portfolio"; on L105 replace "no clear portfolio signal" with "no additional capability vs LanceDB embedded at this scale"; on L110 rephrase as "The differentiating value comes from the eval harness (Sprint 2), not the vector-store choice."

</details>

<details><summary>⚠️ Non-blocking — Deferred import inside a loop: <code>src/enterprise_rag_ops/retrieval/pipeline.py:131</code></summary>

```python
for doc in read_corpus(config.CORPUS_PATH):
    from enterprise_rag_ops.retrieval.chunker import chunk_document
    for chunk in chunk_document(doc):
```

`chunk_documents` (plural) is already imported at the top of the file (L23). `chunk_document` (singular) should be too. The deferred import inside the for loop is not wrong but reads as an oversight and triggers a name lookup on every iteration.

**Fix:** add `chunk_document` to the top-level import on L23; delete L131.

</details>

<details><summary>⚠️ Non-blocking — <code>load_retriever()</code> untested in CI</summary>

`test_pipeline_contract.py:51-66` notes it "mirrors `load_retriever` but with the stub embedder" and then manually wires the components instead of invoking `load_retriever()`. The re-chunking logic in `pipeline.py:130-135` (which has the drift risk against the BM25 `chunk_ids.txt` sidecar — see Notes) is exercised only by the local-only `make retrieval-smoke`, never by `make verify`.

**Fix:** add a `test_load_retriever_from_persisted_artifacts` case to `test_pipeline_contract.py` that calls `pipeline.load_retriever(embedder=stub_embedder)` after a `build_index()` on the tmp_path-redirected config, asserts a `HybridRetriever` is returned and `.retrieve()` produces non-empty results. No model download required.

</details>

<details><summary>⚠️ Non-blocking — Unparameterised filter in <code>src/enterprise_rag_ops/retrieval/vector_store.py:112</code></summary>

```python
query = query.where(f"source_type = '{source_type_filter}'", prefilter=True)
```

`source_type_filter` is internal-only in Phase 2 (called from `HybridRetriever.retrieve`), so the trust model holds for now. Flag for Sprint 3 (when the retriever may be exposed via an API) — validate against the source-type allowlist at the `HybridRetriever` boundary or use a parameterised LanceDB filter.

</details>

<details><summary>⚠️ Non-blocking — AC-5 (reloadable .npy) only structurally covered</summary>

`test_embeddings_and_chunk_order_are_aligned` (test_pipeline_contract.py:105-115) loads `.npy` with `np.load` and verifies shape + chunk-id alignment but does not feed those vectors back through a retriever to confirm the persisted artifacts produce equivalent ranked results. `test_lancedb_open_reuses_existing_table` covers the LanceDB-handle reopening minimally. The gap is small; the fix above (NON-BLOCKING #2) effectively closes it.

</details>

<details><summary>⚠️ Non-blocking — Quadratic comprehension: <code>tests/retrieval/test_vector_store.py:41-43</code></summary>

```python
chunk_id_to_source = {
    c.chunk_id: d.source_type for d in synthetic_documents for c in chunks if c.doc_id == d.id
}
```

O(docs × chunks) where `{c.chunk_id: doc_source_type[c.doc_id] for c in chunks}` is O(chunks). Fine on the synthetic 6-doc fixture; worth fixing before Sprint 2's test suite grows.

</details>

## Acceptance Criteria

| AC                                                                            | Status | Covering test / artifact                                                                              |
| ----------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------- |
| AC-1 — `Chunk` with `chunk_id`/`doc_id`/`text`; `chunk.doc_id == document.id` | ✅     | `test_schema.py::test_chunk_doc_id_matches_document_id`                                               |
| AC-2 — uniform 256/32 chunking, no per-source branch                          | ✅     | `test_chunker.py::test_chunker_uniform_across_sources_no_per_source_branch`                           |
| AC-3 — `make build-index` produces three artifacts                            | ✅     | `test_pipeline_contract.py::test_pipeline_contract_end_to_end` (tmp_path scope)                       |
| AC-4 — idempotent skip + `rebuild-index` force                                | ✅     | `test_build_index_is_idempotent` + `test_rebuild_index_force_clears_and_regenerates`                  |
| AC-5 — BM25 mmap reload + `.npy` reload                                       | 🟡     | BM25 covered (`test_bm25_save_load_roundtrip_with_mmap`); `.npy` reload structurally only (see issue) |
| AC-6 — LanceDB schema + `source_type` pre-filter                              | ✅     | `test_vector_store.py::test_lancedb_source_type_prefilter_restricts_results`                          |
| AC-7 — top-k with no duplicate doc_id                                         | ✅     | `test_hybrid_retriever.py::test_retrieve_returns_unique_doc_ids`                                      |
| AC-8 — `source_type_filter` restricts                                         | ✅     | `test_retrieve_source_type_filter_restricts_docs` + filter-empties case                               |
| AC-9 — abstention below 0.45                                                  | ✅     | `test_retrieve_abstains_when_top_cosine_below_threshold`                                              |
| AC-10 — `reranker=None` is the default path                                   | ✅     | `test_retrieve_reranker_none_is_default_path`                                                         |
| AC-11 — pipeline-contract in `make verify`, no network                        | ✅     | `test_pipeline_contract.py` (uses `StubEmbedder`, no `sentence-transformers` import path)             |
| AC-12 — `make retrieval-smoke` Recall@10 > 0                                  | ✅     | `test_retrieval_smoke.py` (3 questions selected via streaming, marked `smoke`)                        |
| AC-13 — ADR-002 accepted + ADR-001 deferred stub                              | ✅     | `docs/adr/0001-eval-framework.md` + `docs/adr/0002-retrieval-architecture.md` + `README.md`           |
| AC-14 — 4 deps pinned + `make verify` clean                                   | ✅     | `pyproject.toml` L14-17, version-bounded; `make verify` PASS                                          |

## KB Staleness

| KB File                                                     | What Changed                                                                                                                                                                                                                                                    | Impact                                                                                                                                                                                                            | Action                                                                                                                                                                     |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.claude/kb/rag-retrieval/patterns/hybrid-retrieve-fuse.md` | The pattern's `dense_retrieve` re-encodes the full corpus on every call (`corpus_embs = model.encode([c.text for c in chunks], …)`). Phase 2 instead encodes once at build time and queries a persistent LanceDB index (NFR-1). DESIGN.md already flagged this. | Anyone copying the pattern verbatim will rebuild the matrix per query — exactly the anti-pattern Phase 2 had to refactor away from. Pattern's contract is now "reference for fusion logic only, not persistence." | `/update-kb rag-retrieval` (already SPRINT-scoped post-ADR-002): rewrite the dense path to read a persisted vector store and add a one-liner noting the build/query split. |

`rag-retrieval` `last_updated` (2026-05-17) precedes ADR-002 (2026-05-18) — the `_index.yaml` bump goes with the update.

## ADR

ADR-002 lands cleanly (records the LanceDB→Qdrant swap that justifies the `VectorStore` seam, plus the chunking-escalation trigger and the RRF no-calibration rationale). ADR-001 is an appropriately thin deferral. No additional ADR needed.

## Notes

- **Position↔chunk_id drift risk in `load_retriever`.** `load_retriever` reconstructs `chunk_to_doc` / `chunk_to_source_type` by re-running `chunk_document` over `corpus.jsonl`, not by reading the persisted sidecar. If `CHUNK_SIZE` / `CHUNK_OVERLAP` change in `config.py` without a `make rebuild-index`, the live maps drift silently from the BM25 `chunk_ids.txt` sidecar. The escape hatch is documented in ADR-002 ("`rebuild-index` when something has changed underneath"), but there is no runtime guard. Acceptable for Phase 2; first thing to harden in Sprint 2 when `load_retriever` is under real query traffic.
- **Abstention vs filter (DESIGN risk).** Implementation handles the empty-filter case correctly — dense search applies the filter at LanceDB; an empty hit list triggers abstention before BM25 is ever called. Both AC-8 and AC-9 hold; covered by `test_retrieve_with_filter_that_empties_candidates_returns_empty`.

## Suggested Next Steps

1. Fix the two 🔴 stranger-test items (ADR-002 L17 and BRAINSTORM.md L104/105/110).
2. (Optional but recommended) fold in NON-BLOCKING #1 + #2 in the same commit — tiny diff, closes the `load_retriever` CI gap.
3. Locally validate the full path: `make download-data` → `make build-index` → `make retrieval-smoke`. AC-12 only PASSes via this manual run.
4. Commit and open the PR (conventional commits: `feat:` for the package, `docs:` for the ADRs).
5. After merge, run `/update-kb rag-retrieval` to fold ADR-002 + persistence model into `patterns/hybrid-retrieve-fuse.md` (already SPRINT-scoped).
