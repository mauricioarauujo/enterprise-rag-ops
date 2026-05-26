# DEFINE: sprint-2/phase-5-retrieval-eval — Retrieval Metrics & Gold-Aware Corpus

**Sprint/Phase:** sprint-2/phase-5-retrieval-eval | **Date:** 2026-05-24

## Resolved Open Questions

The BRAINSTORM contains five **Resolution (2026-05-24)** blocks pinning every open
question. They are recorded here so `/design` and `/implement` treat them as fixed —
do **not** re-open them. Q1/Q2/Q3 were decided by the user directly; Q4/Q5 were decided
by Claude under explicit user delegation ("you decide" on ADR-0005 timing; "do the best
solution for a portfolio" on abstention). All five are **confirmed inputs, not
unconfirmed assumptions** — no orchestrator re-confirmation round is needed before
`/design`.

- **Q1 — Answerability predicate (robust, not category-string).** A question
  contributes gold IDs to the corpus **only when `len(expected_doc_ids) > 0`** — never a
  `category == "info_not_found"` string check. Empty-gold questions (including
  `info_not_found`, and any other empty-gold category) fall out for free and stay
  legitimately unanswerable. `/define` records a required one-time inspection of the
  `questions` config at `DATASET_REVISION` (per-category counts + empty-`expected_doc_ids`
  tally) as an acceptance note (AC-2).
- **Q2 — Distractor default.** `distractors_per_source = 50` is the committed default,
  configurable via CLI flag. Yields ~600–700 docs — encodes comfortably on the 8 GB Air
  and keeps precision@k honest. The flag stays so the final portfolio run can scale
  distractors up on a rented box.
- **Q3 — `load_retriever` re-chunk fix (proper, in-phase).** Build the
  `chunk_id → doc_id` and `chunk_id → source_type` maps from the persisted
  `embeddings.chunks.json` sidecar + the LanceDB `source_type` column
  (`chunk_id.split("::", 1)[0]`) instead of re-reading/re-chunking `corpus.jsonl`. A
  regression test asserts `load_retriever` performs no corpus re-read. Promoted to
  **Must**; **own commit, lands before the metrics runner depends on it.** Not a slipped
  tech-debt and not an incidental side effect — correctness at the right seam.
- **Q4 — ADR-0005 timing (in-phase).** Write **ADR-0005** (LLM provider/model matrix) in
  Phase 5 — promoted Should → **Must**. It resolves the same-family judge/generator
  concern (ADR-0003 / SPRINT.md carry-forward), documents the three candidate providers
  (OpenAI, Anthropic, Ollama), and assigns judge-vs-generator roles. A light Context7/Exa
  pass on OpenAI + Anthropic structured-output support and pricing feeds it **before
  `/design`** (pre-`/design` research, not Phase-5 code — does not block this DEFINE).
- **Q5 — Abstention signal (both ways, baseline model).** Score abstention **both**
  ways (Approach C): retrieval-level (offline, cheap leading indicator) and
  **end-to-end** on `info_not_found` (the authoritative thesis signal — does the full
  baseline pipeline emit the abstention sentinel?). Scope is the **baseline single model**
  over the `info_not_found` subset; the _multi-model_ sweep stays Phase 6. The "Paris"
  anchor case is scored end-to-end here. **Dependency:** end-to-end tests must not mock
  the LLM (CLAUDE.md) → the cassette/replay pattern must be settled in `/design` before
  this lands (see Cassette/Replay note under Acceptance Criteria and AC-16).

## Requirements

### Functional

- **FR-1 (`gold_aware_sample` pure function)** — A pure function
  `gold_aware_sample(documents, gold_doc_ids: set[str], distractors_per_source: int) -> list[Document]`
  in `ingest/sampler.py`. It includes **every** document whose `id` ∈ `gold_doc_ids`,
  then adds stratified-by-source distractors (`distractors_per_source` per source,
  selected by ascending `id`, excluding any doc already pulled in as gold), and returns
  a deterministic ordered list. The function receives only primitive types (`Document`
  iterable + `set[str]` + `int`) — it knows nothing about `Question` or `eval/`, so it
  stays fully testable without the eval layer (Decision 1 = Approach B). Determinism
  preserves NFR-1 (same revision + params → byte-identical corpus).
- **FR-2 (`--gold-aware` CLI orchestration)** — `ingest/cli.py` (the composition root)
  gains a `--gold-aware` mode. In that mode the CLI streams `load_questions()`, builds
  the gold-id set as `{id for q in questions for id in q.expected_doc_ids if q.expected_doc_ids}`
  (the **`len(expected_doc_ids) > 0`** answerability predicate, Q1 — **not** a category
  string), then calls `gold_aware_sample(documents, gold_ids, distractors_per_source)`
  and writes the result via the existing writer. The CLI orchestrator imports from both
  `ingest` and `eval` (acceptable at the composition root); the sampler does **not**
  import `eval/`. `distractors_per_source` defaults to **50** (Q2) and is exposed as a
  CLI flag.
- **FR-3 (Legitimate unanswerability preserved)** — Questions with empty
  `expected_doc_ids` (including all `info_not_found` questions) contribute **no** docs to
  the corpus, so they remain genuinely unanswerable. This is a direct consequence of the
  FR-2 predicate; no `info_not_found` doc is pulled in as gold.
- **FR-4 (`retrieval_metrics.py` pure functions)** — `eval/retrieval_metrics.py` provides
  pure functions `recall_at_k`, `precision_at_k`, and `mrr` over
  `(ranked_doc_ids: list[str], expected_doc_ids: list[str], k: int = 10) -> float | None`.
  They reuse the **None-empty-denominator convention** established by `JudgeVerdict`
  (Phase 4): an empty denominator returns `None` (= N/A), never coerced to `0.0`.
  Formulas follow `rag-retrieval/concepts/retrieval-eval-metrics.md` exactly:
  `recall@k = |R ∩ D_k| / |R|`, `precision@k = |R ∩ D_k| / k`,
  `mrr` over a query = `1 / rank_of_first_hit` (`None` when no hit in the window). No
  formula is re-derived; the KB is the source.
- **FR-5 (Dedup invariant before metrics)** — Before any metric is computed, ranked
  chunk IDs are mapped chunk→doc via `chunk_id.split("::", 1)[0]` and only the **first
  occurrence per doc ID** is retained, preserving rank order (the non-negotiable invariant
  from the KB). The deduplicated doc-ID list is what all FR-4 functions operate on.
- **FR-6 (Per-category breakdown)** — Results are grouped by `Question.category` and
  aggregate recall@k / precision@k / MRR are reported per category. The "Paris" case
  anchors the `info_not_found` category.
- **FR-7 (Retrieval-level abstention scoring)** — For the `info_not_found` category, the
  scorer evaluates whether the retriever returns `[]` (the existing behavior: empty when
  `dense_hits[0][1] < ABSTENTION_THRESHOLD`, `ABSTENTION_THRESHOLD = 0.45` in
  `retrieval/config.py:57`). It computes **abstention precision** and **abstention recall**
  over the category. This is the offline, LLM-free leading indicator.
- **FR-8 (End-to-end abstention scoring, baseline model)** — For the `info_not_found`
  subset, the scorer runs the **baseline single-model** pipeline and scores whether the
  final `AnswerWithSources.answer` equals the abstention sentinel. The sentinel is the
  `ABSTAIN_ANSWER` constant defined at `generation/cli.py:22`
  (`"I don't have enough information to answer this question."`) — the eval **imports the
  constant**, never hardcoding the string. A correct abstention also implies
  `sources == []`. It reports end-to-end abstention precision/recall alongside the
  retrieval-level rate (FR-7). The "Paris" out-of-domain anchor case (system answered
  instead of abstaining) is scored here. Multi-model is explicitly Phase 6.
- **FR-9 (`load_retriever` re-chunk fix)** — `load_retriever` is fixed to build its
  `chunk_id → doc_id` and `chunk_id → source_type` maps from the persisted
  `embeddings.chunks.json` sidecar (ordered chunk IDs) + the LanceDB `source_type` column,
  using `chunk_id.split("::", 1)[0]`, instead of re-reading/re-chunking `corpus.jsonl`
  (Q3). This is a standalone commit that lands **before** the metrics runner depends on it.
- **FR-10 (ADR-0005 written)** — `docs/adr/0005-llm-provider-matrix.md` is written and
  accepted: documents the three candidate providers (OpenAI, Anthropic, Ollama), assigns
  judge-vs-generator roles, and resolves the same-family judge/generator independence
  concern carried forward from ADR-0003 / SPRINT.md. Fed by the pre-`/design` Context7/Exa
  pass on OpenAI + Anthropic structured-output support and pricing.
- **FR-11 (Unit tests, mirrored)** — Mirrored test files cover every new/changed module:
  (a) `retrieval_metrics.py` — the dedup invariant, recall/precision/MRR edge cases
  (empty expected, no hits, all hits, partial hits at various ranks), and the
  None-denominator cases; (b) `gold_aware_sample()` — gold docs always present,
  empty-gold question excluded, distractor counts per source, determinism (same input →
  same output), and the empty-gold-**set** edge case; (c) the `load_retriever` no-re-read
  regression (asserts no `corpus.jsonl` re-read); (d) the retrieval-level and end-to-end
  abstention scorers. All FR-4/FR-5/FR-7 tests are pure functions — no API, no built index
  required.

### Non-functional

- **NFR-1 (Deterministic, byte-identical corpus)** — `gold_aware_sample()` is fully
  deterministic: the same `documents` stream + `gold_doc_ids` + `distractors_per_source`
  yields a byte-identical corpus (gold docs in a defined order, distractors ascending by
  `id` within source, sources in a stable order). This preserves the existing
  `stratified_sample()` reproducibility contract (the prior NFR-1) and keeps the
  streaming, memory-bounded design intact for the 8 GB Air.
- **NFR-2 (None=N/A metric convention reused)** — All ratio metrics return `float | None`
  with `None` meaning "not applicable" (empty denominator), reusing the `JudgeVerdict`
  precedent from Phase 4. No metric coerces an undefined ratio to `0.0`. Aggregation over
  a category skips `None` rather than averaging it in.
- **NFR-3 (Offline `make test` — no network, no key)** — `make test` runs the metric,
  dedup, sampler, `load_retriever` regression, and abstention-scorer **unit** tests with
  **no network I/O** and **no `OPENAI_API_KEY`**. The live end-to-end abstention run
  (FR-8) is never executed under `make test`: it is either gated behind a
  marker excluded from the default run or replayed from a cassette (cassette/replay
  strategy settled in `/design`, see AC-16).
- **NFR-4 (Sampler stays decoupled from eval)** — `ingest/sampler.py` has **zero** import
  edge to `eval/`. The cross-layer coordination (questions → gold-id set) lives only in
  `ingest/cli.py`, the composition root (Decision 1 = Approach B). No `ingest → eval`
  import cycle is introduced.
- **NFR-5 (Sentinel & threshold as imported SSoT)** — The end-to-end abstention scorer
  imports `ABSTAIN_ANSWER` from `generation/cli.py` and the retrieval-level scorer relies
  on `ABSTENTION_THRESHOLD` from `retrieval/config.py` — neither value is duplicated or
  hardcoded in `eval/`.
- **NFR-6 (Dependency hygiene)** — At most **one** new dev dependency (`vcrpy`,
  version-bounded) is added, **only if** `/design` adopts the cassette/replay strategy
  (AC-16). No new runtime dependency, no eval-framework library, no second provider SDK.
  `openai` and `pydantic` are already present.
- **NFR-7 (Conventions)** — New code lives in `ingest/` (sampler + CLI) and `eval/`
  (metrics + abstention scoring) with mirrored test files; ADRs use YYYY-MM-DD dates and
  English. `make lint test` (lint + pytest excluding gated markers) passes.
  Commit sequence follows Conventional Commits.
- **NFR-8 (Near-zero cash budget — hard constraint)** — The user's real budget is ~$0
  (not the Sprint-2 $50 alarm ceiling). The **only** live paid API spend permitted in
  Phase 5 is a **single recorded run** of the FR-8 end-to-end abstention over the
  `info_not_found` subset (~50 questions, estimated **< $0.05** at gpt-5-nano/gpt-4o-mini
  rates). That run is **cassette-recorded once** (AC-16) and replayed free thereafter; no
  full-500-question live run occurs in Phase 5. Dev iteration uses `StubGenerator` or a
  local **Ollama** model at **$0**. `/design` must therefore make the cassette/replay the
  default path and any live call opt-in (marker-gated) — never on the `make test` path
  (NFR-3). Everything else in the phase (sampling, retrieval metrics, retrieval-level
  abstention) is local compute at $0.

## Acceptance Criteria

1. `gold_aware_sample(documents, gold_doc_ids, distractors_per_source)` is a pure
   function in `ingest/sampler.py`: given a `documents` iterable, a `set[str]` of gold
   IDs, and an int distractor count, it returns a list containing **every** doc whose
   `id ∈ gold_doc_ids` plus exactly `distractors_per_source` non-gold docs per source
   (or all available if fewer), selected by ascending `id`; the result is a deterministic
   ordered list. Verified by a unit test over a hand-built document set.
2. **Answerability inspection (Q1 acceptance note):** a one-time inspection of the
   `questions` config at `DATASET_REVISION` is recorded — per-category counts plus the
   tally of questions with empty `expected_doc_ids` — confirming that the
   `len(expected_doc_ids) > 0` predicate (not a `category` string) is the correct
   answerability filter and that `info_not_found` (and any other empty-gold category)
   falls out for free.
3. `rag-ingest --gold-aware` streams `load_questions()`, builds the gold-id set using the
   `len(expected_doc_ids) > 0` predicate, calls `gold_aware_sample()` with
   `distractors_per_source` defaulting to **50** (overridable via flag), and writes a
   corpus of roughly 600–700 docs to `CORPUS_PATH`. Verified by running the mode and
   asserting the corpus contains all gold IDs for answerable questions and the expected
   per-source distractor counts.
4. No `info_not_found` (or other empty-`expected_doc_ids`) question contributes any doc
   to the gold-aware corpus; those questions remain unanswerable. Verified by a unit test
   asserting an empty-gold question yields no gold docs.
5. `recall_at_k`, `precision_at_k`, and `mrr` in `eval/retrieval_metrics.py` are pure
   functions returning `float | None`; given hand-built `(ranked_doc_ids, expected_doc_ids, k)`
   they return the KB formulas (`|R∩D_k|/|R|`, `|R∩D_k|/k`, `1/rank_of_first_hit`); an
   empty `expected_doc_ids` (empty denominator) returns `None`, never `0.0`. No network or
   index access.
6. The dedup invariant is applied before every metric: a ranked list with multiple chunks
   from the same doc (`doc::0`, `doc::1`) collapses to the first occurrence per doc ID in
   rank order via `chunk_id.split("::", 1)[0]`. Verified by a unit test on a list with
   intra-doc duplicates.
7. Metric edge cases are covered and total: empty expected, no hits, all hits, and partial
   hits at various ranks each produce the defined value (`None` for empty-denominator
   cases). Verified by parametrized unit tests.
8. Results are grouped by `Question.category` and aggregate recall@k / precision@k / MRR
   are reported per category. Verified by a test over a small multi-category input asserting
   per-category aggregation (with `None` values skipped, not averaged in).
9. Retrieval-level abstention scoring: for the `info_not_found` category the scorer treats
   a `[]` retriever result (best dense hit `< ABSTENTION_THRESHOLD = 0.45`) as a correct
   abstention and computes abstention precision and recall over the category. Verified by a
   unit test feeding synthetic retrieval results (no live index).
10. End-to-end abstention scoring (baseline single model): the scorer compares the final
    `AnswerWithSources.answer` against `ABSTAIN_ANSWER` **imported** from `generation/cli.py`
    (never hardcoded); a correct abstention also has `sources == []`. It reports end-to-end
    abstention precision/recall alongside the retrieval-level rate. The "Paris" out-of-domain
    case (answered instead of abstaining) is exercised. The live run is offline-replayed or
    marker-gated (AC-16); `make test` never issues a live call.
11. `load_retriever` builds `chunk_id → doc_id` and `chunk_id → source_type` maps from the
    `embeddings.chunks.json` sidecar + the LanceDB `source_type` column (via
    `chunk_id.split("::", 1)[0]`) and does **not** re-read/re-chunk `corpus.jsonl`. A
    regression test asserts no `corpus.jsonl` read occurs during `load_retriever`. This
    lands as its **own commit before** the metrics runner depends on it.
12. `gold_aware_sample()` determinism: the same input (documents + gold set + distractor
    count) yields a byte-identical ordered output across two invocations. Verified by a
    unit test comparing two runs; the empty-gold-**set** edge (no gold IDs → distractors
    only) is also covered.
13. `docs/adr/0005-llm-provider-matrix.md` is written and accepted: it documents the three
    candidate providers (OpenAI, Anthropic, Ollama), assigns judge-vs-generator roles, and
    resolves the same-family judge/generator independence concern (ADR-0003 / SPRINT.md
    carry-forward).
14. (Should) `nDCG@k` is added to `retrieval_metrics.py` following the KB formula
    (`DCG@k / IDCG@k`, `rel_i ∈ {0,1}`), returns `float | None`, and is unit-tested for the
    perfect-ranking (=1.0), no-hit (`None`/`0.0` per the pinned convention), and
    partial-ranking cases. Absence does not fail the phase.
15. (Should) The abstention threshold sweep (0.30–0.65, step 0.05) runs as a standalone
    script over `info_not_found`, producing the precision/recall trade-off curve;
    `docs/adr/0002-*.md` is updated with the chosen operating point; `make build-index-gold`
    and `make retrieval-eval` targets exist. Absence does not fail the phase.
16. **Cassette/replay strategy is settled in `/design`** (see note below): `make test`
    stays offline (no network, no `OPENAI_API_KEY`) for the FR-8 live end-to-end run, either
    via a version-bounded `vcrpy` dev dep + recorded cassette (likely a new **ADR-0006**) or
    a marker-gated live path. The mechanism is a `/design` decision; this AC fixes only the
    invariant that `make test` never hits the network.

> **Cassette/replay note (the one genuinely-open design dependency).** CLAUDE.md forbids
> mocking the LLM in eval tests, `vcrpy` is **not** yet in `pyproject.toml`, and **no**
> cassette/replay ADR exists (the "TBD ADR in Sprint 2"). This does **not** block the
> DEFINE, but it **must** be resolved in `/design` before the FR-8 live end-to-end run
> lands. **Recommendation:** adopt the cassette/replay pattern as **ADR-0006** plus a
> version-bounded `vcrpy` dev dependency (NFR-6); the recorded cassette lets the live
> abstention test replay offline under `make test`, and the record path is marker-gated.
> This is the cleanest portfolio-grade resolution and keeps `make test` deterministic
> and network-free.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ----------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit with evidence: the current stratified subset (900 docs) contains gold `expected_doc_ids` for only ~3 of 500 questions, so recall@k is near-zero **by construction** — a coverage artifact, not a retrieval failure. Phase 5 fixes the prerequisite (gold-aware corpus) then layers on real metrics + abstention scoring. The "Paris" anchor case is concrete evidence of the abstention gap.        |
| Users       | 2     | Consumers are the downstream Phase 6 multi-model runner/report (named) and the maintainer calibrating the abstention threshold. Internal eval-harness phase — no external end user, so workflow-impact is inherently thin (scored honestly, consistent with the Phase 1–4 DEFINEs).                                                                                                                                     |
| Success     | 3     | 16 numbered, falsifiable acceptance criteria, each with a concrete pass/fail check covering every FR/NFR: the sampler contract + determinism, the answerability inspection, the metric formulas + None-denominator + dedup invariant, per-category breakdown, both abstention scorers (imported sentinel/threshold), the `load_retriever` regression, ADR-0005, the offline-CI invariant, and the Should-tier items.    |
| Scope       | 3     | Full MoSCoW in the BRAINSTORM with an explicit Won't list (multi-model end-to-end sweep, multi-model runner, HTML/MD report, cost/latency tracking, `conflicting_info` scoring, reranker/architecture changes, full 512K-corpus encode). Budget intentionally relaxed by the user ("do it right, no tech debt") with scope pulled in (load_retriever fix, end-to-end abstention, ADR-0005, sweep) rather than deferred. |
| Constraints | 3     | All constraints named as NFRs: deterministic byte-identical corpus (NFR-1), None=N/A metric convention (NFR-2), offline `make test` with no key (NFR-3), sampler decoupled from eval / no import cycle (NFR-4), imported sentinel + threshold SSoT (NFR-5), dependency hygiene ≤1 new dev dep (NFR-6), conventions (NFR-7).                                                                                             |

**Total: 14/15 — PASS (≥12).** Users scored 2: an internal eval-harness phase whose
"user" is the Phase 6 runner plus the maintainer, so workflow-impact is inherently thin —
acceptable, not a blocker, and consistent with the Phase 1–4 DEFINEs. All five BRAINSTORM
open questions are resolved with confirmed inputs (Q1–Q3 user-decided, Q4–Q5 Claude-decided
under explicit delegation), so no `AskUserQuestion` round was needed; no ambiguity was
invented beyond what the BRAINSTORM closed. The cassette/replay strategy is the one
genuinely-open design dependency, but it is correctly deferred to `/design` (AC-16) and
does not lower the DEFINE's clarity.

## Infrastructure Readiness

| Dependency                                        | KB domain        | Specialist | Status                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------------------- | ---------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HF `questions` config @ `DATASET_REVISION`        | none needed      | none       | Ready — same pinned SHA as Phase 1/2/4; `load_questions()` (the single typed reader of `expected_doc_ids`) imports `DATASET_REVISION` from `enterprise_rag_ops.ingest.config` (single SSoT). A one-time per-category inspection (AC-2) confirms the empty-gold tally.                                                                                 |
| `Question` loader (`eval/questions.py`, Phase 4)  | `rag-eval`       | none       | Ready — frozen `Question(question_id, question, answer_facts, expected_doc_ids, category)`; `category == question_type`. The CLI orchestrator (FR-2) streams it to build the gold-id set; reused unchanged.                                                                                                                                           |
| `AnswerWithSources` + `ABSTAIN_ANSWER` (Phase 3)  | `rag-generation` | none       | Ready — `AnswerWithSources` in `generation/schema.py`; `ABSTAIN_ANSWER` constant at `generation/cli.py:22`. The end-to-end abstention scorer (FR-8) imports the constant (NFR-5); never hardcoded. Reused unchanged.                                                                                                                                  |
| `Chunk` / chunk→doc dedup invariant (Phase 2)     | `rag-retrieval`  | none       | Ready — `chunk_id = f"{doc_id}::{offset}"`; dedup is `chunk_id.split("::", 1)[0]`, first occurrence per doc. KB `concepts/retrieval-eval-metrics.md` documents the non-negotiable invariant. Reused unchanged.                                                                                                                                        |
| LanceDB `embeddings.chunks.json` sidecar + column | `rag-retrieval`  | none       | Ready — the sidecar lists ordered chunk IDs and LanceDB has a `source_type` column; FR-9 builds the `chunk_id → doc_id` / `source_type` maps from them (no corpus re-read). Reused unchanged.                                                                                                                                                         |
| `ABSTENTION_THRESHOLD` (`retrieval/config.py:57`) | `rag-retrieval`  | none       | Ready — `= 0.45`; `hybrid_retriever.py` returns `[]` when best dense hit `< ABSTENTION_THRESHOLD`. The retrieval-level scorer (FR-7) relies on it; the Should-tier sweep varies it 0.30–0.65 and feeds an ADR-0002 update.                                                                                                                            |
| `openai` Python SDK (live e2e run)                | none needed      | none       | Ready — already a runtime dep (`openai>=1.50,<2.0`); the baseline e2e abstention run reuses the existing `OpenAIGenerator` path. No new dep. Needs `OPENAI_API_KEY` only for the live record; `make test` runs offline (NFR-3).                                                                                                                       |
| `pydantic` (schemas)                              | none needed      | none       | Ready — already a runtime dep (`pydantic>=2.6,<3.0`). No new dep.                                                                                                                                                                                                                                                                                     |
| `vcrpy` (cassette/replay)                         | none needed      | none       | **New dev dep — conditional on `/design`.** Added (version-bounded) **only if** `/design` adopts the cassette/replay strategy (likely ADR-0006) for the FR-8 live run (NFR-6). Non-blocking for the DEFINE; the invariant `make test` must enforce is offline-only (AC-16).                                                                           |
| ADR-0005 provider research (OpenAI/Anthropic)     | none needed      | none       | **Pre-`/design`, not blocking the DEFINE.** A light Context7/Exa pass on OpenAI + Anthropic structured-output support + pricing feeds ADR-0005 (FR-10/AC-13) **before** `/design`, per SPRINT.md Knowledge Plan. Flagged as research pre-work, not Phase-5 code.                                                                                      |
| `rag-retrieval` KB domain                         | `rag-retrieval`  | none       | Ready — `concepts/retrieval-eval-metrics.md` (conf 0.90) supplies recall@k / precision@k / MRR / nDCG formulas (k=10) and the dedup invariant; consumed directly (FR-4/FR-5). Sufficient; no `/new-kb` needed.                                                                                                                                        |
| `rag-eval` KB domain                              | `rag-eval`       | none       | **Exists (draft, Phase 4) but covers the judge layer only — not retrieval metrics or abstention scoring.** Documenting the new retrieval-metric + abstention-scoring design is **knowledge-loop `/update-kb rag-eval` work AFTER this phase** (per SPRINT.md Knowledge Plan). Non-blocking for `/implement`.                                          |
| Eval/retrieval specialist agent                   | n/a              | none       | **Not warranted yet.** Pure metric functions + a deterministic sampler + two abstention scorers are small, single-pass builds with no repeated specialist context-loading — consistent with Phase 4's reasoning. Revisit only if Phase 6 (multi-model runner, report) surfaces repeated friction (then a `**Harness suggestion:**` for `/new-agent`). |

No `/new-kb` or `/new-agent` blocks Phase 5. Three non-blocking items are logged for the
orchestrator: (1) ADR-0005 provider research is **pre-`/design`** (not Phase-5 code);
(2) `/update-kb rag-eval` for the retrieval-metric + abstention-scoring design is sequenced
**after** this phase; (3) no specialist agent is recommended. All ambiguity has a confirmed
BRAINSTORM input; the only genuinely-open design dependency is the cassette/replay strategy,
correctly deferred to `/design` (AC-16).

## Sequencing Notes (not requirements)

- **Scope ~doubles the original 6h** (budget intentionally relaxed by the user). Recommend
  delivery as **one phase / one PR** (consistent with the SDD one-branch-one-PR model) with
  a disciplined commit sequence: (1) `load_retriever` re-chunk fix, (2) gold-aware sampler,
  (3) `retrieval_metrics` + dedup invariant, (4) abstention scoring (retrieval-level +
  end-to-end), (5) ADR-0005 + ADR-0002 update. Splitting into 5a (corpus + metrics) / 5b
  (abstention + ADR-0005) is **possible but not recommended** — it fractures the SDD
  artifacts for one logically-coupled phase. Surface as an option; default to one PR.
- **Cassette/replay (AC-16)** is the one genuinely-open design dependency. It does **not**
  block this DEFINE but must be resolved in `/design` before the FR-8 live end-to-end run
  lands; recommended resolution is ADR-0006 + a version-bounded `vcrpy` dev dep.

## Next Step

→ `/design sprint-2/phase-5-retrieval-eval`
