# BRAINSTORM: sprint-1/phase-2-retrieval — Hybrid Retrieval

**Sprint/Phase:** sprint-1/phase-2-retrieval | **Date:** 2026-05-18

## Problem Statement

Phase 1 produced a validated `data/processed/corpus.jsonl` (900 `Document` objects
across 9 source types). Phase 2 must build a hybrid retriever (BM25 + dense) over that
corpus, persist it so it is not rebuilt on every run, and pass a smoke gate asserting
`Recall@k > 0` against a fixed question subset drawn from the dataset `questions`
config. The retriever is a deliberately conventional substrate — the engineering signal
of this project comes from the eval and observability layers in Sprints 2–3, not from
retrieval sophistication.

---

## Research & KB Scan

All Phase 2 topics are covered by the `rag-retrieval` KB domain (built via the
3-pillar Deep Research prior to this brainstorm). Coverage classification below:

| Topic                                           | Concept / pattern file                             | Coverage                                 |
| ----------------------------------------------- | -------------------------------------------------- | ---------------------------------------- |
| Chunking strategy for the 9-source corpus       | `concepts/chunking-strategies.md`                  | Sufficient                               |
| BM25 library selection (bm25s vs rank_bm25)     | `concepts/lexical-vs-semantic.md`                  | Sufficient                               |
| Dense embedding model choice                    | `concepts/lexical-vs-semantic.md`, quick-reference | Sufficient                               |
| Hybrid score fusion (RRF vs alternatives)       | `concepts/hybrid-score-fusion.md`                  | Sufficient                               |
| Vector store choice (ADR-002 input)             | quick-reference decision matrix                    | Sufficient                               |
| Metadata filtering & pre-filter mechanics       | `concepts/metadata-filtering.md`                   | Sufficient                               |
| Reranking — scope and skip criteria             | `concepts/reranking.md`                            | Sufficient                               |
| `expected_doc_ids` smoke test pattern           | `patterns/expected-doc-ids-smoke.md`               | Sufficient                               |
| Retrieval eval metrics (Recall@k, MRR)          | `concepts/retrieval-eval-metrics.md`               | Sufficient                               |
| Frontier techniques (deliberately out of scope) | `concepts/frontier-2026.md`                        | Sufficient                               |
| ADR-001 (eval framework: RAGAs/DeepEval)        | none                                               | Missing — deferred (see ADR Scope below) |

No `/new-kb` or `--deep-research` is needed before `/define`. The single missing
area (ADR-001 eval framework) is recommended for deferral to Sprint 2, where the eval
harness actually lands. If that recommendation is rejected and ADR-001 must ship in
Phase 2, the `rag-eval` domain noted in `_index.yaml` would need a `/new-kb` pass
before `/define`.

---

## Approaches Considered

### 1. Chunking strategy

The corpus is uniform at the raw `Document` level (one flat schema — confirmed in
`docs/dataset.md`), but the source content is heterogeneous: Slack threads differ
structurally from Confluence docs, Jira tickets, and GitHub code. Phase 1's lesson was
that a uniform schema collapsed 9 planned adapters to 1. Does the same logic hold for
chunking?

| Approach                                                                                                                                   | Pros                                                                                                                                                                                     | Cons                                                                                                                                                                   | Effort |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Uniform fixed-size (256-token child, 32-token overlap) applied to all 9 source types                                                    | Mirrors Phase 1's simplicity win; single chunker, no branching; correct defaults per `concepts/chunking-strategies.md`; chunk→`doc_id` mapping is trivial                                | Lower precision on structured sources (Slack threads, GitHub code); parent context not preserved for generation                                                        | S      |
| B. Uniform parent-child (256-token child / 1024-token parent, 32-token overlap) applied to all 9 sources                                   | KB-recommended default; preserves generator context without per-source logic; `Chunk.doc_id = Document.id` is a clean foreign key; aligns to `patterns/hybrid-retrieve-fuse.md` skeleton | Two chunk types to manage (children indexed, parents fetched at generation time — Phase 3 concern); slightly more complex than A                                       | S–M    |
| C. Per-source-type chunking (9 strategies: temporal windowing for Slack, AST splitting for GitHub, heading hierarchy for Confluence, etc.) | Maximum retrieval precision; aligns to full per-source guidance in `concepts/chunking-strategies.md`                                                                                     | Exactly the Phase-1 trap the brief warns against: 9 chunkers for a substrate phase; the corpus subset (100 docs/source) may not reveal whether the complexity pays off | L      |

**Recommendation: Approach A** with one explicit future hook. The subset (900 docs,
≤25 KB text each for most sources) makes precision differences between A and B hard to
observe. The `expected_doc_ids` smoke gate only requires `Recall@k > 0`, not high
Recall — fixed-size chunking easily satisfies it. Parent context is a Phase 3 concern
(generation); Phase 2's output is `(doc_id, score)` pairs, not expanded chunks.
The `Chunk.doc_id = Document.id` mapping is identical in both approaches.

If the smoke gate reveals Recall@10 = 0 on any question (meaning fixed-size chunks
scramble the signal completely), escalate to Approach B before Phase 3. This is
unlikely for 900-doc corpus at 256-token chunks.

### 2. BM25 lexical index

| Approach                                                                                  | Pros                                                                                                                                                          | Cons                                                                                                      | Effort |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------ |
| A. `bm25s` (k1=1.5, b=0.75, method=`lucene`) with disk serialization (`mmap=True` reload) | Up to 500× faster than rank_bm25 per `concepts/lexical-vs-semantic.md`; memory-mapped reload keeps RAM low; SciPy sparse matrix on disk is stable across runs | Requires explicit `bm25s.save(path)` / `bm25s.load(path, mmap=True)` wiring                               | S      |
| B. `rank_bm25`                                                                            | Simpler API surface                                                                                                                                           | In-memory only (re-indexes on every run); higher RAM; KB explicitly recommends bm25s                      | S      |
| C. Qdrant's built-in sparse vector index                                                  | Eliminates a separate library; sparse+dense native hybrid in one store                                                                                        | Requires Qdrant (server or local); loses the embedded/no-server advantage; over-engineering at this scale | M      |

**Recommendation: Approach A (`bm25s`).** The KB is unambiguous: bm25s with mmap
serialization. The serialization wiring is minimal (a `save`/`load` pair) and prevents
the index being rebuilt every retrieval call.

### 3. Dense embeddings and persistence

| Approach                                                                                            | Pros                                                                                                                                                 | Cons                                                                                                                                         | Effort                            |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| A. BGE-M3 (`BAAI/bge-m3`, 1024 dims) via `sentence-transformers`; save `.npy` corpus matrix to disk | KB default; multi-source robustness (corpus spans code, chat, docs); single encode pass at index time; pre-saved matrix avoids re-encoding per query | 1024-dim matrix for 900 docs × avg chunk count is small; BGE-M3 model is 568 MB — first run downloads it                                     | S                                 |
| B. nomic-embed-text-v1.5 (64–768 dims, MRL)                                                         | CPU-friendly; smaller index at 64 dims; MTEB close to BGE-M3                                                                                         | Truncation requires explicit dim config; KB lists as fallback, not default; deviates from KB recommendation without clear gain at this scale | S                                 |
| C. No persistence — re-encode corpus on every retrieval call                                        | Simplest code                                                                                                                                        | Unacceptably slow (sentence-transformers encode 900+ chunks ≥ 10s each call); useless as a substrate for Phase 3                             | S (code) / unacceptable (runtime) |

**Recommendation: Approach A (BGE-M3 + `.npy` persistence).** Encoding once and
persisting the matrix (and the BM25 index) to `data/processed/` makes Phase 3's `rag-ask`
CLI fast without an in-process server. The 568 MB model download is a one-time cost,
accepted by the same logic as the HF dataset download. nomic-embed is the right fallback
for CI environments with no GPU, but should not be the primary choice.

### 4. Vector store

This is the ADR-002 decision. The three candidates from the KB decision matrix:

| Approach                           | Pros                                                                                                                                                   | Cons                                                                                                                          | Effort |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. LanceDB (embedded, disk-backed) | No server; embedded in-process; `.where(prefilter=True)` for metadata filtering; `RRFReranker()` built in; excellent for dev/small subsets; lowest RAM | Matures fast but not as battle-tested as Qdrant; fusion API ties the code to LanceDB conventions                              | S      |
| B. Qdrant (local mode, no Docker)  | Production-proven; native sparse+dense hybrid; filterable HNSW; strong SDK                                                                             | More complex setup than LanceDB embedded; HNSW graph held in RAM (fine at 900 docs × chunks); slightly higher friction for CI | M      |
| C. pgvector (PostgreSQL extension) | SQL-native filtering; good for existing Postgres infra                                                                                                 | Requires a Postgres server; manual SQL union for hybrid; overkill for this scale; no additional capability over LanceDB here  | L      |

**Recommendation: Approach A (LanceDB).** At the actual indexed scale — 900 documents
× ~3–5 chunks each = roughly 3,000–5,000 chunks — LanceDB embedded is the obvious
choice: no server to provision, disk-backed (RAM footprint negligible), built-in RRF,
and pre-filter native. The differentiating value of this project comes from the eval
harness (Sprint 2), not the vector-store choice — use the simplest store that works
correctly, then let the eval harness reveal whether anything needs upgrading. This
feeds ADR-002 directly.

### 5. Hybrid fusion

| Approach                                      | Pros                                                                                                                                                 | Cons                                                                                                                           | Effort |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. RRF (k=60) via over-fetch 3× per retriever | No calibration; score-distribution-agnostic; KB default; LanceDB `RRFReranker()` is a free native implementation; confirmed by research + Azure docs | None at this scale                                                                                                             | S      |
| B. Convex combination (alpha-weighted)        | Can favor semantic signal post-tuning                                                                                                                | Requires MinMax normalization and alpha calibration; no tuning data available in Phase 2; brittle if index composition changes | M      |
| C. DBSF (distribution-based)                  | Adaptive, no alpha to tune                                                                                                                           | More complex per-query computation than RRF; minimal gain over RRF at this scale                                               | M      |

**Recommendation: Approach A (RRF, k=60).** `concepts/hybrid-score-fusion.md` is
explicit: RRF with k=60 is the industry-standard default requiring no calibration.
LanceDB wraps it natively. Any tuning belongs to Sprint 2's systematic eval, not the
substrate.

### 6. Metadata filtering and reranking — scope decision

| Approach                                                                                                             | Pros                                                                                                                                                                                         | Cons                                                                                                                 | Effort                               |
| -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| A. Index `source_type` as a pre-filterable LanceDB column; expose it as an optional retriever parameter; no reranker | Smoke gate has no source-specific questions — filtering is free to include and costs nothing; reranking is explicitly out of scope per `concepts/reranking.md`; composable hook for Sprint 2 | None                                                                                                                 | S                                    |
| B. No metadata filtering or reranking in Phase 2                                                                     | Even simpler                                                                                                                                                                                 | Adds metadata indexing work to Sprint 2 when the schema is already known and the field already exists on `Document`  | S (code savings) / M (Sprint 2 debt) |
| C. Include cross-encoder reranker (BGE Reranker v2-m3)                                                               | Better precision                                                                                                                                                                             | `concepts/reranking.md` is explicit: out of scope for the smoke gate; adds ~500 MB model + latency; scope creep risk | M–L                                  |

**Recommendation: Approach A.** Index `source_type` as a schema column at index time —
it costs nothing to include and prevents a schema migration in Sprint 2. Expose it as
an optional `source_type_filter: str | None = None` parameter on the retriever. No
reranker in Phase 2; include a commented stub or a `reranker=None` placeholder in the
pipeline so Sprint 2 can toggle it without a redesign.

### 7. `expected_doc_ids` smoke test design

| Approach                                                                                                                                            | Pros                                                                                                              | Cons                                                                                                                                                                        | Effort |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Load a small fixed hardcoded question subset (3–5 questions) with manually verified `expected_doc_ids` drawn from the dataset `questions` config | Entirely offline; fast; no dependency on dataset `questions` loader being built in Phase 2; unambiguous pass/fail | Must manually inspect the dataset `questions` config to extract a valid subset; `expected_doc_ids` must reference `Document.id` values present in the Phase 2 corpus subset | S      |
| B. Load all 500 questions from the dataset `questions` config (streaming) during the smoke test                                                     | Tests the full eval surface                                                                                       | Requires building a `questions` loader in Phase 2 (new concern); adds HF network dependency to the smoke gate; slow (full corpus encode for each test run)                  | M      |
| C. Generate synthetic questions with known answers from the corpus                                                                                  | No HF dependency                                                                                                  | Questions may not match the actual eval distribution; defeats the purpose of using EnterpriseRAG-Bench                                                                      | M      |

**Recommendation: Approach A.** The `patterns/expected-doc-ids-smoke.md` pattern
confirms this design: a fixed `SMOKE_QUESTIONS` list with manually verified
`expected_doc_ids`. The smoke gate asserts `Recall@10 > 0` per question and `doc_id`
uniqueness in the result. The questions config loader is a Sprint 2 concern (the eval
harness scales it to all 500 questions). Phase 2 needs to inspect the dataset
`questions` config (locally or via streaming) to identify 3–5 questions whose
`expected_doc_ids` fall within the 900-doc stratified corpus subset — this is a
pre-implementation step, not a runtime dependency.

**Key invariant (non-negotiable):** `Chunk.doc_id = Document.id`; the smoke test
deduplicates chunk hits to `doc_id` before computing Recall@k. This is the
deduplication contract from `concepts/retrieval-eval-metrics.md`.

### 8. ADR scope — ADR-001 (eval framework) in Phase 2?

The `SPRINT.md` bundles ADR-001 (eval framework: RAGAs vs DeepEval vs custom) and
ADR-002 (retrieval architecture + vector store) into Phase 2.

**Assessment:** ADR-001 belongs in Sprint 2, not Phase 2. Rationale:

- The eval framework (RAGAs, DeepEval, custom judge) is only exercised in Sprint 2's
  eval harness. Writing ADR-001 now means deciding an architecture that has no code,
  no tests, and no empirical signal to inform the decision.
- The Sprint 2 track already scopes the rag-eval KB and systematic eval runs. Those
  produce the signal ADR-001 needs (latency, cost, per-fact granularity trade-offs).
- ADR-001 in Phase 2 would be a pure forward-looking architectural opinion, not a
  decision record of something actually decided. ADRs are most valuable when the
  decision is live.

**Recommendation:** Write ADR-002 (retrieval architecture + vector store) in Phase 2 —
this decision is live and the choices above resolve it. Stub ADR-001 with a
"deferred to Sprint 2" note in `docs/adr/` if the sprint plan requires a placeholder,
but do not write the full ADR until the eval harness exists. Flag this as an open
question for the product owner.

---

## Recommended Approach

Combine the per-topic recommendations into one coherent design:

1. **Chunking:** uniform fixed-size (256-token child, 32-token overlap) via
   `langchain_text_splitters.RecursiveCharacterTextSplitter` or equivalent; each
   `Chunk` carries `chunk_id` (derived from `Document.id` + offset index) and
   `doc_id = Document.id`.
2. **BM25:** `bm25s` (k1=1.5, b=0.75, method=`lucene`); index persisted to
   `data/processed/bm25_index/` via `bm25s.save()`; reloaded with `mmap=True`.
3. **Dense embeddings:** BGE-M3 via `sentence-transformers`; corpus matrix encoded
   once, saved as `data/processed/embeddings.npy`; chunk ordering persisted alongside.
4. **Vector store:** LanceDB embedded (disk-backed at `data/processed/lancedb/`);
   schema includes `chunk_id`, `doc_id`, `source_type` (pre-filterable), `text`.
5. **Hybrid fusion:** RRF (k=60) with over-fetch factor 3; LanceDB's `RRFReranker()`
   or manual implementation consistent with `patterns/hybrid-retrieve-fuse.md`.
6. **Metadata filtering:** `source_type` indexed as a LanceDB column; retriever
   exposes `source_type_filter: str | None = None` parameter.
7. **Reranker:** out of scope; include a `reranker=None` hook in the pipeline
   signature for Sprint 2 composability.
8. **Smoke gate:** 3–5 hardcoded questions with manually extracted `expected_doc_ids`;
   asserts `Recall@10 > 0` per question and unique `doc_id` per result.
9. **ADR-002:** written in Phase 2, capturing the LanceDB / BGE-M3 / bm25s / RRF /
   fixed-size chunking decisions. ADR-001 stubbed or deferred.

This is the smallest implementation that gives Phase 3 a working retriever, satisfies
the smoke gate, and keeps Sprint 2 unblocked — following the same discipline that
Phase 1 applied when it collapsed 9 adapters to 1.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                           |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Must     | `Chunk` dataclass with `chunk_id`, `doc_id`, `text` fields; `doc_id = Document.id`                                                             |
| Must     | Chunker: uniform fixed-size (256 tokens, 32-token overlap) over `corpus.jsonl`                                                                 |
| Must     | BM25 index built via `bm25s`, persisted to `data/processed/bm25_index/`                                                                        |
| Must     | Dense embeddings via BGE-M3, corpus matrix saved to `data/processed/embeddings.npy`                                                            |
| Must     | LanceDB embedded index at `data/processed/lancedb/`; schema includes `chunk_id`, `doc_id`, `source_type`, `text`                               |
| Must     | Hybrid retriever: BM25 + dense → RRF (k=60) → doc-level deduplication → top-k `(doc_id, score)`                                                |
| Must     | `source_type` indexed as a pre-filterable LanceDB column                                                                                       |
| Must     | `make build-index` target that runs chunking + BM25 index + embedding + LanceDB indexing (idempotent)                                          |
| Must     | Smoke test asserting `Recall@10 > 0` on 3–5 fixed questions with verified `expected_doc_ids`                                                   |
| Must     | Smoke test asserting no duplicate `doc_id` in retriever output (deduplication contract)                                                        |
| Must     | ADR-002 written: retrieval architecture, vector store choice, chunking, fusion algorithm                                                       |
| Should   | `make retrieval-smoke` target wrapping the smoke test (distinct from `make check-data`)                                                        |
| Should   | Abstention threshold: if top-1 cosine similarity < 0.45, return empty list (from `concepts/retrieval-eval-metrics.md`)                         |
| Should   | `reranker=None` parameter placeholder in `HybridRetriever` for Sprint 2 composability                                                          |
| Should   | `source_type_filter: str                                                                                                                       | None = None`parameter on the retriever's`retrieve()` method |
| Should   | `make verify` passes (ruff format + lint + unit tests); new modules under `src/enterprise_rag_ops/retrieval/` with mirrored `tests/retrieval/` |
| Could    | ADR-001 stub in `docs/adr/` noting deferral to Sprint 2 (satisfies the sprint plan's requirement without a premature decision)                 |
| Could    | Logging per-source chunk count distribution at index build time (mirrors Phase 1's per-source document logging)                                |
| Could    | `docs/adr/README.md` updated to note that first ADR lands in Phase 2 (not Sprint 2 as it currently states)                                     |
| Won't    | Cross-encoder reranker — out of scope per `concepts/reranking.md`; Phase 2 smoke gate only requires Recall@k > 0                               |
| Won't    | ADR-001 (eval framework) — not a live decision in Phase 2; deferred to Sprint 2                                                                |
| Won't    | Per-source-type chunking (Slack temporal windowing, GitHub AST splitting, etc.) — complexity not justified at the subset scale                 |
| Won't    | Parent-child chunking — Phase 3's generation layer can be built on fixed-size chunks; parent context retrieval is a Sprint 2+ optimization     |
| Won't    | Loading all 500 `questions` from the dataset `questions` config — deferred to Sprint 2 eval harness                                            |
| Won't    | SPLADE, ColBERT, instruction-following embeddings — explicitly out of scope per `concepts/frontier-2026.md`                                    |
| Won't    | Qdrant, pgvector, or any server-backed vector store in Phase 2                                                                                 |
| Won't    | Convex combination or DBSF fusion — no calibration data available; RRF is the correct default                                                  |

---

## Open Questions

1. **ADR-001 scope confirmation.** The sprint track bundles ADR-001 (eval framework)
   into Phase 2. The recommendation here is to stub or defer it to Sprint 2 where the
   eval harness exists. Should Phase 2 write a placeholder ADR-001 stub, or is the
   sprint plan flexible on this? Answering this determines whether `/define` includes
   ADR-001 work.

2. **Question selection for the smoke gate.** The smoke test requires 3–5 questions
   from the dataset `questions` config whose `expected_doc_ids` fall within the 900-doc
   stratified corpus subset. These must be identified before implementation by
   inspecting the `questions` split (streamed, no full load required). Confirmed:
   the dataset `questions` config is at the same pinned SHA
   (`69916e31c68aa5963c00248fd7f0bc12d04fd235`, `QUESTIONS_CONFIG = "questions"`).
   Should this question-selection step be part of Phase 2's `/implement`, or is a
   pre-run inspection expected before that?

3. **Chunk text splitter library.** The KB defaults (256 tokens, 32 overlap) are
   library-agnostic. Two practical options: `langchain_text_splitters` (adds a
   LangChain dep) or a thin stdlib tokenizer via `tiktoken` or `transformers`
   tokenizer. Which is preferred — the lighter stdlib approach or accepting LangChain
   as a dep? (The answer affects `pyproject.toml` `dependencies`.)

4. **BGE-M3 model download in CI.** BGE-M3 is 568 MB. The smoke test fixture
   (`retriever_components` in `patterns/expected-doc-ids-smoke.md`) loads the model at
   test time. Should the smoke test be excluded from `make verify` (run only via
   `make retrieval-smoke`) to avoid a 568 MB model download in CI, or is CI expected
   to cache the model between runs?

5. **`make build-index` idempotency and forced rebuild.** The index build should be
   idempotent (skip if artifacts exist). Should `make build-index` always rebuild
   (overwrite), or should it skip if `data/processed/lancedb/` exists, with a
   `make rebuild-index` for forced refresh? The choice affects the Makefile target
   design and how Phase 3 depends on this step.

---

## Resolved (2026-05-18) — input for `/define`

1. **ADR-001 — defer to Sprint 2.** Phase 2 writes only a short "deferred" stub in
   `docs/adr/`; the full eval-framework decision is made when the harness exists.
2. **Smoke-gate questions — selected during `/implement`** (first step: a streamed
   inspection of the `questions` config; no separate manual pre-run).
3. **Text splitter — use `langchain-text-splitters`** (the standalone package, _not_
   the full `langchain` meta-package). Rationale: a battle-tested
   `RecursiveCharacterTextSplitter` is less custom code to own than a bespoke splitter
   — lower long-term debt, not higher. Pin it in `pyproject.toml`.
4. **Retrieval smoke — two-tier, keep a CI test.** The 568 MB cost is the _embedding
   model_, not the input data. CI runs a fast **pipeline-contract** test: a tiny
   synthetic fixture corpus + a stub/deterministic embedder, asserting the wiring —
   chunk → BM25 + dense → RRF fusion → chunk→`doc_id` dedup → ranked top-k. The
   real-model **Recall@k** smoke (BGE-M3 + corpus subset) stays local via
   `make retrieval-smoke`. `/define` to pin: pure stub embedder vs a small real model
   in CI.
5. **`make build-index` — idempotent.** Skips if `data/processed/lancedb/` exists;
   `make rebuild-index` forces a clean rebuild.

**Guiding principle (user, 2026-05-18):** avoid accumulating tech-debt — favour
scalable, maintainable, organised paths from day 0. Reconciled with the
conventional-substrate framing: scope stays minimal (no per-source chunkers, no
reranker), but the _structure_ is clean — notably a `VectorStore` / `Retriever`
interface seam so the LanceDB → Qdrant swap (ADR-002) is a localised change, not a
rewrite. `/design` owns that boundary.

## Next Step

→ `/define sprint-1/phase-2-retrieval`
