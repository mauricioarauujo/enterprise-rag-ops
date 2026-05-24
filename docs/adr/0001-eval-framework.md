# ADR-0001: Eval Framework — Custom Thin Per-Fact Judge

**Status:** accepted
**Date:** 2026-05-23

## Context

Sprint 1 ships the substrate: hybrid retrieval (ADR-0002) and a generation layer
(ADR-0003) that emits `AnswerWithSources` (`answer: str`, `sources: list[str]`). But
nothing scores that output. "Passes the smoke gate" means the pipeline is wired and
abstention does not crash — it does **not** mean the answer is correct or that its
citations are honest. The motivating failure is concrete: an answer can assert "the
capital of France is Paris" and cite an unrelated `google_drive` doc that never mentions
Paris. The smoke gate counts that as a cited source; a real eval must catch it.

This ADR was deferred from Sprint 1 (originally 2026-05-18) on purpose: the
eval-framework choice has no empirical signal to compare against until a retriever and a
generator exist. They now do, so Sprint 2 opens this fresh.

EnterpriseRAG-Bench supplies, per question, atomic `answer_facts` and gold
`expected_doc_ids`. Sprint 2 needs to turn those into:

- **per-fact recall/precision** — does the answer state each gold fact, omit it, or
  contradict it;
- **doc-level (per-`doc_id`) faithfulness** — does each _cited_ doc's text actually
  support the claim it was cited for (the anchor case above);
- an **offline-CI seam story** — `make test` must stay network-free and key-free, the
  invariant carried from ADR-0002/0003;
- **cost discipline** — the eventual 500-question run must stay affordable.

Constraints (NFRs): offline CI (`StubJudge`, no key); determinism via `strict: true`
structured output + a closed discrete verdict vocabulary + defensive Pydantic
re-validation; minimal scope (the seam is justified only by a named future swap, no
pre-built alternatives); schema-as-SSoT (`model_json_schema()`, no hand-maintained
parallel schema); dependency hygiene (≤1 new dev dep; no eval-framework library, no
second provider SDK, no LLM wrapper).

## Decision

A **custom thin per-fact judge**, mirroring the generation layer's proven shape rather
than adopting an eval framework:

1. **`Judge` Protocol seam.** Single synchronous method
   `judge(question, answer_with_sources, answer_facts, retrieved_docs) -> JudgeVerdict`.
   Sprint 2 ships `OpenAIJudge` (production; default model `gpt-5-nano-2025-08-07`,
   override via `RAG_JUDGE_MODEL`) and `StubJudge` (CI). The Protocol is the named swap
   surface for **ADR-0005**'s cross-family judge (a `ClaudeJudge`, or an Ollama-backed
   judge via `base_url`) — a new file plus a one-line wiring change. The contract hard-wires
   no same-family assumption.
2. **A single structured-output call per question.** `OpenAIJudge` issues one
   `chat.completions.create` with
   `response_format={"type": "json_schema", "json_schema": <schema>, "strict": true}`.
   The LLM produces only the two verdict lists; reproducibility rests on `strict` + the
   discrete `Literal` vocabulary, not on majority-vote-over-N (deferred unless the anchor
   cases show drift).
3. **Doc-level faithfulness via per-`doc_id` prompt isolation.** Each cited doc's text is
   rendered as a separately named block (`=== doc {doc_id} ===`), never a merged context
   blob. A cited doc absent from the retrieved set renders as an explicit
   `(text unavailable)` block so the judge returns `unsupported` instead of the citation
   silently vanishing. This per-doc isolation is precisely what lets the judge answer
   "does _this_ doc support the claim?" — the discriminator the anchor case exploits.
4. **Pure-Python aggregation.** `fact_recall = |present|/|facts|`,
   `fact_precision = |present|/(|present|+|contradicted|)`,
   `faithfulness_ratio = |supported|/|citations|` are computed in Python from the two
   verdict lists, **never by the LLM**, and are excluded from the LLM-facing schema. Empty
   denominators yield `None` ("not applicable"), so an abstention with no facts/citations
   aggregates to `(None, None, None)` rather than a misleading `0.0` or `1.0`.
5. **Schema as SSoT.** `JudgeVerdict` is the canonical schema. Its LLM-facing surface (a
   private `_LLMJudgeVerdict` holding only the two lists) is what feeds the `strict`
   json_schema and re-validates the response — the same `model_json_schema()` pattern
   `OpenAIGenerator` uses for `AnswerWithSources`. The closed schema (`extra="forbid"` →
   `additionalProperties: false`) lets `strict: true` reject drift server-side.

The decision is **custom**, justified by four things an off-the-shelf framework does not
give cleanly: native ingestion of the dataset's `answer_facts`; doc-level (per-`doc_id`)
faithfulness rather than scoring a merged context; first-class abstention handling (the
`None` N/A convention); and cost — one call per question, not three.

## Consequences

### What we accept

- **No eval-framework dependency.** No RAGAs, no DeepEval — `make test` adds no new
  runtime dep. `openai` and `pydantic` are already present from Sprint 1.
- **`OpenAIJudge` needs `OPENAI_API_KEY` for live runs.** CI and `make test` use
  `StubJudge` and need no key; the `openai` import lives only in `eval/openai_judge.py`,
  so the offline test path never touches the SDK at runtime (the ADR-0003 invariant,
  carried).
- **The cassette/replay test is Should-tier.** A vcrpy-recorded live judge test is
  optional this phase; its absence does not fail the phase. `StubJudge` plus a
  fake-client `OpenAIJudge` test carry the call-shape contract offline, and the anchor
  case is provable via hand-built verdicts. (Phase 4 ships **no** new dev dep on this
  basis — a vcrpy cassette cannot be recorded without a live call, so adding the dep
  unused was declined per § Engineering Behavior.)
- **Same-family judge/generator (carried from ADR-0003).** Generator and judge default to
  the same OpenAI family, which can inflate measured faithfulness. ADR-0005 is the
  resolution venue — routing one side to a different family. The `Judge` seam makes that
  a localized change.

### What changes when it changes

- **ADR-0005 (cross-family judge)** is the named swap behind the `Judge` Protocol — a new
  file implementing `judge(...)` plus one wiring line. `RAG_JUDGE_MODEL` already lets a
  run swap OpenAI model variants without a code change.
- **`JudgeVerdict` is the Phase 6 runner's input contract.** The multi-model runner and
  report consume it; any change ripples there. In particular, downstream averaging must
  treat each `None` float as N/A (exclude), not coerce it to 0.
- **`FactVerdict` is designed for an additive `supporting_doc_id`** — a later
  non-breaking field tying a fact to the doc that supports it. Not built now.

### Build-time invariants

- **Closed schema + `strict: true` + defensive re-validation.** Both verdict models carry
  `extra="forbid"`; the returned JSON is re-validated through `_LLMJudgeVerdict`, so drift
  surfaces as a typed `ValidationError`, not an opaque SDK error.
- **Aggregation is deterministic and pure** — identical verdict lists yield byte-identical
  floats; no I/O, no LLM call.
- **The `None` empty-denominator convention** is total: empty `per_fact` → `fact_recall =
None`; `|present|+|contradicted| == 0` → `fact_precision = None`; empty `per_citation` →
  `faithfulness_ratio = None`.
- **Temperature is left at the model default** — `gpt-5-nano-2025-08-07` rejects an
  explicit temperature; reproducibility is carried by `strict` + the discrete vocabulary
  (same constraint as `OpenAIGenerator`).
- **The `openai` import lives only in `eval/openai_judge.py`** — `schema`, `aggregate`,
  `interfaces`, `prompt`, `stub_judge`, and `questions` import no `openai`, preserving the
  offline-CI invariant on a clean clone.

## Alternatives Considered

| Choice            | Picked                                                                                                                        | Rejected                                                  | Why                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Eval framework    | **Custom thin judge** (`Judge` Protocol + `OpenAIJudge` + `StubJudge`; one structured-output prompt; pure-Python aggregation) | **RAGAs v0.4**; **DeepEval**                              | Both score against a merged context blob, so they miss the anchor case — a citation to the wrong `doc_id` is invisible once docs are concatenated. Neither ingests the dataset's `answer_facts` as a per-fact checklist cleanly; both add a heavy dependency and lock-in; both default to multi-call metrics (cost). Custom gives per-fact recall/precision, per-`doc_id` faithfulness, abstention handling, and 1 call/q. |
| Determinism       | `strict: true` + closed discrete vocabulary (single call)                                                                     | Majority-vote over N samples                              | N× the cost for a discrete-verdict task where `strict` + `Literal` enums already pin the output space. Multi-sample is an escalation only if the anchor cases show drift.                                                                                                                                                                                                                                                  |
| Faithfulness unit | Per-`doc_id` block (one named block per cited doc)                                                                            | Merged context blob; per-sentence NLI                     | The merged blob is exactly what hides the spurious-citation failure. Per-`doc_id` isolation is the minimal unit that catches it; per-sentence NLI is more machinery than the doc-level question needs.                                                                                                                                                                                                                     |
| Aggregate floats  | Derived in Python, excluded from the LLM schema                                                                               | Let the LLM emit the floats                               | LLM-emitted ratios are unverifiable and can disagree with their own verdict lists. Python derivation is deterministic, auditable, and keeps the floats out of `strict`-mode schema friction.                                                                                                                                                                                                                               |
| Provider seam     | `Judge` Protocol + native `openai` SDK                                                                                        | **LangChain**; **litellm**                                | The Protocol seam already makes call sites provider-agnostic; structured-output is provider-specific enough that a unifying wrapper leaks exactly where it matters most (the `strict` json_schema contract). A wrapper adds a dependency and an abstraction without buying anything the seam doesn't already give. ADR-0005 adds `ClaudeJudge` as a sibling file, not a wrapper.                                           |
| CI strategy       | `StubJudge` behind the `Judge` seam (+ fake-client test)                                                                      | Skip judge tests in CI; live cassette as the primary path | Exact precedent from ADR-0003's `StubGenerator`; exercises the contract offline with no key. The vcrpy cassette is a Should-tier add-on, not the primary coverage.                                                                                                                                                                                                                                                         |

## References

- `.claude/sdd/features/sprint-2/phase-4-perfact-judge/` — BRAINSTORM, DEFINE, DESIGN.
- ADR-0002 — retrieval architecture (`Chunk`, the `Retriever`/`VectorStore` seams the
  judge reuses).
- ADR-0003 — generation layer (`AnswerWithSources`, the judge's answer-input contract;
  the structured-output + `StubGenerator` patterns this ADR mirrors).
- ADR-0005 (planned) — cross-family judge/generator, the named swap behind the `Judge`
  Protocol.
- `rag-eval` KB domain — a planned post-ADR `/new-kb` (sequenced after this ADR per the
  Sprint 2 knowledge plan), seeded by the judge-prompt / faithfulness / abstention
  concepts decided here.
