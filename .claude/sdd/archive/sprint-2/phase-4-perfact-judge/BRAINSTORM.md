# BRAINSTORM: phase-4-perfact-judge — Per-Fact LLM-as-Judge

**Sprint/Phase:** sprint-2/phase-4-perfact-judge | **Date:** 2026-05-22

## Problem Statement

Sprint 1 shipped a substrate (`rag-ask`) that returns `AnswerWithSources(answer, sources)`
against the EnterpriseRAG-Bench. The system can now produce answers — but "passes smoke"
is not "correct." Phase 4 makes that gap measurable: an LLM-as-judge that scores a
generated answer against its question's `answer_facts` (per-fact recall and precision)
and verifies that each cited `doc_id` actually supports the claimed fact (citation
faithfulness), producing machine-readable verdicts the downstream runner (Phase 6) can
aggregate and report.

---

## Research & KB Scan

| Topic                                      | KB file / domain                                                                   | Coverage                                                                                                                                                                  |
| ------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RAGAs vs DeepEval vs custom harness        | `.claude/kb/_research/inbox/rag-eval-2026-05-26.md` (pillar 3)                     | Sufficient — 3-way comparison with cost, CI, lock-in, and corpus-coverage analysis                                                                                        |
| Per-fact recall / precision mechanics      | `rag-retrieval/concepts/retrieval-eval-metrics.md` (conf 0.90)                     | Sufficient for metric definitions; the judge prompt design is new                                                                                                         |
| `answer_facts` / `expected_doc_ids` schema | `docs/dataset.md`                                                                  | Sufficient — schema confirmed; no questions-loader exists yet                                                                                                             |
| Generator seam and `AnswerWithSources`     | `generation/schema.py`, `generation/interfaces.py`, `generation/stub_generator.py` | Sufficient — the eval input contract is the exact `AnswerWithSources` Pydantic model                                                                                      |
| `Chunk` schema (`doc_id`, `text`)          | `retrieval/schema.py`                                                              | Sufficient — the faithfulness judge sees per-doc text via `doc_id`                                                                                                        |
| Judge prompt design patterns               | Not in KB                                                                          | Thin — the research inbox covers the mechanics; a `rag-eval` KB domain is planned **after** ADR-0001 (per SPRINT.md Sprint-Wide Knowledge Plan); no pre-build needed here |
| vcrpy / cassette pattern for LLM CI        | Not in KB                                                                          | Thin — defer to the ADR that decides the cassette replay strategy; a reference in the research supports the pattern                                                       |

**Conclusion:** No `/new-kb` or additional `--deep-research` is needed before `/define`.
The pillar-3 research file is the live input for ADR-0001. A `rag-eval` KB domain will
be built _after_ ADR-0001 closes (per SPRINT.md).

---

## Approaches Considered

### Decision 1 — Build vs. Adopt (the ADR-0001 question)

All three candidates must be assessed because ADR-0001 requires a documented comparison.

| Approach                                                                                                                                                                                                        | Per-fact recall/precision                                                                                                                                                                      | Citation faithfulness (doc-level)                                                                                                                                                                 | Seam / CI story                                                                                                                                                                               | Cost (500 q)                                                                                                                           | Lock-in                                                                                                                                                                                             |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. Custom thin judge** — a `Judge` Protocol + `OpenAIJudge` + `StubJudge`; single structured-output prompt per question injecting `answer_facts` as a checklist and each cited doc's text as a separate block | Direct: facts are the checklist items; verdict is per-fact {present\|absent\|contradicted}                                                                                                     | Native: prompt isolates claim→`doc_id` mapping; no blob context merging                                                                                                                           | `Judge` Protocol mirrors `Generator`; `StubJudge` preserves offline CI; vcrpy cassette for live-judge tests                                                                                   | 1 LLM call/q ≈ $2.63/run (500 q)                                                                                                       | None — standard `openai` SDK + Pydantic                                                                                                                                                             |
| **B. DeepEval adoption** — `FaithfulnessMetric` + `AnswerRelevancyMetric`; custom `G-Eval` for per-fact with supplied facts                                                                                     | Requires overriding claim extraction via G-Eval; no native "inject supplied facts" path; under-scores golden contexts (mean 0.46 in benchmarks vs. 0.82–0.91 for other tools)                  | Global blob context evaluation — a model can cite the wrong `doc_id` and still pass if the fact appears anywhere in the context window; no native per-`doc_id` mapping without template overrides | Local JSON cache (`--use-cache`) is not a cassette; a changed prompt invalidates the cache and fires live calls; Confident AI SaaS lock-in for visual reporting                               | 3 LLM calls/q ≈ $7.88/run; 3× multiplier applies even with supplied facts because DeepEval still runs its internal extraction pipeline | Moderate — tied to Confident AI platform for full feature set; prompt templates tightly optimized for OpenAI                                                                                        |
| **C. RAGAs v0.4** — `FactualCorrectness` + `Faithfulness` metrics via the Collections API                                                                                                                       | Forces LLM auto-decomposition of both the generated answer AND the reference — wasted tokens and semantic drift when `answer_facts` is already the ground truth; no "inject static facts" path | Global context blob — same `doc_id` gap as DeepEval; "citation accuracy" metric requires custom wrapper for structured metadata                                                                   | No native offline replay or cassette; same 3-call multiplier; v0.3→v0.4 API broke backward compat (deprecated `evaluate()`, changed return types, moved metric imports); high maintenance tax | 3 LLM calls/q ≈ $7.88/run                                                                                                              | High — v0.4 API churn is documented; future minor versions may repeat; abstention scoring penalizes correct "I don't know" responses with score=0 (hostile to `info_not_found` category in Phase 5) |

**Anchor case check.** The spurious-citation case (`rag-ask "capital of France?"` returned
a citation to an unrelated google_drive doc): Approach A catches it — the prompt asks
"does the text of doc X support the claim 'The capital of France is Paris'?" against
the actual doc text, which answers No → faithfulness=unsupported. Approach B and C
evaluate faithfulness against the merged context; if any retrieved doc contains
"Paris" (plausible in a 900-doc enterprise corpus), both would mark the claim as
supported regardless of which `doc_id` was cited. The anchor case is a direct
discriminator in favor of Approach A.

---

### Decision 2 — Verdict schema granularity

How the judge represents its per-question output.

| Approach                                                                                                                                                                                               | Pros                                                                                                                                                                             | Cons                                                                                                                                                         | Effort |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. Per-fact flat list `{fact, verdict: present\|absent\|contradicted}` + per-citation flat list `{doc_id, verdict: supported\|unsupported}` — two Pydantic lists, aggregated in Python post-processing | Clean separation; aggregation logic is pure Python (no LLM tokens); maps directly to recall = len(present)/len(facts), precision = len(present)/(len(present)+len(contradicted)) | Slightly more complex prompt (two output sections)                                                                                                           | S      |
| B. Single compound verdict per fact with an optional `supporting_doc_id` field                                                                                                                         | One object instead of two lists                                                                                                                                                  | Mixes the two scoring dimensions; a fact can be present-in-answer but unsupported-by-cited-doc — both properties need independent verdicts                   | S      |
| C. Aggregated scores only (no per-fact detail) — judge emits recall_score and precision_score floats directly                                                                                          | Simple output                                                                                                                                                                    | Loses per-fact traceability; impossible to inspect which facts are missing or which citations are dishonest; Phase 6 report would have no per-fact breakdown | S      |

**Leaning: A.** Per-fact and per-citation lists keep the two scoring dimensions independent
and preserve the traceability the Phase 6 report needs, while keeping aggregation in
pure Python (deterministic, cheap, testable).

---

### Decision 3 — Judge seam (Protocol or plain class)

Whether a `Judge` Protocol is justified by the CLAUDE.md seam rule ("justified by a
named, likely future swap — an ADR that anticipates it").

The named future swap is ADR-0005 (LLM provider/model matrix): the judge family must be
different from the generator family (same-family bias carried forward from ADR-0003;
explicit in SPRINT.md risks). ADR-0005 will swap the judge model — the swap is named,
likely, and in-sprint (Phase 5). A `Judge` Protocol is therefore justified on exactly
the same grounds as the `Generator` Protocol (ADR-0003 §1). The `StubJudge`
(deterministic, offline) preserves `make test` on the same pattern as `StubGenerator`
and `StubEmbedder`.

---

## Recommended Approach

**Approach A (custom thin judge)** on all three decisions.

The `answer_facts` checklist is the key differentiator. Every other consideration —
cost, CI reproducibility, doc-level faithfulness, ADR-0001 material — also favors
Approach A, and the research already runs the three-way comparison that makes
ADR-0001's alternative analysis complete. DeepEval remains the honest "adopt" runner-up
(more stable than RAGAs v0.4, credible CI story via its cache) but loses on the
`doc_id` faithfulness gap — the exact gap the anchor case exposes. RAGAs is weakened by
the API-churn risk and by penalizing correct abstention with a score of 0, which
pre-poisons the Phase 5 `info_not_found` category before that phase even starts.

The custom approach is also the smallest thing to build at Phase 4 scope: one prompt,
one Pydantic verdict schema, one aggregation function, one Protocol + stub. The
parallel execution, cost tracker, and report live in Phases 5–6.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                                                                                                  |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | `Judge` Protocol in `eval/judge/interfaces.py` — single method `judge(question, answer_with_sources, answer_facts, retrieved_docs) -> JudgeVerdict`                                                                                                                   |
| Must     | `JudgeVerdict` Pydantic model: `per_fact: list[FactVerdict]`, `per_citation: list[CitationVerdict]`, plus aggregated `fact_recall`, `fact_precision`, `faithfulness_ratio` floats (derived in Python, not via LLM)                                                    |
| Must     | `FactVerdict` Pydantic model: `fact: str`, `verdict: Literal["present", "absent", "contradicted"]`                                                                                                                                                                    |
| Must     | `CitationVerdict` Pydantic model: `doc_id: str`, `verdict: Literal["supported", "unsupported"]`                                                                                                                                                                       |
| Must     | `OpenAIJudge` implementing `Judge` — single structured-output call; injects `answer_facts` as a checklist and each cited doc's text as a named block; default model configurable via `RAG_JUDGE_MODEL` env var                                                        |
| Must     | `StubJudge` — deterministic offline drop-in for `make test` (mirrors `StubGenerator`); all facts "present", all citations "supported"                                                                                                                                 |
| Must     | Thin `questions` loader in `eval/` — streams the `questions` config from the dataset at the pinned SHA (same `DATASET_REVISION` constant from ingest), yields typed `Question` objects with `question_id`, `question`, `answer_facts`, `expected_doc_ids`, `category` |
| Must     | Unit tests: `StubJudge` contract, aggregation logic (pure Python — no API call), `Question` loader schema                                                                                                                                                             |
| Must     | ADR-0001 written: three-way RAGAs / DeepEval / custom comparison, decision, consequences                                                                                                                                                                              |
| Should   | vcrpy cassette fixture for `OpenAIJudge` — records one real call, replays in `make test`; this is the Sprint 2 cassette pattern referenced in CLAUDE.md conventions                                                                                                   |
| Should   | Keep the judge model configurable via `RAG_JUDGE_MODEL` and avoid hard-wiring same-family assumptions, so ADR-0005 can bind a cross-family judge with no Phase-4 refactor (the cross-family default + `ClaudeJudge` land in Phase 5 — see Q2 decision)                |
| Should   | `make test` stays offline and free after Phase 4 lands                                                                                                                                                                                                                |
| Could    | `judge-one` CLI smoke target — runs the judge on a single hand-crafted question + answer pair; useful for prompt iteration without a full pipeline run                                                                                                                |
| Could    | Per-category aggregation utility (group verdicts by `question.category`) — useful at Phase 6 report time; could be scaffolded now at low cost                                                                                                                         |
| Won't    | Retrieval metrics (recall@k, precision@k, MRR over `expected_doc_ids`) — Phase 5                                                                                                                                                                                      |
| Won't    | Abstention scoring on `info_not_found` category — Phase 5                                                                                                                                                                                                             |
| Won't    | ADR-0005 (LLM provider/model matrix) — Phase 5                                                                                                                                                                                                                        |
| Won't    | Multi-model runner (running the judge across ≥2 generator families) — Phase 6                                                                                                                                                                                         |
| Won't    | HTML/MD report generation — Phase 6                                                                                                                                                                                                                                   |
| Won't    | Parallel/concurrent judge execution — Phase 5/6                                                                                                                                                                                                                       |
| Won't    | Cost and latency tracking per question — Phase 6                                                                                                                                                                                                                      |
| Won't    | Gold-corpus rebuild (targeted ingest of `expected_doc_ids`) — a corpus-coverage concern; relevant to Phase 5 retrieval metrics, not to per-fact answer scoring in Phase 4                                                                                             |
| Won't    | Conflict detection between retrieved documents (contradicting sources) — out of current scope; a future judge extension                                                                                                                                               |
| Won't    | Caching or memoization of judge calls beyond the cassette pattern                                                                                                                                                                                                     |

---

## Open Questions

1. **Judge determinism strategy.** `gpt-5-nano-2025-08-07` (the generator default)
   rejects `temperature=0`. If the judge uses the same model family, the same
   constraint applies. Two options: (a) rely on structured-output constraints to
   force deterministic discrete verdicts (the output vocabulary is small: three
   possible values per fact, two per citation — leaving little room for drift), or
   (b) run N=3 parallel judge calls and take majority vote (adds cost and latency).
   Which strategy applies for Phase 4, and does it depend on the judge model family
   chosen? This needs a decision in `/define` because it affects the `Judge.judge()`
   signature (synchronous single-call vs. multi-call with aggregation).

   **Decided (2026-05-23):** Option (a). Determinism rests on `strict: true`
   structured output + the closed, discrete verdict vocabulary — the `Literal`
   enums are enforced at decode time, so the judge cannot emit an out-of-vocabulary
   verdict. No majority-vote-over-N in Phase 4: `Judge.judge()` stays a synchronous
   single call (one LLM call/question). Majority-vote is deferred as an escalation
   only if observed drift on the anchor cases proves the vocabulary insufficient.

2. **Judge model family (ADR-0005 dependency).** ADR-0005 (Phase 5) will decide the
   full provider matrix; Phase 4 must not hard-wire the judge to the generator's
   family (same-family bias risk documented in ADR-0003 and SPRINT.md). What is the
   Phase 4 default judge model — a different OpenAI model tier, an Anthropic model,
   or left entirely configurable via `RAG_JUDGE_MODEL` with no default? The answer
   determines whether Phase 4 needs a second provider SDK dependency and whether
   a `ClaudeJudge` must be built now or deferred to Phase 5/6.

   **Decided (2026-05-23):** Mechanism — `Judge` Protocol + native-SDK classes
   (`OpenAIJudge` now, `ClaudeJudge` later), mirroring `Generator`. **LangChain and
   litellm were considered and rejected:** the Protocol seam already makes call
   sites provider-agnostic (swap = one new class + one wiring line), so a wrapper
   would add a heavy, churn-prone dependency to solve a problem the seam already
   solves — and structured output (`strict: true`) is provider-specific enough
   (OpenAI `json_schema`/`strict` vs. Anthropic tool-use `input_schema`) that a
   unifying abstraction leaks exactly where the judge depends on it most. Phase 4
   ships `OpenAIJudge` only (no second provider SDK), with the model configurable
   via `RAG_JUDGE_MODEL`. Cross-family judge independence — `ClaudeJudge` and
   binding the judge to a different family than the generator — is deferred to
   ADR-0005 / Phase 5; Phase 4 must not hard-wire same-family assumptions that
   would block it. The LangChain/litellm rejection rationale belongs in
   ADR-0001 (or ADR-0005).

   **Update (2026-05-23):** the provider matrix will likely include a local /
   open-weight model via **Ollama**, alongside OpenAI and Anthropic (three
   providers). This _reinforces_ the Protocol-seam choice rather than reopening
   it: each provider stays a thin `Judge` / `Generator` class, and Ollama exposes
   an OpenAI-compatible endpoint, so an Ollama-backed class can reuse the `openai`
   SDK with a different `base_url` — nearly free to add, no new SDK. Caveat for
   ADR-0005: open-weight models are weaker at the judge task (low human-agreement
   as judges) and at strict-schema / faithfulness, so Ollama is a stronger fit as
   a _generator under test_ (zero-cost, offline, fully reproducible) than as the
   _judge_. ADR-0005 assigns the judge-vs-generator role per provider. (Three
   providers nudges litellm slightly, but Ollama's OpenAI-compatible endpoint keeps
   the native-SDK path cheap — the Protocol decision holds.)

3. **Per-fact ↔ citation mapping granularity.** The verdict schema (Approach A above)
   scores each cited `doc_id` independently and each fact independently. But a
   stronger faithfulness signal would map each _asserted fact_ to the _specific cited
   doc_ that should support it. This requires the judge to emit, per fact, both a
   verdict AND the `doc_id` it evaluated against — increasing prompt complexity
   and output token count. Is that granularity required for Phase 4, or is the
   two-list flat schema sufficient for the anchor case and Phase 6 report?

   **Decided (2026-05-23):** Option A — the flat two-list schema. It already
   catches the anchor case (the spurious citation falls in `per_citation` →
   `unsupported`), and the per-fact↔doc mapping is a richer _diagnostic_ signal
   whose payoff is in the Phase 6 report and the Sprint 3 failure taxonomy, not in
   the Phase 4 judge. To avoid rework, `FactVerdict` is designed so that adding an
   optional `supporting_doc_id` field later is an **additive, non-breaking**
   extension. Option B (per-fact→doc mapping) is recorded as a future improvement
   in the project backlog.

4. **Corpus-coverage effect on Phase 4.** The dev subset (100 docs/source) contains
   gold documents for only ~3 of 500 questions. Per-fact _answer_ scoring
   (`answer_facts` vs. `AnswerWithSources.answer`) works regardless of corpus
   coverage — the judge scores what was generated, not what could have been
   retrieved. Faithfulness scoring judges whether cited doc text supports the
   claim, which also works regardless of corpus (cited docs are whatever the
   substrate retrieved). Both Phase 4 judge dimensions are therefore robust to
   the coverage gap, but the _numbers_ will reflect corpus-limited retrieval quality
   (many abstentions, low recall). `/define` should state this explicitly so the
   Phase 4 result is not misread as a judge failure. Is a note in the eval output
   (e.g., a `corpus_coverage_warning` field) needed, or is this documented
   sufficiently in the phase's acceptance criteria?

   **Decided (2026-05-23):** For Phase 4, document the caveat in the acceptance
   criteria — no code, the judge is robust to coverage and can be validated on
   hand-crafted cases + the existing subset. The real fix is **gold-aware corpus
   sampling** as a Phase 5 opening task: build the corpus from the union of the
   answerable questions' `expected_doc_ids` + distractor docs, so low recall
   becomes real signal rather than a coverage artifact. That makes a structured
   `corpus_coverage_warning` field unnecessary — legitimate abstention comes
   cleanly from the `info_not_found` category, not from accidentally-missing gold
   docs. (Include _all_ answerable gold; do not drop gold to manufacture
   abstentions — that would be indistinguishable from a real retrieval miss.)

5. **Questions loader scope.** Phase 4 needs a `Question` loader to feed the judge.
   The loader must stream the `questions` config at the pinned SHA (same
   `DATASET_REVISION` as ingest). The open question is scope: (a) a thin typed
   loader that yields `Question` dataclasses and stops there (Phase 4 minimum), or
   (b) a loader that also filters by `category` and by `question_id` subset, which
   Phase 5 and 6 will need for per-category metrics and dev-run subsets. Building
   (b) now at low extra cost avoids a re-open in Phase 5. Should the loader be
   in `eval/` (eval-only concern) or in `src/enterprise_rag_ops/` (reusable
   across CLI smoke targets)?

   **Decided (2026-05-23):** Option (a) — a thin, typed `Question` loader in
   `eval/`, streaming the `questions` config at the pinned `DATASET_REVISION`
   (imported from `enterprise_rag_ops.ingest.config` to keep the SHA a single
   SSoT). Category and `question_id` filtering are **not** loader features: with
   only 500 questions the loader yields all typed `Question` objects and callers
   filter with a list comprehension (`[q for q in load() if q.category == ...]`).
   An optional `limit` / `question_ids` arg for dev iteration is the only
   subsetting worth considering. Mechanic for `/define` to confirm: whether `eval/`
   is an installable top-level tree (per the CLAUDE.md architecture map) or a
   `src/enterprise_rag_ops/eval/` submodule — does not change the "eval concern"
   placement, only the import mechanics.

---

## Next Step

→ `/define sprint-2/phase-4-perfact-judge`
