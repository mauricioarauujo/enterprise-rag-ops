# SPRINT 2: Eval Harness

**Sprint:** sprint-2 | **Date:** 2026-05-22 | **Status:** closed (2026-05-26)

## Goal

Turn the Sprint 1 substrate into a rigorously **evaluated** system: a reproducible
eval harness that scores answers at per-fact granularity (LLM-as-judge over
`answer_facts`), measures retrieval quality (recall@k / precision@k / MRR over
`expected_doc_ids`), and scores abstention on out-of-domain questions. The harness
runs a multi-model comparison and emits a report with per-category breakdown, cost,
and latency — the project's primary signal. "Passes smoke" is not "correct"; this
sprint makes that gap measurable.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                                                                                                                                                                                   | Slug                        |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| 4     | Per-fact LLM-as-judge over `answer_facts` (recall/precision + faithfulness of citations); write **ADR-0001** (eval framework)                                                                                                                                                                                                            | `phase-4-perfact-judge`     |
| 5     | Gold-aware corpus sampling (build the corpus from `expected_doc_ids` + distractors) as the opening task; retrieval metrics (recall@k, precision@k, MRR over `expected_doc_ids`); abstention scoring on `info_not_found`; write **ADR-0005** (LLM provider/model matrix) and calibrate the `0.45` abstention threshold (updates ADR-0002) | `phase-5-retrieval-eval`    |
| 6     | Multi-model runner (≥2 families) + cost/latency tracking; HTML+MD report with per-category breakdown; first **published baseline numbers**                                                                                                                                                                                               | `phase-6-multimodel-report` |

Planned breakdown, not a contract — each phase refines on `/brainstorm`.

## Sprint-Wide Knowledge Plan

Two kinds of pre-work, keyed to each phase's decision point — research lands _before_
a phase's brainstorm/ADR; KB work lands _after_ its ADR. Tech-agnostic knowledge can
be KB'd whenever it stabilizes.

| Knowledge area                                                                                                                     | Kind          | Action                                                                                      | Timing                                                                                         |
| ---------------------------------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Eval framework design space (RAGAs vs DeepEval vs custom per-fact judge) — per-fact granularity, traceability, 500-q cost, lock-in | research      | Context7/Exa on RAGAs + DeepEval; `--deep-research` if the trade-off stays unclear          | **Before Phase 4 brainstorm + ADR-0001** — do not pre-build a survey KB of the undecided space |
| Eval harness (chosen approach): per-fact judge prompt design, faithfulness scoring, abstention/conflict scoring                    | KB            | `/new-kb rag-eval`                                                                          | **After ADR-0001** (during/after Phase 4) — documents the decided design                       |
| Retrieval eval metrics (recall@k / precision@k / MRR / nDCG over `expected_doc_ids`)                                               | tech-agnostic | none — already covered by `rag-retrieval` KB (`concepts/retrieval-eval-metrics`, conf 0.90) | Coverage holds; `/update-kb rag-retrieval` only if implementation reveals a gap                |
| Abstention threshold (`0.45`) calibration — precision/recall trade-off on `info_not_found`                                         | tech-agnostic | fold method into `rag-eval` KB; record the calibrated value by **updating ADR-0002**        | After the Phase 5 sweep                                                                        |
| LLM provider/model matrix + judge independence (resolve same-family judge/generator from ADR-0003)                                 | research      | Context7/Exa on current OpenAI + Anthropic model specs, pricing, structured-output support  | **Before Phase 5/6 brainstorm + ADR-0005**                                                     |

**Carried-forward KB debt (Sprint 1 close, not yet run).** Orthogonal to Sprint 2's
deliverables but cheap to pay while this sprint reads the retrieval/generation
contracts: `/new-kb rag-generation` (Phase 3 lessons — `Generator` seam + `StubGenerator`
CI pattern, structured-output attribution, ranked-chunk assembly, two-tier smoke gate)
and `/update-kb rag-retrieval` (the `VectorStore` 2→3-method widening + new
`Retriever.retrieve_chunks`). Do opportunistically; not on the Sprint 2 critical path.

## Success Criteria

- **End-to-end eval run:** `make eval-baseline` runs the full 500 questions for one
  model and emits a report with a per-category breakdown across all 10 question
  categories (basic … high_level).
- **Per-fact granularity:** the judge produces per-fact recall/precision against
  `answer_facts`, plus a faithfulness verdict on each cited source (does the cited doc
  support the claim — catches the anchor "Paris" spurious-citation case).
- **Retrieval metrics:** recall@k, precision@k, and MRR computed over `expected_doc_ids`,
  reported per category.
- **Abstention scoring:** `info_not_found` questions are scored for correct abstention;
  the report surfaces false-negative abstentions (the substrate answering when it should
  decline).
- **Multi-model, cross-family comparison:** ≥2 models from **different families**
  published in `results/baseline.{html,md}`, with cost and latency tracked per question
  and per model.
- **Decisions captured at decision time:** ADR-0001 (eval framework) and ADR-0005 (LLM
  provider/model matrix, resolving the same-family judge/generator flag) written and
  accepted; ADR-0002 updated with the calibrated abstention threshold.
- **Cost discipline:** a full eval cycle stays under the per-cycle cost bar; dev runs are
  capped to a question subset, full 500 only at milestones.

## Risks

- **Corpus coverage gates credible numbers (highest risk).** The Sprint 1 dev subset
  (100 docs/source = 900 docs) contains the gold docs for only ~3 of 500 questions, so a
  naive 500-q eval over it would report near-zero retrieval recall — a data-coverage
  artifact, not a retrieval failure. The harness needs a corpus that actually contains
  the `expected_doc_ids` (targeted ingest of gold docs + distractors) or an eval mode
  that accounts for out-of-corpus gold. **Resolved (2026-05-23):** gold-aware corpus
  sampling as a Phase 5 opening task — build the corpus from the union of the answerable
  questions' `expected_doc_ids` + distractors, so low recall is real signal, not
  artifact. Phase 4's judge is unaffected (robust to coverage). Subset numbers stay
  relative-only (not directly comparable to the full-corpus leaderboard — final numbers
  need the full corpus on a larger machine).
- **Eval cost over budget.** 500 questions × multiple models × per-fact judge calls
  multiplies fast. Mitigate: `gpt-5-nano`-class judge, cap to ~100 questions during dev,
  run the full 500 only at milestones; track cost per cycle and fail loud on overrun.
- **Same-family judge bias.** If one family both generates and judges, lenient
  self-grading is likely (anchor Case 1's spurious citation could pass). ADR-0005 must
  mandate a different judge family; bake the independence into the harness config.
- **Judge determinism / reproducibility.** `gpt-5-nano` rejects `temperature=0`, so judge
  stability rests on prompt design and possibly multi-sample aggregation. Eval tests must
  not hit the live API ad hoc — adopt the cassette/replay pattern (the TBD Sprint 2 ADR
  in AGENTS.md conventions) so eval results are reproducible offline.
- **Substrate perf on local hardware.** BGE-M3 encode (~22 min, swaps an 8 GB Air) and
  `load_retriever` re-chunking the corpus per call make repeated 500-q runs painful.
  Mitigate: pay the cheap `load_retriever` fix (build maps from the sidecar + LanceDB,
  no re-chunk), shrink `DOCS_PER_SOURCE` during dev, and run final numbers on a rented box.
- **Eval-framework lock-in (ADR-0001).** Picking RAGAs/DeepEval could constrain per-fact
  granularity or traceability; a thin custom judge avoids lock-in but costs build time.
  Decide on observed retrieval/generation failure modes, not on framework popularity.

---

## Retrospective

**Outcome:** all three planned phases shipped with ✅ READY reviews and merged to `main`
(Phase 4 → PR #6, Phase 5 → PR #8, Phase 6 → PR #10). Every Success Criterion is met,
including the published cross-family baseline.

### Success criteria — final status

| Criterion                                                               | Status                                                                              |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| End-to-end `make eval-baseline`, per-category report (10 categories)    | ✅ shipped (Phase 6)                                                                |
| Per-fact recall/precision + per-citation faithfulness                   | ✅ (Phase 4 judge; anchor "Paris" spurious-citation caught offline)                 |
| Retrieval recall@k / precision@k / MRR (+ nDCG) over `expected_doc_ids` | ✅ (Phase 5)                                                                        |
| Abstention scoring on `info_not_found`, false-negative surfacing        | ✅ (Phase 5; sentinel enforced at the generator after the layer-defect fix)         |
| Multi-model cross-family comparison + cost/latency                      | ✅ `results/baseline.{html,md}`: gpt-5-nano vs Haiku 4.5, ~$2.59, 999 records       |
| ADRs at decision time (0001, 0005; 0002 threshold; same-family flag)    | ✅ + ADR-0006 (cassette) and ADR-0007 (eval-record schema) shipped                  |
| Cost discipline (dev subset, full 500 at milestones)                    | ✅ capped dev sweep caught the EOL-model + weak-gold-guard bugs before the paid run |

### What worked

- **Per-phase `/review` caught substantive defects, not just nits.** Phase 5's review
  found a _hand-fabricated_ cassette that was masking a real architectural defect — FR-8
  e2e abstention targeted the wrong layer (the gate rarely fires for `info_not_found`, so
  the **generator** is the operative abstention layer). Recording a genuine cassette forced
  the fix: one enforced sentinel contract at both abstention points. The "no mocked LLM in
  eval" rule (ADR-0006) earned its keep.
- **Run-the-paid-baseline-for-real surfaced six findings the offline suite could not** —
  EOL Anthropic model (404), a gold-aware index guard too weak to catch 0/20 gold docs,
  BGE-M3/MPS thread-unsafety under `--concurrency`, missing per-call timeout, tier-1 rate
  limits, and a dead `.gitignore` negation. The capped dev sweep _before_ the full run
  caught the two cheapest-to-fix (9, 10) for pennies — now the standard pre-publish step.
- **Knowledge loop kept pace with the work.** `rag-eval` grew to 15 concepts/patterns
  across the sprint (PRs #7, #9) — capture happened per-phase, so close had nothing to
  back-fill.

### What slipped / scope changes vs the SPRINT.md plan

- **ADR count grew from 2 to 4.** Plan named ADR-0001 + ADR-0005 (and an ADR-0002 update).
  Reality also produced **ADR-0006** (cassette/replay — the "TBD Sprint 2 ADR" the
  conventions had flagged) and **ADR-0007** (eval-record schema, Phase 6). Both were latent
  in the plan's risk section; numbering them was the correct call, not creep.
- **ADR-0003 picked up a behavior change.** The abstention-layer fix hardened the Phase-3
  generator prompt (exact sentinel, no parametric answers) — recorded as the Sprint-2 update
  note in ADR-0003. A cross-phase ripple the original plan didn't anticipate.
- **Baseline is subset/gold-aware, not full-corpus.** As the top risk predicted, credible
  numbers required gold-aware corpus sampling (Phase 5 opening task); the published numbers
  are relative on the gold-aware corpus, not a full-500-over-full-corpus leaderboard — that
  awaits a larger machine. Recall@10 landed 64–100% on the gold-aware build (vs the ~0% a
  naive run would have reported).

## Sprint Close

**Verdict:** ✅ closed — 3/3 phases shipped, all Success Criteria met, knowledge loop
current.

### Knowledge capture — already executed (nothing outstanding)

Every per-phase Knowledge Capture suggestion landed during the sprint. `rag-eval` now holds:
per-fact-judge-call, per-doc-faithfulness, none-empty-denominator, schema-as-ssot,
judge-determinism, offline-ci-judge, retrieval-metric-aggregation, abstention-scoring,
cassette-replay-eval (incl. response-header scrubbing), eval-record-schema, cost-accounting,
stats-capture-seam, multi-model-runner, eval-report-render, concurrent-eval-sweep.

### KB staleness — one open item

- **`rag-generation` KB is an empty scaffold** (`concepts/` + `patterns/` dirs, no files,
  not registered in `_index.yaml`). This is Sprint 1's carried-forward debt, now compounded:
  Sprint 2 changed generation behavior (abstention is a single canonical sentinel enforced
  at both the retrieval gate and the generator prompt — ADR-0003 update). Recommend
  `/new-kb rag-generation` seeded from the Phase 3 lessons **plus** the Sprint-2 abstention
  enforcement. Out of Sprint 2's critical path but the freshest it will ever be.
- `rag-retrieval` is **not** stale (Phase 5 confirmed `retrieval-eval-metrics` consumed
  verbatim). Optional one-liner: LanceDB no-vector `.search().select().to_arrow()` returns
  all rows (the default-10 limit applies only to vector/FTS search) — verified on 0.30.2.

### ADRs — all recorded, none missing

0001 (eval framework), 0005 (provider matrix), 0006 (cassette/replay), 0007 (eval-record
schema) written and accepted this sprint; 0002 updated with the calibrated 0.45 abstention
threshold; 0003 updated with the enforced-sentinel note; 0004's stranger-test leak scrubbed.

### Doc follow-up (private, gitignored)

- `docs/planning/roadmap.md` ADR ledger is stale: it omits the shipped **ADR-0007
  (eval-record schema)** and still pencils failure-mode-taxonomy at 0007 — that slot is
  taken, so taxonomy moves to **0008** (stretch 0009 caching → 0010). One-line fix.
- Phase 6 left a code follow-up for Sprint 3: **strengthen the FR-10 gold-aware index guard**
  (it checks dir existence, not gold-aware-ness — a plain index with 0/20 gold docs passed
  and yielded meaningless scores). A marker file or a sampled-gold-docs assertion.
