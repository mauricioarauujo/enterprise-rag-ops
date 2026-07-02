# BRAINSTORM: phase-5-retrieval-eval — Retrieval Metrics & Gold-Aware Corpus

**Sprint/Phase:** sprint-2/phase-5-retrieval-eval | **Date:** 2026-05-24

## Problem Statement

Phase 4 shipped a per-fact judge that scores answer quality. Its numbers are
meaningless until the corpus is built so that retrieval failures are real signal, not
coverage artifacts: the current stratified subset (first 100 docs/source by id, 900
docs) contains the gold `expected_doc_ids` for roughly 3 of 500 questions, making
recall@k near-zero by construction. Phase 5 fixes this prerequisite first, then
layers on the retrieval metrics (recall@k, precision@k, MRR) and abstention scoring
on `info_not_found` that turn the full eval harness into a credible measurement.

---

## Research & KB Scan

| Topic                                                                                    | KB file / domain                                               | Coverage                                                                                                                                                |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Retrieval eval metrics (recall@k, precision@k, MRR, nDCG, k=10 default, dedup invariant) | `rag-retrieval/concepts/retrieval-eval-metrics.md` (conf 0.90) | Sufficient — formulas and dedup invariant are HIGH-confidence and should be consumed directly                                                           |
| Chunk→doc mapping (`chunk_id.split("::",1)[0]`)                                          | `rag-retrieval/patterns/expected-doc-ids-smoke.md` (conf 0.95) | Sufficient — invariant is codebase-grounded and confirmed correct                                                                                       |
| `load_questions()` / `Question` schema                                                   | `eval/questions.py` (codebase)                                 | Sufficient — already built in Phase 4; the single typed reader of `expected_doc_ids`                                                                    |
| `JudgeVerdict` None-empty-denominator convention                                         | `rag-eval` KB domain (conf 0.95)                               | Sufficient — reuse convention for all new ratio metrics                                                                                                 |
| `stratified_sample()` determinism / streaming design                                     | `ingest/sampler.py` (codebase)                                 | Sufficient — fully read; NFR-1 (same revision + params → byte-identical) is the constraint the new mode must preserve                                   |
| Distractor doc selection strategy                                                        | Not in KB                                                      | Thin — no domain KB; the choice (stratified-by-source vs. first-N-by-id) needs a decision; coverage is sufficient to decide without additional research |
| Abstention threshold calibration (0.45 sweep)                                            | Not in KB — deferred from ADR-002                              | Thin — the anchor "Paris" case and the `info_not_found` category are the relevant signal; a threshold sweep is a Could in the MoSCoW (see below)        |
| LLM provider/model matrix for ADR-005                                                    | Not yet researched                                             | Thin — ADR-005 is on this phase's plate but primarily serves Phase 6; whether to write it now or at the 5/6 boundary is itself an open question         |

**Conclusion:** No `/new-kb` or `--deep-research` is needed before `/define`. The
retrieval metrics KB is already sufficient. A `/update-kb rag-retrieval` may be
warranted after Phase 5 if the distractor-selection pattern proves reusable.
ADR-005 research (Context7/Exa on OpenAI + Anthropic pricing and structured-output
support) should happen before `/define` only if the team decides to write ADR-005 in
this phase; otherwise defer to the Phase 5/6 boundary.

---

## Approaches Considered

### Decision 1 — Layering: how gold doc IDs reach the sampler

The new sampler mode must know which `doc_id`s are the gold docs for answerable
questions. Those IDs live in the `questions` config, read by `eval/questions.py`.
The sampler currently has zero dependency on `eval/`.

| Approach                                                                                                                                                                                                                                                                                                                        | Pros                                                                                                                                                                    | Cons                                                                                                                                                                                                                   | Effort |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Ingest imports eval questions reader (`ingest` → `eval` dependency) — `cli.py` calls `load_questions()`, collects gold IDs, passes them to a new `gold_aware_sample()` in `sampler.py`                                                                                                                                       | Single call site; no duplication; keeps sampler pure (receives a `set[str]`, knows nothing about `Question`)                                                            | Creates an `ingest → eval` import edge — upward coupling in the module hierarchy (eval is conceptually "above" ingest); any eval-layer change re-imports ingest config via the questions reader, creating a cycle risk | S      |
| B. Thin orchestrator in cli — a new CLI flag (`--gold-aware`) triggers a pre-step in `ingest/cli.py` that streams `load_questions()`, builds the gold-id set, then calls `gold_aware_sample(documents, gold_ids, distractors_per_source)`. The sampler receives only primitive types; `eval` is not imported by sampler at all. | Clean inversion: the CLI orchestrator resolves the dependency; sampler stays a pure function over `Document` + `set[str]`; fully testable without eval; no import cycle | The orchestrator (`cli.py`) must import from both `ingest` and `eval` — acceptable for an entrypoint, but it does make `rag-ingest` aware of the eval schema at CLI level                                              | S      |
| C. Duplicate a minimal questions reader in ingest — a tiny `ingest/gold_reader.py` that streams the `questions` config and yields `(question_id, expected_doc_ids, category)` tuples without importing from `eval/`                                                                                                             | Zero coupling between layers; truly independent                                                                                                                         | Duplicates the HuggingFace dataset streaming logic and the `DATASET_REVISION` consumption; two readers will drift if the questions schema changes; violates the "single typed reader" design established in Phase 4    | M      |

**Leaning: B.** The CLI orchestrator is already the right place for cross-layer
coordination (it wires loader → adapters → sampler → writer). Adding the gold-id
pre-step there keeps both the sampler and `eval/questions.py` unmodified and
independent. The import direction (cli imports eval) is the right direction — CLI is
the composition root.

---

### Decision 2 — Distractor strategy

Gold docs for answerable questions come from `expected_doc_ids`. The remaining corpus
is distractors. Three strategies for selecting them:

| Approach                                                                                                                                           | Pros                                                                                                                                                          | Cons                                                                                                                                                 | Effort |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Stratified-by-source distractors (N per source, deterministic by ascending id — same as the current sampler) — e.g. `distractors_per_source=50` | Deterministic (NFR-1 preserved); matches the existing sampling mental model; proportional source representation prevents source-type imbalance in distractors | N is a new parameter to expose and document; the right value is unclear without measuring                                                            | S      |
| B. Fixed-ratio to gold — e.g. 3× as many distractors as gold docs, selected by ascending id across all sources                                     | Ratio-based: corpus automatically scales if gold count changes; simpler one-parameter API                                                                     | Cross-source ratio is harder to reason about; determinism requires defining a total order for the cross-source selection (sort by `doc_id` globally) | S      |
| C. No distractors — corpus = gold docs only                                                                                                        | Smallest corpus possible; encodes fastest (critical on the 8 GB Air)                                                                                          | Precision@k would be trivially high (every result is gold); abstention from `info_not_found` still works but the retrieval signal is over-optimistic | XS     |

**Leaning: A.** Stratified-by-source distractors (small N, configurable, same
ascending-id determinism) preserve the existing sampler's mental model, keep NFR-1
intact, and give each source type representation among distractors. Approach C is
explicitly wrong for retrieval quality measurement. Approach B is viable but
introduces a global-sort over potentially thousands of docs; the stratified
approach is simpler and already proven.

The resulting corpus will almost certainly be _smaller_ than the current 900-doc
subset (gold docs are ~a few hundred at most; distractors at 50/source = 450 more →
roughly 600–700 total), which is a side benefit: BGE-M3 encode and `load_retriever`
both run faster, easing the 8 GB Air constraint.

---

### Decision 3 — Abstention signal: retrieval-level vs. end-to-end

For `info_not_found` questions, the system should abstain. Two distinct abstention
signals exist:

| Approach                                                                                                                                                          | Pros                                                                                                                                                                                              | Cons                                                                                                                                                               | Effort |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. Retrieval-level abstention — score whether the retriever returned an empty result (cosine < 0.45 threshold) for `info_not_found` questions                     | Pure retrieval signal; testable without running the LLM; directly tied to the 0.45 threshold calibration ADR-002 deferred                                                                         | Does not capture cases where retrieval returned results but the LLM abstained (or vice versa); the generator has its own Python short-circuit abstention (Phase 3) | S      |
| B. End-to-end abstention — score whether `AnswerWithSources.answer` equals the abstention sentinel (`"I cannot find a relevant answer in the provided sources."`) | Reflects real user-facing behavior; catches both retrieval-level and generation-level abstention failures (the "Paris" case: retrieval passed the threshold, LLM answered from parametric memory) | Requires running the full pipeline; 500 live LLM calls; higher cost per sweep                                                                                      | M      |
| C. Both — report retrieval-level abstention rate (cheap, offline) as a leading indicator, and end-to-end abstention rate (live run) as the authoritative signal   | Complete picture; the two signals together isolate whether the failure is retrieval or generation                                                                                                 | Double the measurement points; Phase 6 multi-model runner is the right home for end-to-end; adds scope to an already-tight 6h budget                               | L      |

**Leaning: A for Phase 5, B deferred to Phase 6.** Phase 5 owns the retrieval layer;
retrieval-level abstention (did the retriever reject the query?) is the right
measurement here. End-to-end abstention (did the full pipeline produce the sentinel?)
belongs in Phase 6 where the multi-model runner drives the LLM. The "Paris" case
still gets scored at Phase 5 if we check whether the retriever should have rejected
it (the answer is yes — a faithfully-calibrated 0.45 threshold should have returned
empty on an out-of-domain question), making the threshold sweep directly relevant.

---

## Recommended Approach

**Approach B (CLI orchestrator) for layering + Approach A (stratified distractors)
for corpus building + Approach C (both retrieval-level and end-to-end) for abstention.**

> **Budget note (2026-05-24):** the user explicitly relaxed the 6h budget for this
> phase — "do it right, no tech debt; best portfolio solution." The selections below
> reflect that: the `load_retriever` fix, end-to-end abstention, ADR-005, and the
> threshold sweep are all pulled into scope rather than deferred. This roughly doubles
> the original 6h estimate; `/define` should consider whether to split the PR into
> 5a (corpus + metrics) / 5b (abstention + ADR-005) for review hygiene.

Rationale:

- The CLI-orchestrator pattern is already the composition root for ingest; adding a
  pre-step there is the smallest, cleanest change that avoids import cycles and keeps
  both `eval/questions.py` and `sampler.py` unmodified.
- Stratified distractors mirror the existing sampler contract; determinism is
  preserved without new mechanisms.
- Abstention is scored **both** ways: retrieval-level (offline leading indicator) and
  end-to-end on `info_not_found` (the authoritative thesis signal, baseline model
  only — the multi-model sweep stays Phase 6). The "Paris" case is scored end-to-end.
- nDCG is a **Should**: the KB documents the formula; completing the standard IR suite
  is cheap and reviewers expect it.
- ADR-005 is a **Must**: written now at decision time, it hands Phase 6 a settled
  provider matrix and resolves the same-family judge/generator concern up front.

---

## Scope (MoSCoW)

| Priority | Item |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must | New `gold_aware_sample(documents, gold_doc_ids, distractors_per_source)` function in `ingest/sampler.py` — pure function; receives `set[str]` of gold IDs; includes all docs whose `id` is in the gold set, then adds stratified distractors; result is deterministic (ascending id within source, sources sorted). |
| Must | `--gold-aware` flag (or a distinct `--mode gold-aware` / `--mode stratified`) on `rag-ingest` CLI; the CLI pre-step streams `load_questions()`, filters answerable categories (exclude `info_not_found`), collects gold IDs, then calls `gold_aware_sample()`. |
| Must | `info_not_found` docs must NOT be pulled in by the gold-aware sampler — the sampler filters to non-`info_not_found` categories when building the gold ID set, so those questions remain legitimately unanswerable. |
| Must | `eval/retrieval_metrics.py` — pure functions over `(ranked_doc_ids: list[str], expected_doc_ids: list[str], k: int = 10) -> float                                                                                                                                                                                            | None`: `recall_at_k`, `precision_at_k`, `mrr`(returns`None`when`expected_doc_ids`is empty, per the None-empty-denominator convention from`JudgeVerdict`). |
| Must | Dedup invariant applied before all metrics: `chunk_id.split("::",1)[0]` maps chunks to docs; first occurrence per doc ID preserved in rank order. |
| Must | Abstention scoring for `info_not_found` — retrieval-level: check whether the retriever returns an empty result (cosine < 0.45) for each `info_not_found` question; compute abstention precision and abstention recall over the category. |
| Must | Per-category metric breakdown: group results by `Question.category` and report aggregate recall@k / precision@k / MRR per category; the "Paris" case anchors the `info_not_found` category. |
| Must | Unit tests for all `retrieval_metrics.py` functions (pure functions — no API, no index required): dedup invariant, recall/precision/MRR edge cases (empty expected, no hits, all hits, partial hits at various ranks), None-denominator cases. |
| Must | Unit tests for `gold_aware_sample()`: gold docs always present, `info_not_found` gold not included, distractor counts, determinism (same input → same output), empty-gold edge case. |
| Must | **Fix `load_retriever` re-chunking properly** (Q3) — build `chunk_id → doc_id` / `source_type` maps from the `embeddings.chunks.json` sidecar + LanceDB column instead of re-chunking; regression test asserts no corpus re-read. Own commit, lands before the metrics runner depends on it. |
| Must | **End-to-end abstention scoring on `info_not_found`** (Q5) — run the baseline pipeline over the `info_not_found` subset and score whether the final answer is the abstention sentinel; report end-to-end abstention precision/recall alongside the retrieval-level rate. Baseline single model only (multi-model → Phase 6). |
| Must | **ADR-005 (LLM provider/model matrix)** (Q4) — resolves the same-family judge/generator concern (ADR-003/SPRINT.md carry-forward), documents the three candidate providers (OpenAI, Anthropic, Ollama), and assigns judge vs. generator roles. Light Context7/Exa provider research feeds it before `/design`. |
| Must | **Cassette/replay test fixture for the end-to-end abstention run** — CLAUDE.md forbids mocking the LLM in eval tests; the cassette/replay pattern (the "TBD ADR in Sprint 2") must be settled in `/design`. May warrant its own small ADR (0006) — `/define` decides. |
| Should | `make build-index-gold` (or a `DOCS_PER_SOURCE` / `MODE` variant in the Makefile) that runs `rag-ingest --gold-aware` then `rag-index` to rebuild the index from the gold-aware corpus. |
| Should | ADR-002 updated with the calibrated abstention threshold — the threshold sweep on `info_not_found` produces the empirical precision/recall trade-off curve; the update records the chosen operating point. |
| Should | Abstention threshold sweep — score abstention precision/recall across a range of cosine thresholds (e.g., 0.30–0.65 in steps of 0.05) to support the ADR-002 calibration; can be a standalone script rather than a `make` target. |
| Should | nDCG@k metric added to `retrieval_metrics.py` — formula is documented in the KB; completes the standard IR metric suite (reviewers expect it); cheap given the KB formula. |
| Should | `make retrieval-eval` smoke target — runs the retrieval metrics over the gold-aware corpus on a small subset (e.g., 50 questions) for fast offline validation. |
| Could | `make retrieval-smoke-gold` — extend the existing `test_retrieval_smoke.py` to run against the new gold-aware corpus and assert Recall@10 > 0 on a broader set of questions (not just the 3 hardcoded ones from Phase 2). |
| Won't | _Multi-model_ end-to-end abstention sweep — Phase 6 (the baseline single-model end-to-end run is now in scope above; the cross-model matrix belongs with the Phase 6 runner). |
| Won't | nDCG added to the report — Phase 6; the Phase 5 job is producing the metric, not formatting it. |
| Won't | Multi-model runner or cross-family judge — Phase 6. |
| Won't | HTML/MD report generation — Phase 6. |
| Won't | Cost and latency tracking per question — Phase 6. |
| Won't | Conflict-resolution scoring on `conflicting_info` category — out of Phase 5 scope; roadmap lists it as a Sprint 2 eval primitive but it's not a retrieval metric and not part of the 6h plan. |
| Won't | Reranker tuning or retrieval architecture changes — the substrate stays fixed; Phase 5 measures it, does not improve it. |
| Won't | Encoding the full 512K-doc corpus — dev stays on the gold-aware subset; final portfolio numbers use a rented box (see roadmap). |

---

## Open Questions

1. **Category filter for the gold ID set: which categories are "answerable"?**
   The sampler must exclude `info_not_found` questions from the gold ID collection to
   preserve legitimate abstention. Are there other categories (e.g., `conflicting_info`,
   `high_level`) where `expected_doc_ids` may be empty or ambiguous? A one-time
   inspection of the `questions` config at `DATASET_REVISION` — checking whether
   `expected_doc_ids` is non-empty for each category — would confirm the exact filter.
   The design assumes `category != "info_not_found"` is sufficient; `/define` must
   validate this or narrow it to `expected_doc_ids` being non-empty (the more robust
   predicate).

   **Resolution (2026-05-24):** Use the robust predicate — a question contributes
   gold IDs only when `len(expected_doc_ids) > 0`; do **not** depend on the `category`
   string. `info_not_found` falls out for free (no gold docs), and any other
   empty-gold category is handled correctly without enumeration. `/define` confirms
   with a one-time inspection of the `questions` config at `DATASET_REVISION`
   (per-category counts + empty-`expected_doc_ids` tally), recorded as an acceptance note.

2. **Distractor count: what is the right `distractors_per_source` default?**
   The current default is 100 docs/source (900 total). The gold-aware corpus will have
   far fewer gold docs (order of hundreds across all sources); adding 50 distractors/source
   (450 total) yields roughly 600–700 docs — small enough to encode comfortably on the
   8 GB Air but large enough to keep precision@k honest. Is 50 the right default, or
   should it be configurable with no default (forcing an explicit choice)? The choice
   affects the BGE-M3 encode time and the precision signal — too few and precision is
   trivially high, too many and we approach the original 900-doc cost. This needs a
   concrete number in `/define`.

   **Resolution (2026-05-24):** `distractors_per_source = 50` is the committed default
   (configurable via CLI flag). Yields ~600–700 docs — encodes comfortably on the 8 GB
   Air and keeps precision@k honest. `/define` locks 50 as the default; the flag stays
   so the final portfolio run can scale distractors up on a rented box.

3. **`load_retriever` re-chunking bug: prerequisite for Phase 5 or tech-debt slip?**
   The anchor cases doc and REVIEW.md both flag `load_retriever` as re-chunking the
   corpus on every call (~60–90s wasted CPU) — the fix is `chunk_id.split("::",1)[0]`,
   ~15 lines. The retrieval-metrics runner will call `load_retriever` once and issue
   500 queries; if `load_retriever` is called per-question (or per-category), that's
   500× the re-chunk cost. Should the Phase 5 `retrieval_metrics` runner fix this
   incidentally (it would have to, to be usable), or is a dedicated pre-Phase-5 fix
   commit the right sequencing? Either way it should not be counted in the 6h budget.

   **Resolution (2026-05-24):** Fix it properly **inside Phase 5** — not a slipped
   tech-debt and not an incidental side effect. Build the `chunk_id → doc_id` and
   `chunk_id → source_type` maps from the persisted `embeddings.chunks.json` sidecar +
   the LanceDB `source_type` column (`chunk_id.split("::",1)[0]`) instead of
   re-chunking, with a regression test asserting `load_retriever` performs no corpus
   re-read. Budget is explicitly not the constraint; correctness at the right seam is.
   Promoted to **Must** (own commit, before the metrics runner depends on it).

4. **ADR-005 timing: write in Phase 5 or at the Phase 5/6 boundary?**
   ADR-005 (LLM provider/model matrix) resolves the same-family judge/generator concern
   from ADR-003 and SPRINT.md. It does not block any Phase 5 deliverable — no
   multi-model runner or cross-family judge is built in Phase 5. But writing it at
   decision time (before Phase 6 brainstorm) preserves the "capture-why" principle.
   Writing it early also forces a concrete three-provider decision (OpenAI / Anthropic /
   Ollama) that the Phase 6 brainstorm can treat as settled. Is there any reason to
   defer ADR-005 past the Phase 5 ship, or should it be a Should in Phase 5 (as listed
   in MoSCoW above)?

   **Resolution (2026-05-24, decided by Claude):** Write ADR-005 **in Phase 5** —
   promoted Should → **Must**. The cross-family judge requirement is already concrete
   (anchor Case 1 + the ADR-003 / SPRINT.md carry-forward), so the decision is ripe;
   writing it now preserves capture-at-decision-time and hands Phase 6 a settled
   provider matrix (OpenAI / Anthropic / Ollama, with judge-vs-generator roles
   assigned) instead of re-litigating it mid-implementation. A light Context7/Exa pass
   on OpenAI + Anthropic structured-output support and pricing runs before `/design`.

5. **Abstention signal: is retrieval-level abstention sufficient for the Phase 5
   credibility claim?**
   The "Paris" anchor case is a retrieval-level failure (the 0.45 threshold did not
   reject the query). Measuring retrieval-level abstention precision/recall on the
   `info_not_found` category is the Phase 5 deliverable. But the portfolio thesis
   ("retrieval + generation alone can't tell if an answer is grounded") is best
   demonstrated end-to-end. Does the Phase 5 milestone require the end-to-end signal
   (LLM abstention rate on `info_not_found`) to be credible, or is retrieval-level
   sufficient for the mid-checkpoint go/no-go? If end-to-end is required at Phase 5,
   it changes the scope and likely the budget.

   **Resolution (2026-05-24, decided by Claude — best-portfolio):** Score abstention
   **both** ways (Approach C). Retrieval-level abstention (offline, cheap) is the
   leading indicator; **end-to-end abstention on `info_not_found`** — does the full
   baseline pipeline emit the abstention sentinel? — is the authoritative signal that
   demonstrates the thesis and scores the "Paris" case directly. Scope it to the
   **baseline single model** over the `info_not_found` subset (the _multi-model_ sweep
   stays Phase 6). The threshold sweep is promoted to **Should** and feeds an ADR-002
   calibration update. **Dependency:** end-to-end tests must not mock the LLM
   (CLAUDE.md) → the cassette/replay pattern (the "TBD ADR in Sprint 2") must be
   settled in `/design` before this lands — flag for `/define` to scope.

---

## Next Step

→ `/define sprint-2/phase-5-retrieval-eval`
