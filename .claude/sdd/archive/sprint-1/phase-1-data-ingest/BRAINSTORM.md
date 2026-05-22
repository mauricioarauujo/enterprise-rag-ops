# BRAINSTORM: phase-1-data-ingest — Data Ingest & Document Indexing

**Sprint/Phase:** sprint-1/phase-1-data-ingest | **Date:** 2026-05-17

## Problem Statement

Sprint 1 starts with no `src/` directory and no runtime dependencies. Phase 1 must
produce a reproducible `make download-data` command that fetches EnterpriseRAG-Bench at
a pinned HF revision, normalizes the nine heterogeneous enterprise sources into a
canonical document model, and stores a bounded corpus subset that Phase 2 (retrieval)
can index — all verifiable without a retriever in place.

## Suggested Research & KB Work

| Topic                                                               | Coverage   | Action                                                                                                                         |
| ------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------ |
| HF `datasets` library — `load_dataset`, revision pinning, streaming | sufficient | No KB needed; field-level notes go in `docs/dataset.md` per SPRINT.md.                                                         |
| `huggingface_hub` snapshot download                                 | sufficient | Same — not complex enough to warrant a KB entry.                                                                               |
| Chunking strategy, BM25+dense retrieval, `expected_doc_ids` scoring | missing    | `/new-kb rag-retrieval` before `/brainstorm sprint-1/phase-2-retrieval` (already recorded in SPRINT.md; out of Phase 1 scope). |
| Pydantic dataclass patterns for document schemas                    | sufficient | Standard library knowledge; no KB action.                                                                                      |

None of the Phase 1 topics require `--deep-research`. Coverage is sufficient for
the design decisions at hand. The `rag-retrieval` KB is the only pre-work needed for
Phase 2, and it is explicitly deferred there.

## Approaches Considered

### Data Acquisition

| Approach                                                                    | Pros                                                                                                                                                        | Cons                                                                                                                           | Effort |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. `datasets.load_dataset(..., revision=SHA)` with streaming                | Single dep (`datasets`); streaming avoids materializing 500K docs; revision SHA is the canonical reproducibility pin; integrates cleanly with HF ecosystem. | `datasets` is heavier than `huggingface_hub` alone; streaming API differs from batch access; requires careful iterator design. | S      |
| B. `huggingface_hub.snapshot_download(revision=SHA)` to `data/raw/`         | Downloads raw Parquet files; lighter API surface; allows `data/processed/` to be built separately.                                                          | Two-step pipeline (download then parse); Parquet schema must be reverse-engineered; no built-in field validation.              | M      |
| C. `datasets.load_dataset` with `trust_remote_code=True` + local cache only | Full HF ecosystem features; dataset script handles schema details.                                                                                          | Remote code execution risk; more fragile to dataset updates; overkill for a static bench.                                      | M      |

**Recommendation:** Approach A. The `datasets` library is already the natural fit for
HF bench datasets; streaming avoids loading 500K docs into memory; pinning by commit
SHA is idiomatic and auditable. The subset/sampling logic sits cleanly on top of the
streaming iterator.

### Document Model

| Approach                                                                                      | Pros                                                                                                                                    | Cons                                                                                       | Effort |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------ |
| A. Pydantic `BaseModel` with mandatory fields (`id`, `source_type`, `text`, `metadata: dict`) | Validation at ingest boundary; serializable to JSON/Parquet; `metadata` dict absorbs per-source heterogeneity without over-engineering. | Pydantic adds a dep; `dict` metadata is untyped — Phase 2 may need typed sub-schemas.      | S      |
| B. Plain Python `dataclass` (stdlib)                                                          | Zero extra deps; fast; trivially serializable.                                                                                          | No field-level validation; schema drift is silent; harder to extend with validators later. | S      |
| C. Source-specific typed schemas with a union discriminator                                   | Fully typed per source; catches schema errors early.                                                                                    | Nine sources = nine models; high upfront complexity for a substrate phase.                 | L      |

**Recommendation:** Approach A. Pydantic will be added as a core dep regardless
(needed for Phase 3 prompt schemas and Sprint 2 eval models). The `metadata: dict`
field deliberately defers per-source typing until Sprint 2 proves what fields the eval
harness actually needs.

### Chunking Boundary — Phase 1 vs Phase 2

| Approach                                                                 | Pros                                                                                                                                                        | Cons                                                                                                                                                                                                    | Effort                    |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| A. Phase 1 stores raw documents only; chunking is Phase 2's first step   | Clean separation of concerns: ingest owns the document model, retrieval owns the chunk model; Phase 1 has fewer moving parts and is independently testable. | Phase 2 starts with a larger scope. `/new-kb rag-retrieval` must be ready before Phase 2.                                                                                                               | S (Phase 1) / M (Phase 2) |
| B. Phase 1 includes fixed-size chunking (e.g., 512-token sliding window) | Phase 2 can begin dense indexing immediately; reduces Phase 2 scope.                                                                                        | Chunking strategy is tightly coupled to the retriever — making it Phase 1's concern violates the separation principle and couples Phase 1 to a decision (chunk size, overlap) that needs ADR-002 input. | M (Phase 1) / S (Phase 2) |

**Recommendation:** Approach A. Phase 1 outputs canonical `Document` objects; Phase 2
owns `Chunk` derivation. This keeps Phase 1 independently testable, allows ADR-002 to
determine chunk strategy before any chunking code is written, and matches the
sprint plan's intent ("Data loading and document indexing" — indexing here means
organizing into the document model, not building an inverted index or embeddings).
The KB action (`/new-kb rag-retrieval`) remains a Phase 2 prerequisite, not Phase 1.

### Scale Handling

| Approach                                                                          | Pros                                                                                                                                                   | Cons                                                                                                    | Effort                 |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- | ---------------------- |
| A. `CORPUS_SIZE` env var / Makefile param; default=1000 docs; streaming `take(N)` | Deterministic subset via fixed seed + first-N of a sorted stream; configurable for CI vs local vs full; full corpus is always one env-var change away. | Sorted-stream ordering may not be representative of all 9 sources; must document the sampling contract. | S                      |
| B. Stratified sample by `source_type` (N per source)                              | Better coverage of all 9 enterprise source types in smoke tests.                                                                                       | Slightly more complex sampling logic; N-per-source may still be skewed.                                 | S–M                    |
| C. Full corpus, rely on streaming to avoid memory blow-up                         | No sampling logic to maintain; always tests real distribution.                                                                                         | 500K+ docs will slow every smoke-gate run unacceptably on local hardware.                               | S (code) / L (runtime) |

**Recommendation:** Approach B — stratified by `source_type`, with a configurable
`DOCS_PER_SOURCE` (default 100, giving ~900 docs across 9 sources). This gives
representative coverage of all source heterogeneity at the document-model layer
without special-casing. The sampling is deterministic: sort within each source by `doc_id`
and take the first N. `make download-data` accepts `DOCS_PER_SOURCE=<n>` to override.

## Recommended Approach

Combine the per-topic recommendations above into a single coherent design:

1. **Acquisition:** `datasets.load_dataset("onyx-dot-app/EnterpriseRAG-Bench", revision=<SHA>, streaming=True)`.
2. **Document model:** Pydantic `Document(id, source_type, text, metadata)` in `src/enterprise_rag_ops/ingest/schema.py`.
3. **Normalization:** one thin adapter per source type in `src/enterprise_rag_ops/ingest/adapters/` that maps raw HF fields to `Document`. Adapters registered in a dict keyed by `source_type` string.
4. **Chunking:** explicitly excluded from Phase 1 — `Document` is the unit Phase 2 receives.
5. **Subset:** stratified by `source_type`, `DOCS_PER_SOURCE=100` default, deterministic (sort by `doc_id`, take first N per source).
6. **Storage:** processed documents serialized to `data/processed/corpus.jsonl` (gitignored). The `data/raw/` HF cache is also gitignored.
7. **Validation (smoke):** `make check-data` target runs a pytest test that asserts: (a) `corpus.jsonl` exists, (b) line count within expected range, (c) all 9 `source_type` values present, (d) no document has empty `text`, (e) `doc_id` values are unique.

This approach is the smallest deliverable that gives Phase 2 a stable, validated
document corpus to build its retriever against.

## Scope (MoSCoW)

| Priority | Item                                                                                       |
| -------- | ------------------------------------------------------------------------------------------ |
| Must     | `make download-data` fetches data at a pinned HF revision SHA                              |
| Must     | Pydantic `Document` schema with `id`, `source_type`, `text`, `metadata`                    |
| Must     | Normalization adapters for all 9 source types present in the dataset                       |
| Must     | Stratified subset saved to `data/processed/corpus.jsonl` (deterministic)                   |
| Must     | `DOCS_PER_SOURCE` configurable via env/Makefile param                                      |
| Must     | `make check-data` pytest smoke test validating corpus integrity                            |
| Must     | `docs/dataset.md` updated with field-level schema notes                                    |
| Should   | `pyproject.toml` updated with `datasets` and `pydantic` as runtime deps                    |
| Should   | Logging (stdlib `logging`) in the ingest script showing per-source counts                  |
| Could    | CLI entrypoint (`rag-ingest`) alongside `make download-data`                               |
| Could    | Parquet output in addition to JSONL for Phase 2 compatibility                              |
| Won't    | Chunking — belongs to Phase 2 with ADR-002 driving chunk strategy                          |
| Won't    | Embedding or vector-store writes — Phase 2                                                 |
| Won't    | BM25 index build — Phase 2                                                                 |
| Won't    | Eval harness integration (`gold_answer`, `answer_facts` usage) — Sprint 2                  |
| Won't    | Full 500K corpus ingest as the default path — resource risk, deferred to explicit override |
| Won't    | Per-source typed Pydantic sub-schemas — premature; `metadata: dict` is sufficient          |

## Open Questions

1. **HF revision SHA to pin.** The exact commit SHA for EnterpriseRAG-Bench must be
   confirmed by running `datasets.load_dataset_builder` or inspecting the HF repo's
   commit history. Which SHA should be the canonical pin for Sprint 1? Should it be the
   latest main as of 2026-05-17, or a specific tagged release?

2. **Field mapping per source.** The nine source types (Confluence, Jira, Slack,
   Linear, Gmail, GDrive, GitHub, HubSpot, Fireflies) likely have heterogeneous raw
   field names in the HF dataset. Are the source-specific schemas documented anywhere,
   or must they be reverse-engineered by inspecting the raw data? This determines whether
   adapter implementation is S or M effort.

3. **Chunking boundary confirmation.** The SPRINT.md says "Data loading and document
   indexing" for Phase 1. "Doc indexing" is ambiguous — does the product owner mean
   organizing documents into the document model (Approach A above), or does it include
   building a searchable index structure? Confirming this blocks the Phase 1 / Phase 2
   scope split.

4. **`datasets` streaming vs. full download trade-off for CI.** Streaming avoids
   materializing the full corpus but requires a live HF connection on every run. Should
   `make download-data` be a one-time materialization to `data/raw/` (so `make check-data`
   runs offline), or is a live download on every run acceptable?

5. **`metadata` field contents.** Which per-source fields beyond `id`, `source_type`,
   and `text` should be preserved in `metadata` for Phase 2 and Sprint 2's eval harness?
   At minimum `expected_doc_ids` linkage requires the `doc_id` to be stable — but are
   there other fields (e.g., URL, timestamp, thread ID) that retrieval or evaluation will
   need?

## Next Step

-> `/define sprint-1/phase-1-data-ingest`
