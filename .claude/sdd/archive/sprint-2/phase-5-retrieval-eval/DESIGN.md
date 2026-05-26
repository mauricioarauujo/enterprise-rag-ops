# DESIGN: sprint-2/phase-5-retrieval-eval — Retrieval Metrics & Gold-Aware Corpus

**Sprint/Phase:** sprint-2/phase-5-retrieval-eval | **Date:** 2026-05-24

## Architecture

Phase 5 has four logically-coupled but cleanly-separable build streams. All five
BRAINSTORM open questions (Q1–Q5) are CLOSED in the DEFINE and are treated here as
fixed inputs, not re-opened.

### 1. Gold-aware corpus (ingest layer)

```
ingest/cli.py  (--gold-aware mode = composition root)
   │
   ├─ eval/questions.load_questions()           # stream Question objects (Phase 4, unchanged)
   │     └─ gold_ids = {id for q in qs for id in q.expected_doc_ids if q.expected_doc_ids}   # Q1 predicate
   │
   └─ ingest/sampler.gold_aware_sample(documents, gold_ids, distractors_per_source)  # FR-1, pure
         └─ write_corpus(...)                    # existing writer, unchanged
```

The cross-layer edge (`questions → gold-id set`) lives **only** in `ingest/cli.py`, the
composition root. `ingest/sampler.py` receives primitives (`Iterable[Document]`,
`set[str]`, `int`) and has **zero** import edge to `eval/` (Decision 1 = Approach B,
NFR-4). This mirrors the existing `stratified_sample` shape — `gold_aware_sample` is its
gold-augmented sibling in the same module.

### 2. Retrieval metrics (eval layer, pure)

```
ranked_chunk_ids  ──dedup(chunk_id.split("::",1)[0], first-wins)──▶  ranked_doc_ids
                                                                          │
   eval/retrieval_metrics.py:  recall_at_k / precision_at_k / mrr [ / ndcg_at_k (Should) ]
        └─ float | None  (None = empty denominator, the JudgeVerdict precedent)
```

Dedup (FR-5) is the non-negotiable invariant from
`rag-retrieval/concepts/retrieval-eval-metrics.md` and runs **before** any metric. The
formulas are copied from that KB concept verbatim — no re-derivation (FR-4). The
None-empty-denominator convention is reused from Phase 4's `JudgeVerdict` (NFR-2).

### 3. Abstention scoring (eval layer)

Two scorers over the `info_not_found` category (the "Paris" anchor case lives here):

- **Retrieval-level (FR-7)** — offline, LLM-free. Reads `ABSTENTION_THRESHOLD` from
  `retrieval/config.py` (imported, never duplicated — NFR-5). Treats a `[]` retriever
  result (best dense hit `< 0.45`) as a correct abstention; computes abstention
  precision/recall. Tested with synthetic retrieval results, no live index.
- **End-to-end (FR-8)** — baseline single model. Runs the real pipeline and compares
  `AnswerWithSources.answer` against `ABSTAIN_ANSWER` **imported** from
  `generation/cli.py` (NFR-5); a correct abstention also implies `sources == []`. This
  is the one path that issues a live LLM call — recorded once, replayed offline forever
  after (see Cassette/Replay below). Multi-model sweep is explicitly Phase 6.

### 4. `load_retriever` re-chunk fix (retrieval layer)

`pipeline.load_retriever` currently re-reads and re-chunks `corpus.jsonl` to rebuild the
`chunk_id → doc_id` / `chunk_id → source_type` maps (`pipeline.py:128–133`). FR-9
rebuilds them instead from the persisted `embeddings.chunks.json` sidecar (ordered chunk
IDs, `config.CHUNK_ORDER_PATH`) + the LanceDB `source_type` column, via
`chunk_id.split("::", 1)[0]`. This is its **own commit, landing before** the metrics
runner depends on it (Q3). The DEFINE wording "a regression test asserts no corpus
re-read" is honoured by spying on `read_corpus` / `chunk_document` in the test.

### Data flow (end-to-end abstention, the only live path)

```
info_not_found questions ─▶ load_retriever() ─▶ retrieve_chunks()
   │                                                    │
   │  [] (abstain)                          non-empty ──┘
   │     │                                       │
   │     └─▶ ABSTAIN_ANSWER, sources=[]          └─▶ ContextAssembler ─▶ OpenAIGenerator
   │                                                                          │
   └────────────────────────── score answer == ABSTAIN_ANSWER ◀──────────────┘
                          (recorded once via cassette → replayed under make test)
```

## File Manifest

Every owner is `direct`: the DEFINE concluded no specialist is warranted (pure metric
functions + a deterministic sampler + two scorers are small single-pass builds with no
repeated specialist context — consistent with Phase 4). The only agents in
`.claude/agents/` are workflow/KB specialists (`code-reviewer`, `kb-architect`,
brainstorm/define/design agents); none own `src/eval` or `src/retrieval` code.

| File                                                    | Change  | Owner  | Phase order | Covers                                                                                                |
| ------------------------------------------------------- | ------- | ------ | ----------- | ----------------------------------------------------------------------------------------------------- |
| `src/enterprise_rag_ops/ingest/config.py`               | edit    | direct | 1 (config)  | FR-2 (`DEFAULT_DISTRACTORS_PER_SOURCE = 50`, Q2)                                                      |
| `src/enterprise_rag_ops/retrieval/pipeline.py`          | edit    | direct | 2 (core)    | FR-9, AC-11 — **own commit, lands first**                                                             |
| `tests/retrieval/test_pipeline_loader.py`               | created | direct | 2 (tests)   | FR-11c, AC-11 (no-re-read regression)                                                                 |
| `src/enterprise_rag_ops/ingest/sampler.py`              | edit    | direct | 3 (core)    | FR-1, NFR-1, AC-1 (`gold_aware_sample`)                                                               |
| `src/enterprise_rag_ops/ingest/cli.py`                  | edit    | direct | 3 (core)    | FR-2, FR-3, AC-3 (`--gold-aware` orchestration)                                                       |
| `tests/ingest/test_sampler.py`                          | edit    | direct | 3 (tests)   | FR-11b, AC-1/4/12 (gold present, empty-gold excluded, distractor counts, determinism, empty-gold-set) |
| `tests/ingest/test_cli.py`                              | edit    | direct | 3 (tests)   | FR-2/FR-3, AC-3/4 (`--gold-aware` wiring, predicate, info_not_found excluded)                         |
| `src/enterprise_rag_ops/eval/retrieval_metrics.py`      | created | direct | 4 (eval)    | FR-4, FR-5, NFR-2, AC-5/6/7; AC-14 nDCG (Should)                                                      |
| `tests/eval/test_retrieval_metrics.py`                  | created | direct | 4 (tests)   | FR-11a, AC-5/6/7/12; AC-14 (Should)                                                                   |
| `src/enterprise_rag_ops/eval/retrieval_eval.py`         | created | direct | 4 (eval)    | FR-6, AC-8 (per-category aggregation; None-skipping)                                                  |
| `tests/eval/test_retrieval_eval.py`                     | created | direct | 4 (tests)   | FR-6, AC-8 (multi-category aggregation)                                                               |
| `src/enterprise_rag_ops/eval/abstention.py`             | created | direct | 4 (eval)    | FR-7, FR-8, NFR-5, AC-9/10 (both scorers; imported sentinel + threshold)                              |
| `tests/eval/test_abstention.py`                         | created | direct | 4 (tests)   | FR-11d, AC-9/10 (retrieval-level synthetic; e2e Paris anchor, offline-replayed)                       |
| `tests/eval/conftest.py`                                | edit    | direct | 6 (tests)   | AC-16, NFR-3 (cassette fixture/marker wiring)                                                         |
| `tests/eval/cassettes/abstention_info_not_found.yaml`   | created | direct | 6 (tests)   | AC-16, NFR-8 (recorded FR-8 run, replayed offline)                                                    |
| `pyproject.toml`                                        | edit    | direct | 2 (config)  | NFR-6 (one dev dep `vcrpy`; new `live`/`vcr` marker)                                                  |
| `docs/adr/0005-llm-provider-matrix.md`                  | created | direct | 7 (ADR)     | FR-10, AC-13                                                                                          |
| `docs/adr/0006-cassette-replay.md`                      | created | direct | 7 (ADR)     | AC-16 (cassette/replay decision record)                                                               |
| `docs/adr/README.md`                                    | edit    | direct | 7 (ADR)     | index rows for ADR-0005, ADR-0006                                                                     |
| `Makefile`                                              | edit    | direct | 7 (Should)  | AC-15 (`build-index-gold`, `retrieval-eval` targets)                                                  |
| `src/enterprise_rag_ops/eval/threshold_sweep.py`        | created | direct | 7 (Should)  | AC-15 (0.30–0.65 sweep script)                                                                        |
| `docs/adr/0002-retrieval-architecture.md`               | edit    | direct | 7 (Should)  | AC-15 (chosen operating point)                                                                        |
| `.claude/sdd/features/.../DEFINE.md` answerability note | record  | direct | (note)      | AC-2 (Q1 one-time inspection tally, recorded as an acceptance note)                                   |

Notes on placement choices:

- **`retrieval_metrics.py` vs `retrieval_eval.py` split.** Pure scalar formulas (FR-4/5,
  AC-14) live in `retrieval_metrics.py` — the smallest pure-function surface, no
  `Question` import, fully unit-testable. Per-category aggregation (FR-6, which imports
  `Question.category`) lives in `retrieval_eval.py`. This keeps the metrics file as
  decoupled as the sampler and matches the KB's framing of formulas-vs-harness.
- **`abstention.py` is a single eval module** holding both scorers (FR-7 retrieval-level
  and FR-8 end-to-end). They share the `info_not_found` subset and the
  precision/recall reporting shape; splitting them would be premature.
- **No edit to `eval/questions.py`, `generation/cli.py`, `generation/schema.py`,
  `retrieval/config.py`, `retrieval/hybrid_retriever.py`.** They are consumed unchanged
  (Infrastructure Readiness rows confirm "reused unchanged"). `ABSTAIN_ANSWER` and
  `ABSTENTION_THRESHOLD` are imported as SSoT (NFR-5), not edited.

## Implementation Phases

One PR, disciplined commit sequence (DEFINE Sequencing Notes; one-branch-one-PR SDD
model). The 5a/5b split (corpus+metrics / abstention+ADRs) is **possible but not
adopted** — it fractures the SDD artifacts for one logically-coupled phase.

1. **`load_retriever` re-chunk fix — its OWN commit, lands FIRST (FR-9, AC-11).**
   Rebuild the `chunk_id → doc_id` / `chunk_id → source_type` maps from
   `config.CHUNK_ORDER_PATH` (sidecar) + the LanceDB `source_type` column; drop the
   `read_corpus`/`chunk_document` loop. Add `tests/retrieval/test_pipeline_loader.py`
   asserting no `corpus.jsonl` read occurs (spy on `read_corpus`). Commit:
   `fix(retrieval): build load_retriever maps from sidecar, no corpus re-chunk`.
   _Rationale for landing first: the metrics/abstention runner constructs the retriever
   via `load_retriever`; the correctness fix must precede the consumer (Q3)._

2. **Gold-aware sampler + CLI (FR-1, FR-2, FR-3; NFR-1, NFR-4).** Add
   `DEFAULT_DISTRACTORS_PER_SOURCE = 50` to `ingest/config.py`. Add `gold_aware_sample`
   to `ingest/sampler.py` (gold-first, then ascending-id distractors per source
   excluding gold, deterministic order). Add `--gold-aware` mode + `--distractors-per-source`
   flag to `ingest/cli.py` (composition root: streams `load_questions`, builds gold set
   via the `len(expected_doc_ids) > 0` predicate). Extend `test_sampler.py` and
   `test_cli.py`. Record the AC-2 answerability inspection as a one-time note. Commit:
   `feat(ingest): gold-aware corpus sampling (--gold-aware)`.

3. **Retrieval metrics + dedup invariant (FR-4, FR-5, FR-6; NFR-2).** Create
   `eval/retrieval_metrics.py` (dedup + recall/precision/mrr, `float | None`) and
   `eval/retrieval_eval.py` (per-category aggregation, None-skipping). Mirrored tests.
   Commit: `feat(eval): retrieval metrics (recall/precision/MRR) with doc-level dedup`.

4. **Abstention scoring — retrieval-level + end-to-end (FR-7, FR-8; NFR-5).** Create
   `eval/abstention.py` (both scorers; import `ABSTENTION_THRESHOLD` and
   `ABSTAIN_ANSWER`). Add `vcrpy` dev dep + the `vcr` marker to `pyproject.toml`, wire
   the cassette fixture in `tests/eval/conftest.py`, record
   `tests/eval/cassettes/abstention_info_not_found.yaml` once (the single < $0.05 live
   run, NFR-8), and add `tests/eval/test_abstention.py` (synthetic retrieval-level; e2e
   Paris anchor replayed offline). Commit:
   `feat(eval): abstention scoring (retrieval-level + cassette-replayed e2e)`.

5. **ADRs + docs (FR-10, AC-13, AC-16).** Write `docs/adr/0005-llm-provider-matrix.md`
   (OpenAI / Anthropic / Ollama; judge-vs-generator roles; resolve the ADR-0003
   same-family carry-forward) and `docs/adr/0006-cassette-replay.md` (the cassette/replay
   decision). Update `docs/adr/README.md` index. Commit:
   `docs(adr): ADR-0005 LLM provider matrix + ADR-0006 cassette/replay`.

6. **(Should) Threshold sweep + Makefile + ADR-0002 update (AC-14, AC-15).** Add
   `ndcg_at_k` to `retrieval_metrics.py` (already slotted in step 3 if time allows),
   `eval/threshold_sweep.py` (0.30–0.65, step 0.05), `make build-index-gold` /
   `make retrieval-eval` targets, and the chosen operating point into
   `docs/adr/0002-retrieval-architecture.md`. **Absence does not fail the phase.** Commit:
   `feat(eval): abstention threshold sweep + retrieval-eval targets (Should)`.

Phase order matches the convention: schema/dataset → config → core `src/` → eval `eval/`
→ tests (interleaved per module per the mirrored-test convention) → docs + ADR.
Observability hooks (Sprint 3) are out of scope, so that convention slot is empty.

## Cassette/Replay Decision (AC-16 — the one genuinely-open dependency)

**Decision: ADOPT the cassette/replay pattern as ADR-0006 + a version-bounded `vcrpy`
dev dependency.** This confirms the DEFINE recommendation. Rationale, grounded in the
code I read:

- The current test suite has **no live LLM call anywhere**. Phase 4's `OpenAIJudge` is
  tested offline via an injected `FakeOpenAIClient` (`tests/eval/conftest.py`,
  `test_openai_judge.py`), and `make smoke` / `make retrieval-smoke` are marker-gated
  and excluded from `make test`. So the repo already keeps the live path off the default
  test run — the question is purely how FR-8's e2e abstention assertion gets a
  deterministic, offline LLM response.
- CLAUDE.md / AGENTS.md § Conventions forbid mocking the LLM API in eval tests and name
  the cassette/replay pattern as a "TBD ADR in Sprint 2." A `FakeOpenAIClient`-style fake
  (the judge approach) is acceptable for call-shape/prompt assertions but would be a
  _mock of the eval LLM response_ if used to assert FR-8's answer-equals-sentinel
  outcome — that is exactly what the convention forbids for the eval assertion. The
  cassette records a **real** response once and replays it byte-for-byte, satisfying both
  the convention and NFR-8's "single recorded run, free thereafter."
- ADR-0003's "Alternatives Considered" already earmarked the cassette pattern for
  "ADR-001 in Sprint 2" — ADR-0006 is the correct venue to record it now (ADR-0004 is
  the planned observability slot, ADR-0005 the provider matrix, so 0006 is the next free
  number).

Concrete mechanism (reflected in the manifest):

- **Dependency (NFR-6):** add `vcrpy` (version-bounded, e.g. `vcrpy>=6.0,<7.0`) to the
  `[dependency-groups] dev` block in `pyproject.toml` — the single permitted new dev
  dep. No runtime dep, no second provider SDK.
- **Marker:** register a new `vcr` marker in `pyproject.toml` `[tool.pytest.ini_options]
markers` (alongside `slow`/`integration`/`corpus`/`smoke`). The FR-8 e2e abstention
  test carries `@pytest.mark.vcr`.
- **Offline default (NFR-3, NFR-8):** `make test` runs `-m "not corpus and not smoke"`.
  The `vcr`-marked test is **included** in `make test` but runs in vcrpy's default
  `record_mode="none"` — it replays from the cassette and **fails (never records) if the
  cassette is missing or a request is unmatched**, so it can never silently hit the
  network or require `OPENAI_API_KEY`. The record path is opt-in via an explicit
  `--record-mode=once` (or env-gated `record_mode`) run by the maintainer once, locally,
  with a key — never on the `make test` or CI path. (If a future contributor prefers
  zero new deps, the fallback is to give the e2e test the existing `smoke` marker so it
  is simply excluded from `make test`; rejected here because it removes the e2e
  abstention from the default gate, weakening the regression signal. Recorded as the
  rejected alternative in ADR-0006.)
- **Cassette location:** `tests/eval/cassettes/abstention_info_not_found.yaml`, committed
  to the repo (it contains only the benchmark question + model response, no secret — the
  recording step scrubs the `Authorization` header via vcrpy's `filter_headers`).
- **conftest wiring:** `tests/eval/conftest.py` gains the vcrpy config fixture
  (cassette_library_dir, `filter_headers=["authorization"]`, `record_mode="none"` by
  default).

## Infrastructure Gaps

Three-layer deep scan. **No gap blocks `/implement`.** Two items are _known/sequenced_
(logged in the DEFINE), not new blockers.

| Gap Type              | Area                                                | Detail                                                                                                                                                                                                                                                                 | Recommendation                                                                                   |
| --------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Missing domain        | retrieval-eval metrics                              | None — `rag-retrieval/concepts/retrieval-eval-metrics.md` (conf 0.90) supplies recall@k / precision@k / MRR / nDCG + the dedup invariant. Consumed directly by FR-4/FR-5.                                                                                              | None.                                                                                            |
| Missing domain        | abstention scoring                                  | None — `rag-retrieval` (threshold) + `rag-eval` (None convention) cover the inputs. The _design_ of abstention scoring is new but small.                                                                                                                               | None for `/implement`.                                                                           |
| Missing domain        | LLM provider matrix / cassette                      | None — these are ADR decisions (0005/0006), not KB domains. `vcrpy` usage is standard; no KB needed.                                                                                                                                                                   | None.                                                                                            |
| Missing concept       | `rag-eval` — retrieval metrics + abstention scoring | `rag-eval` is draft and covers the **judge layer only** (per-fact recall/precision, per-doc faithfulness, None convention). It does NOT yet document retrieval metrics or abstention scoring. **Known & sequenced** in the DEFINE as a post-phase knowledge-loop item. | `/update-kb rag-eval` **AFTER** this phase (not a blocker for `/implement`).                     |
| Missing specialist    | eval / retrieval                                    | No eval/retrieval specialist agent exists; existing agents are workflow/KB only. DEFINE concluded **not warranted yet** — small single-pass builds, no repeated specialist context. Revisit only if Phase 6 (multi-model runner/report) surfaces repeated friction.    | None now; a `**Harness suggestion:**` for `/new-agent` only if Phase 6 repeats the context-load. |
| Pre-`/design` prework | ADR-0005 provider research                          | Light Context7/Exa pass on OpenAI + Anthropic structured-output support + pricing. **Logged in the DEFINE as pre-`/design` research, not Phase-5 code.** Feeds ADR-0005 / FR-10. Assumed complete before `/implement` writes ADR-0005.                                 | Confirm research notes exist before writing `docs/adr/0005-*.md`. Not a code blocker.            |

**Agent-alignment layer:** the relevant KB domains (`rag-retrieval`, `rag-eval`,
`rag-generation`-equivalent via `generation/`) are all consumed `direct` in this phase;
no specialist agent's `kb_domains` needs updating because no specialist owns this work.
`code-reviewer` (`kb_domains: []`) handles the `/review` stage and reads KB ad hoc.

**Verdict:** no `/new-kb` and no `/new-agent` blocks Phase 5. The only conditional
dependency — `vcrpy` — is resolved by the cassette/replay decision above (ADR-0006).

## Consistency Check

Non-trivial, multi-module phase (>2 modules, DEFINE has 5 resolved questions) — full
6-pass run. **Verdict: ✅ CONSISTENT** (no CRITICAL/HIGH; three LOW notes recorded).

| ID  | Severity | Pass                 | Location                                     | Finding                                                                                                                                                                                                                                                                                                                                                             | Suggested fix                                                                                                                                                               |
| --- | -------- | -------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | LOW      | 3 Underspecification | FR-2 / ingest/config.py                      | FR-2 fixes `distractors_per_source` default = 50 but does not name a config constant; existing pattern uses `DEFAULT_DOCS_PER_SOURCE`. Manifest adds `DEFAULT_DISTRACTORS_PER_SOURCE` for symmetry — confirm this is the intended SSoT.                                                                                                                             | Add `DEFAULT_DISTRACTORS_PER_SOURCE = 50` to `ingest/config.py` (done in manifest); CLI flag defaults to it.                                                                |
| C2  | LOW      | 6 Inconsistency      | AC-14 / nDCG no-hit value                    | AC-14 says nDCG no-hit returns "`None`/`0.0` per the pinned convention" — ambiguous between the two. NFR-2 pins None=empty-denominator. nDCG IDCG=0 occurs only when expected is empty (→ `None`); a non-empty-expected no-hit is `0.0` (DCG=0, IDCG>0).                                                                                                            | In `retrieval_metrics.py`: `None` only when `expected_doc_ids` empty; `0.0` for non-empty-expected/no-hit. Document in the docstring. (Should-tier; absence does not fail.) |
| C3  | LOW      | 1 Duplication        | FR-5 vs hybrid_retriever.deduplicate_to_docs | The dedup invariant (`chunk_id.split("::",1)[0]`, first-wins) already exists in `retrieval/hybrid_retriever.py:35` (`deduplicate_to_docs`). FR-5 re-implements it in `eval/`. This is intentional (eval operates on bare ranked doc-id lists, not `(chunk_id, score)` tuples from the retriever; importing across layers would couple eval to retrieval internals). | Keep the eval-layer dedup independent; add a one-line comment noting the invariant is shared with `hybrid_retriever` and SSoT'd in the KB. No code reuse forced.            |

Pass-by-pass: **(1) Duplication** — only C3, intentional and justified. **(2) Ambiguity**
— no unresolved TODO/???/placeholder; "roughly 600–700 docs" (AC-3) is a non-binding
sanity range, the binding criterion is "all gold IDs + per-source distractor counts" (a
measurable check). **(3) Underspecification** — C1 (config constant name); every other
requirement has an object + a falsifiable AC. **(4) Constitution alignment** — no
speculative scope (Should-tier items are explicitly optional and named); the one new seam
is no new seam at all (reuses Phase 3's `Generator`/`Retriever`); `vcrpy` is justified by
a named change (FR-8 e2e assertion + the cassette ADR), not "in case"; no stranger-test
leak (all design content is about the system); `make test` offline invariant upheld
(NFR-3). **No CRITICAL.** **(5) Coverage** — every FR-1..11, NFR-1..8, AC-1..16 maps to
≥1 manifest entry (see the "Covers" column; AC-2 is a recorded note, AC-14/15 are
Should-tier). No orphan manifest entries. **(6) Inconsistency** — C2 (nDCG no-hit
wording); terminology otherwise consistent (sentinel, threshold, dedup invariant, "gold
IDs", "distractors per source" used identically in DEFINE and DESIGN).

## Risks & Trade-offs

- **Cassette staleness (R1).** A recorded cassette can drift from live model behavior if
  the model or prompt changes. Mitigation: the cassette pins the FR-8 _abstention_
  outcome (a structural assertion — answer == sentinel, sources == []), not free-text;
  re-record is a one-line `--record-mode=once` run. Documented in ADR-0006. Accepted.
- **nDCG no-hit semantics (R2).** The None-vs-0.0 split (C2) is a genuine design call,
  not a bug — empty-expected is `None` (N/A), non-empty-expected-no-hit is `0.0` (a real
  zero). This is worth one sentence in the `retrieval_metrics.py` docstring and is
  consistent with NFR-2. Should-tier, so low-stakes.
- **Gold-aware corpus size on the 8 GB Air (R3).** `distractors_per_source = 50` × 9
  sources + gold ≈ 600–700 docs encodes comfortably (NFR-1 streaming preserved). The flag
  lets the final portfolio run scale up on a rented box. No design change needed.
- **load_retriever sidecar/column trust (R4).** FR-9 trusts that the sidecar chunk-ID
  order and the LanceDB `source_type` column were written consistently by `build_index`
  (they are — `pipeline.py:95–109` writes both from the same ordered `chunks` list). The
  regression test guards against re-introducing a corpus re-read; a separate guard that
  the maps round-trip the same `chunk_to_doc` is a reasonable extra assertion.

**ADRs warranted:** ADR-0005 (provider matrix, FR-10 — required) and ADR-0006
(cassette/replay — this design decision). The ADR-0002 update (operating point) is
Should-tier.

## Next Step

→ `/implement sprint-2/phase-5-retrieval-eval` — no gaps block implementation. Sequence
the commits exactly as in Implementation Phases (FR-9 fix FIRST). The `/update-kb
rag-eval` knowledge-loop item runs AFTER the phase.
