# DEFINE: sprint-2/phase-4-perfact-judge — Per-Fact LLM-as-Judge

**Sprint/Phase:** sprint-2/phase-4-perfact-judge | **Date:** 2026-05-23

## Resolved Open Questions

The BRAINSTORM contains five **Decided (2026-05-23)** blocks pinning every open
question. They are recorded here so `/design` and `/implement` treat them as fixed —
do **not** re-open them. All five were resolved by the user directly in the BRAINSTORM;
they are **confirmed inputs, not unconfirmed assumptions** — no orchestrator
re-confirmation is needed before `/design`.

- **Q1 — Determinism strategy (Option a).** `Judge.judge()` is a **synchronous
  single LLM call** per question. Determinism rests on `strict: true` structured
  output plus a closed, discrete verdict vocabulary (`Literal` enums enforced at
  decode time), not on majority-vote-over-N. Multi-sample aggregation is deferred as
  an escalation only if observed drift on the anchor cases proves the vocabulary
  insufficient.
- **Q2 — Seam and provider.** A `Judge` Protocol + native-SDK implementations
  (`OpenAIJudge` now, `ClaudeJudge` later), mirroring `Generator`/`StubGenerator`.
  The native `openai` SDK with `response_format` json_schema `strict: true` — **not**
  LangChain or litellm (rejected; rationale belongs in ADR-0001). Judge model
  configurable via `RAG_JUDGE_MODEL`. Phase 4 ships **`OpenAIJudge` only** — no second
  provider SDK. Cross-family judge independence (`ClaudeJudge`, an Ollama-backed class
  via `base_url`) is deferred to ADR-0005 / Phase 5; Phase 4 must **not hard-wire
  same-family assumptions** that would block it.
- **Q3 — Verdict schema (Option A, flat two-list).** `JudgeVerdict` holds
  `per_fact: list[FactVerdict]` and `per_citation: list[CitationVerdict]` plus
  aggregated `fact_recall`, `fact_precision`, `faithfulness_ratio` floats **computed
  in Python**, not by the LLM. `FactVerdict{fact, verdict: present|absent|contradicted}`;
  `CitationVerdict{doc_id, verdict: supported|unsupported}`. The schema is designed so
  an optional `supporting_doc_id` on `FactVerdict` is a future **additive,
  non-breaking** extension — **do not build it now.**
- **Q4 — Corpus-coverage caveat (document, no code).** The dev subset has gold docs for
  only ~3 of 500 questions. Both judge dimensions (per-fact answer scoring and
  per-citation faithfulness) are robust to this — the judge scores generated text, not
  retrieval. The caveat is stated in the acceptance criteria (AC-13); **no
  `corpus_coverage_warning` field is built.** The real fix (gold-aware corpus sampling)
  is a Phase 5 opening task.
- **Q5 — Questions loader (Option a, thin).** A thin, typed `Question` loader in the
  eval tree, streaming the `questions` config at the pinned `DATASET_REVISION`
  (imported from `enterprise_rag_ops.ingest.config` to keep the SHA a single SSoT).
  Yields all typed `Question` objects (`question_id`, `question`, `answer_facts`,
  `expected_doc_ids`, `category`); callers filter by category/id with list
  comprehensions. An optional `limit` / `question_ids` arg for dev iteration is the
  only subsetting in scope. **Category filtering is not a loader feature.** Open
  mechanic for `/design` (does not change placement): whether the eval tree is an
  installable top-level `eval/` or a `src/enterprise_rag_ops/eval/` submodule.

## Requirements

### Functional

- **FR-1 (`FactVerdict` model)** — A Pydantic model `FactVerdict` with exactly two
  fields: `fact: str` and `verdict: Literal["present", "absent", "contradicted"]`. The
  schema is closed (`extra="forbid"` → `additionalProperties: false`) so OpenAI
  `strict: true` mode rejects extra fields. Designed so an optional `supporting_doc_id`
  is a later additive field (Q3) — not present in Phase 4.
- **FR-2 (`CitationVerdict` model)** — A Pydantic model `CitationVerdict` with exactly
  two fields: `doc_id: str` and `verdict: Literal["supported", "unsupported"]`. Closed
  schema, same `strict`-compatibility invariant as FR-1.
- **FR-3 (`JudgeVerdict` model)** — A Pydantic model `JudgeVerdict` carrying
  `per_fact: list[FactVerdict]`, `per_citation: list[CitationVerdict]`, and the
  aggregated floats `fact_recall`, `fact_precision`, `faithfulness_ratio`. The two
  lists are the LLM-produced surface; the three floats are **derived in Python**, never
  by the LLM. `JudgeVerdict` (specifically the two-list LLM-facing surface) is the
  single canonical schema feeding both the OpenAI structured-output JSON schema and the
  judge call sites — mirroring how `AnswerWithSources` is the SSoT in `OpenAIGenerator`.
- **FR-4 (Python-side aggregation)** — A pure-Python aggregation function (no LLM call,
  no I/O) computes the three floats from the two verdict lists:
  `fact_recall = |present| / |facts|`;
  `fact_precision = |present| / (|present| + |contradicted|)`;
  `faithfulness_ratio = |supported| / |citations|`. Edge cases are defined and total:
  empty `per_fact` and empty `per_citation` (e.g. an abstention with no citations) yield
  defined values rather than a `ZeroDivisionError` (the exact convention — `0.0` vs.
  `None`/`1.0` for empty denominators — is pinned in `/design`).
- **FR-5 (`Judge` Protocol)** — A `Judge` Protocol exists in the eval tree with a single
  method
  `judge(question: str, answer_with_sources: AnswerWithSources, answer_facts: list[str], retrieved_docs: list[Chunk]) -> JudgeVerdict`.
  It is **synchronous and single-call** (Q1). The Protocol is the named seam ADR-0005 /
  Phase 5 will swap behind (the cross-family judge). (Exact parameter names/order are
  finalized in `/design`; the contract is question + `AnswerWithSources` + supplied
  facts + the cited/retrieved doc text.)
- **FR-6 (`OpenAIJudge`)** — An `OpenAIJudge` class implements `Judge`. It issues a
  **single** `client.chat.completions.create` call with
  `response_format={"type": "json_schema", "json_schema": ..., "strict": true}` built
  from `JudgeVerdict`'s LLM-facing schema. The prompt injects `answer_facts` as a
  checklist and **each cited doc's text as a separately named block keyed by `doc_id`**
  (the doc-level faithfulness design that catches the anchor case). It defensively
  re-validates the returned JSON through Pydantic so drift surfaces as a typed
  `ValidationError`, not an opaque SDK exception (mirrors `OpenAIGenerator`). Default
  model configurable via `RAG_JUDGE_MODEL`; no same-family assumption is hard-wired (Q2).
- **FR-7 (`StubJudge`)** — A `StubJudge` implementing `Judge` returns a deterministic
  `JudgeVerdict`: every supplied fact `present`, every cited `doc_id` `supported`. It is
  the CI-safe drop-in for `OpenAIJudge` through the `Judge` seam — no API key, no
  network. Mirrors `StubGenerator`.
- **FR-8 (`Question` loader)** — A thin, typed `Question` loader in the eval tree streams
  the `questions` config from the dataset at `DATASET_REVISION` (imported from
  `enterprise_rag_ops.ingest.config` — single SHA SSoT) and yields typed `Question`
  objects with `question_id`, `question`, `answer_facts`, `expected_doc_ids`, `category`.
  An optional `limit` / `question_ids` arg supports dev subsetting. Category filtering is
  **not** a loader feature (callers use list comprehensions, Q5).
- **FR-9 (Unit tests)** — Mirrored tests cover: (a) the `StubJudge` contract (returns a
  valid `JudgeVerdict`, all-`present`/all-`supported`, offline); (b) the aggregation
  logic over hand-built verdict lists including the empty-list edge cases (pure Python,
  no API); (c) the `Question` loader yields correctly typed `Question` objects with all
  five fields populated. All run under `make test` with no network and no
  `OPENAI_API_KEY`.
- **FR-10 (Anchor-case test)** — A unit test encodes the spurious-citation thesis case:
  a hand-built input where a cited `doc_id`'s text does **not** support the asserted
  claim ("the capital of France is Paris" cited against an unrelated google_drive doc)
  yields that `CitationVerdict.verdict == "unsupported"`, dragging `faithfulness_ratio`
  below `1.0`. To stay offline, this is exercised either by feeding a hand-built
  `JudgeVerdict` through the aggregation path or by the gated/cassette `OpenAIJudge`
  path (FR-12) — the live API is never hit under `make test`.
- **FR-11 (ADR-0001 written)** — `docs/adr/0001-eval-framework.md` is rewritten from its
  current `deferred` stub to an accepted ADR: a three-way **RAGAs / DeepEval / custom**
  comparison (per-fact recall/precision, doc-level faithfulness, CI/seam story, 500-q
  cost, lock-in), the decision (**custom thin judge**) justified by `answer_facts`
  ingestion, doc-level faithfulness, abstention handling, and cost, and the
  consequences. It records the LangChain/litellm rejection rationale (Q2).

### Non-functional

- **NFR-1 (Offline CI / no API key)** — `make test` runs the judge contract,
  aggregation, loader, and anchor-case tests with `StubJudge` (and hand-built verdicts)
  and performs **no network I/O**. No `OPENAI_API_KEY` is required for `make test` to
  pass. Any live `OpenAIJudge` test is gated (marker-excluded) or cassette-replayed.
- **NFR-2 (Determinism / reproducibility)** — `OpenAIJudge` carries reproducibility via
  `strict: true` structured output + the closed discrete verdict vocabulary (Q1), plus
  defensive Pydantic re-validation of the returned JSON (mirrors `OpenAIGenerator`).
  Temperature is left at the model default (GPT-5-class models reject an explicit
  temperature; same constraint as the generator). The aggregation function is fully
  deterministic — same verdict lists yield byte-identical floats.
- **NFR-3 (Minimal scope / clean seam)** — The `Judge` Protocol is justified solely by
  the named ADR-0005 swap (cross-family judge). **No** alternative judge implementations
  (`ClaudeJudge`, Ollama-backed) are pre-built. The seam's shape avoids same-family
  hard-wiring; the implementation behind it is `OpenAIJudge` + `StubJudge` only.
- **NFR-4 (Schema as SSoT)** — `JudgeVerdict`'s LLM-facing schema (via
  `model_json_schema()`) is the single source feeding the OpenAI `strict` json_schema,
  mirroring how `AnswerWithSources.model_json_schema()` is used in `OpenAIGenerator`. No
  hand-maintained parallel JSON schema string.
- **NFR-5 (Dependency hygiene)** — `pyproject.toml` adds **at most one new dev
  dependency** (`vcrpy`, version-bounded) for the cassette pattern; `openai` and
  `pydantic` are already present (no new runtime deps). **No** eval-framework library
  (RAGAs, DeepEval), no second provider SDK, no LangChain/litellm is added.
- **NFR-6 (Conventions)** — New code lives in the eval tree (exact location pinned in
  `/design` per the Q5 mechanic) with mirrored test files. `make lint test` (lint + pytest excluding gated markers) passes. English code/docs; YYYY-MM-DD dates.
- **NFR-7 (Graceful API-key error)** — If `OPENAI_API_KEY` is unset when `OpenAIJudge`
  is constructed for a live run, the failure is a clear human-readable message naming
  the missing env var, not an OpenAI SDK stack trace (mirrors `OpenAIGenerator`).
- **NFR-8 (Cost discipline, sanity bound)** — Phase 4 is the judge only; one synchronous
  LLM call per question (Q1). No cost-tracking code ships in Phase 4 (Phase 6 owns it);
  the per-question single-call shape is the sanity bound that keeps the eventual 500-q
  run affordable.

## Acceptance Criteria

1. `FactVerdict` is a Pydantic model with exactly `fact: str` and
   `verdict: Literal["present", "absent", "contradicted"]`; constructing with a valid
   verdict succeeds; an out-of-vocabulary verdict string raises `ValidationError`; the
   schema is closed (extra fields rejected).
2. `CitationVerdict` is a Pydantic model with exactly `doc_id: str` and
   `verdict: Literal["supported", "unsupported"]`; valid construction succeeds, an
   out-of-vocabulary verdict raises `ValidationError`, extra fields are rejected.
3. `JudgeVerdict` is a Pydantic model carrying `per_fact: list[FactVerdict]`,
   `per_citation: list[CitationVerdict]`, and the floats `fact_recall`,
   `fact_precision`, `faithfulness_ratio`; `JudgeVerdict.model_json_schema()` (LLM-facing
   surface) is consumable as an OpenAI `strict` json_schema.
4. The aggregation function, given hand-built verdict lists, returns
   `fact_recall = |present|/|facts|`, `fact_precision = |present|/(|present|+|contradicted|)`,
   and `faithfulness_ratio = |supported|/|citations|`; for empty `per_fact` and empty
   `per_citation` it returns the pinned defined value (no `ZeroDivisionError`). It
   performs no network or LLM call.
5. A `Judge` Protocol exists in the eval tree declaring a single synchronous
   `judge(question, answer_with_sources, answer_facts, retrieved_docs) -> JudgeVerdict`
   method; `OpenAIJudge` and `StubJudge` both satisfy it (verifiable via
   `isinstance`-style runtime check or a structural conformance test).
6. `OpenAIJudge` issues exactly **one** `chat.completions.create` call per `judge()`
   invocation with `response_format={"type": "json_schema", ..., "strict": true}` built
   from `JudgeVerdict`'s schema, honors `RAG_JUDGE_MODEL`, and re-validates the returned
   JSON through Pydantic (a malformed/extra-field response surfaces as a typed
   `ValidationError`). Verified with a fake/recorded client — no live call under
   `make test`.
7. `OpenAIJudge`'s prompt includes `answer_facts` rendered as a checklist and each
   cited doc's text as a separately named block keyed by its `doc_id` (asserted by
   inspecting the constructed prompt/messages with a fake client; the per-`doc_id`
   isolation is what enables the anchor-case verdict).
8. `StubJudge` implements `Judge` and returns a deterministic `JudgeVerdict` with every
   supplied fact `present` and every cited `doc_id` `supported`, with no API key and no
   network.
9. The `Question` loader streams the `questions` config at `DATASET_REVISION` (imported
   from `enterprise_rag_ops.ingest.config`) and yields typed `Question` objects exposing
   `question_id`, `question`, `answer_facts`, `expected_doc_ids`, `category`; an optional
   `limit` / `question_ids` arg restricts the yielded set; the loader does **not** expose
   a category-filter parameter.
10. The `StubJudge`-contract, aggregation, and loader-schema tests run under
    `make test` with no network access and no `OPENAI_API_KEY`, and pass.
11. The anchor-case test asserts that an input whose cited `doc_id` text does not support
    the claim yields that `CitationVerdict.verdict == "unsupported"` and a
    `faithfulness_ratio < 1.0`; the test is offline (hand-built verdict and/or
    cassette/fake client).
12. The Should-tier vcrpy cassette fixture (if landed) lets the `OpenAIJudge` live test
    replay from a recorded cassette under `make test` with no live call; the live
    record path is gated behind a marker excluded from the default run. (Should-tier —
    its absence does not fail the phase, but if present it must not hit the network in
    CI.)
13. **Corpus-coverage caveat (Q4):** the DEFINE and the judge tests explicitly state that
    the dev subset contains gold docs for only ~3 of 500 questions, that low end-to-end
    recall under such a corpus is a **data-coverage artifact, not a judge failure**
    (the judge scores generated text, not retrieval), and that the fix (gold-aware
    sampling) is a Phase 5 task. No `corpus_coverage_warning` field is implemented.
14. `docs/adr/0001-eval-framework.md` is rewritten from `deferred` to an accepted ADR
    containing the three-way RAGAs / DeepEval / custom comparison, the **custom**
    decision justified by `answer_facts` ingestion + doc-level faithfulness + abstention
    handling + cost, the LangChain/litellm rejection rationale, and the consequences.
15. `pyproject.toml` adds at most one new dev dependency (`vcrpy`, version-bounded) and
    **no** new runtime dependency, eval-framework library, second provider SDK, or
    LLM-wrapper library; `make lint test` (lint + pytest excluding gated
    markers) passes with the new code under the eval tree and mirrored tests.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                                                                                                                                             |
| ----------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit with evidence: "passes smoke" ≠ "correct"; the substrate emits `AnswerWithSources` but nothing scores it against `answer_facts` or verifies citation faithfulness. The anchor case (spurious "Paris" citation to an unrelated doc) is concrete evidence of the gap the judge must catch.     |
| Users       | 2     | Consumers are the downstream Phase 6 multi-model runner/report (named) and the maintainer iterating on the judge prompt. Substrate/internal phase — no external end user, so the workflow-impact dimension is inherently thin (consistent with the Phase 1–3 DEFINEs).                                           |
| Success     | 3     | 15 numbered, falsifiable acceptance criteria, each with a concrete pass/fail check covering every FR/NFR, the anchor-case verdict, the offline-CI invariant, the corpus-coverage caveat, ADR-0001, and dependency hygiene.                                                                                       |
| Scope       | 3     | Full MoSCoW in the BRAINSTORM with an explicit 9-item Won't list (retrieval metrics, abstention scoring, ADR-0005, multi-model runner, HTML/MD report, parallel execution, cost/latency tracking, gold-corpus rebuild, inter-doc conflict detection, judge-call caching).                                        |
| Constraints | 3     | All constraints named as NFRs: offline-CI invariant, determinism/reproducibility (strict structured output + discrete vocab + defensive re-validation), minimal-scope seam (no pre-built alternatives, no same-family hard-wiring), schema-as-SSoT, dependency hygiene (≤1 new dev dep), graceful API-key error. |

**Total: 14/15 — PASS (≥12).** Users scored 2: an internal eval-harness phase whose
"user" is the downstream Phase 6 runner plus the maintainer, so the workflow-impact
dimension is inherently thin — acceptable, not a blocker, and consistent with the
Phase 1–3 DEFINEs. All five BRAINSTORM open questions are resolved with confirmed
user inputs, so no `AskUserQuestion` round was needed; no ambiguity was invented beyond
what the BRAINSTORM closed.

## Infrastructure Readiness

| Dependency                                 | KB domain       | Specialist | Status                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------ | --------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HF `questions` config @ `DATASET_REVISION` | none needed     | none       | Ready — same pinned SHA as Phase 1/2 (`69916e31…`); the loader imports `DATASET_REVISION` from `enterprise_rag_ops.ingest.config` (single SSoT). `questions` schema (`gold_answer`, `answer_facts`, `expected_doc_ids`, `category`) confirmed in `docs/dataset.md`.                                                                                                                                                        |
| `AnswerWithSources` schema (Phase 3)       | `rag-retrieval` | none       | Ready — exists in `generation/schema.py`; reused unchanged as the judge's answer-input contract.                                                                                                                                                                                                                                                                                                                           |
| `Chunk` dataclass (Phase 2)                | `rag-retrieval` | none       | Ready — `chunk_id`, `doc_id`, `text` in `retrieval/schema.py`; the faithfulness judge reads per-doc text via `doc_id`. Reused unchanged.                                                                                                                                                                                                                                                                                   |
| `openai` Python SDK (structured outputs)   | none needed     | none       | Ready — already a runtime dep (`openai>=1.50,<2.0`); the `response_format` json_schema `strict: true` path is the same one `OpenAIGenerator` uses. No new dep.                                                                                                                                                                                                                                                             |
| `pydantic` (verdict models)                | none needed     | none       | Ready — already a runtime dep (`pydantic>=2.6,<3.0`). No new dep.                                                                                                                                                                                                                                                                                                                                                          |
| `RAG_JUDGE_MODEL` env var + model access   | none needed     | none       | Ready (local) — needs `OPENAI_API_KEY` for any live judge run; CI uses `StubJudge` (NFR-1). Env-var-only config mirrors `RAG_GEN_MODEL`.                                                                                                                                                                                                                                                                                   |
| `vcrpy` (cassette pattern)                 | none needed     | none       | **New dev dep (Should-tier).** Version-bounded addition to `[dependency-groups] dev` (NFR-5). Supports the CLAUDE.md cassette/replay convention for the live `OpenAIJudge` test; non-blocking — `StubJudge` carries the contract.                                                                                                                                                                                          |
| `rag-eval` KB domain                       | (none yet)      | none       | **Intentionally deferred — not a blocker.** Per SPRINT.md Sprint-Wide Knowledge Plan, `/new-kb rag-eval` lands **after** ADR-0001 closes (the ADR is written in this phase). The pillar-3 research inbox + this DEFINE are sufficient grounding for `/implement`; the KB documents the decided design afterward.                                                                                                           |
| Eval/judge specialist agent                | n/a             | none       | **Not warranted yet.** A single structured-output prompt + Pydantic verdict schema + pure-Python aggregation is a small, well-bounded build; no repeated specialist context-loading is anticipated at Phase 4. Revisit only if Phase 5/6 (multi-model runner, report, prompt iteration across families) surfaces repeated judge-specific friction — that would be a post-phase `**Harness suggestion:**` for `/new-agent`. |

No `/new-kb` or `/new-agent` blocks Phase 4. Two non-blocking items are logged for the
orchestrator: `/new-kb rag-eval` is **sequenced after** ADR-0001 (per SPRINT.md), and no
specialist agent is recommended for this phase. All ambiguity has a confirmed BRAINSTORM
input; no new gaps were identified.

## Next Step

→ `/design sprint-2/phase-4-perfact-judge`
