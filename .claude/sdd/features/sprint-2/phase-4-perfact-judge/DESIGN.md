# DESIGN: sprint-2/phase-4-perfact-judge — Per-Fact LLM-as-Judge

**Sprint/Phase:** sprint-2/phase-4-perfact-judge | **Date:** 2026-05-23

## Architecture

Phase 4 opens the `eval` layer by adding a **judge submodule** to the installed
package — `src/enterprise_rag_ops/eval/` — that scores a Sprint 1 `AnswerWithSources`
against its question's `answer_facts` (per-fact recall/precision) and verifies that
each cited `doc_id` actually supports the claim (citation faithfulness). The output is
a machine-readable `JudgeVerdict` the Phase 6 runner aggregates and reports.

The layer mirrors the Phase 3 `generation` shape one-for-one — that is the whole point
of the design, so the judge inherits a proven seam, a proven offline-CI story, and a
proven schema-as-SSoT pattern rather than inventing new ones:

| Generation (Phase 3)              | Judge (Phase 4)                                    |
| --------------------------------- | -------------------------------------------------- |
| `AnswerWithSources` (schema SSoT) | `FactVerdict` / `CitationVerdict` / `JudgeVerdict` |
| `Generator` Protocol (seam)       | `Judge` Protocol (seam)                            |
| `OpenAIGenerator` (`strict` json) | `OpenAIJudge` (`strict` json, same call shape)     |
| `StubGenerator` (CI drop-in)      | `StubJudge` (CI drop-in)                           |
| `prompt.py` (pure builders)       | `prompt.py` (pure judge-prompt builders)           |
| `RAG_GEN_MODEL` env override      | `RAG_JUDGE_MODEL` env override                     |

Two things have **no analogue in generation** and are the genuinely new shape:

1. **Python-side aggregation** (`aggregate.py`). The three floats (`fact_recall`,
   `fact_precision`, `faithfulness_ratio`) are derived in pure Python from the two
   verdict lists — never by the LLM. They are therefore **excluded from the LLM-facing
   json_schema** (see Schema-as-SSoT wiring) and computed after the call returns.
2. **The `Question` loader** (`questions.py`). A thin typed reader over the dataset
   `questions` config at the pinned `DATASET_REVISION`, feeding judge call sites and
   (later) the Phase 5/6 runners.

### Layout decision — flat submodule, judge-prefixed names

`src/enterprise_rag_ops/eval/` is a **flat package**, not a `judge/` sub-package. The
judge files carry no `judge_` prefix because the module path (`eval.schema`,
`eval.interfaces`) already namespaces them — exactly as `generation.schema` /
`generation.interfaces` do. The flat layout is justified by the named, in-sprint growth
(SPRINT.md Phases 5–6) landing as **sibling files**, not a reshuffle:

```
src/enterprise_rag_ops/eval/
├── __init__.py
├── schema.py        # FactVerdict, CitationVerdict, JudgeVerdict          (FR-1/2/3)
├── aggregate.py     # pure-Python aggregation: two lists -> three floats   (FR-4)
├── interfaces.py    # Judge Protocol (the ADR-0005 seam)                   (FR-5)
├── prompt.py        # build_judge_system_prompt / build_judge_user_prompt  (FR-6)
├── openai_judge.py  # OpenAIJudge                                          (FR-6)
├── stub_judge.py    # StubJudge (CI drop-in)                              (FR-7)
└── questions.py     # Question model + load_questions() loader            (FR-8)
   # Phase 5 adds:  retrieval_metrics.py, corpus_sampling.py  (siblings, no reshuffle)
   # Phase 6 adds:  runner.py, report.py, cost.py             (siblings)
```

This keeps Phase 4 minimal while making the named future additions a localized change —
the seam discipline from CLAUDE.md § Engineering Behavior applied to the file layout
itself.

### Data flow

```
                        ┌──────────────────────────────────────────────────────────┐
   questions config     │                    Judge.judge(...)                       │
   @ DATASET_REVISION   │                                                            │
        │               │  question:str                                             │
        ▼               │  answer_with_sources: AnswerWithSources  (Phase 3 output)  │
  questions.load() ─────┼─►answer_facts: list[str]  (from Question.answer_facts)     │
   yields Question      │  retrieved_docs: list[Chunk]  (the docs the substrate saw) │
   (id, question,       │                          │                                 │
    answer_facts,       │                          ▼                                 │
    expected_doc_ids,   │   resolve cited docs: {doc_id -> text} for doc_id in       │
    category)           │     answer_with_sources.sources, looked up in              │
                        │     {c.doc_id: c.text for c in retrieved_docs}             │
                        │                          │                                 │
                        │                          ▼                                 │
                        │   prompt.build_judge_user_prompt(                          │
                        │     facts_checklist, cited_doc_blocks, answer, question)   │
                        │                          │                                 │
                        │      ┌───────────────────┴────────────────────┐           │
                        │      ▼ (OpenAIJudge)            ▼ (StubJudge)              │
                        │  chat.completions.create   deterministic verdict           │
                        │  response_format=json_schema   (all present /              │
                        │  strict:true  built from        all supported)             │
                        │  JudgeVerdict LLM-facing surface                           │
                        │      │                          │                          │
                        │      ▼ defensive re-validate     │                         │
                        │  per_fact[], per_citation[] ◄────┘                         │
                        │                          │                                 │
                        │                          ▼                                 │
                        │   aggregate(per_fact, per_citation)  (pure Python, FR-4)   │
                        │     -> fact_recall, fact_precision, faithfulness_ratio     │
                        │        (float | None on empty denominators)               │
                        │                          │                                 │
                        │                          ▼                                 │
                        │            JudgeVerdict(per_fact, per_citation,            │
                        │              fact_recall, fact_precision,                  │
                        │              faithfulness_ratio)                          │
                        └──────────────────────────────────────────────────────────┘
```

`make verify` exercises this whole shape through `StubJudge` + hand-built verdicts —
no network, no `OPENAI_API_KEY` (NFR-1). The live `OpenAIJudge` path is reached only by
a gated/cassette test (FR-12, Should-tier).

### Cited-doc resolution (the anchor-case mechanism)

The faithfulness signal lives in **how cited docs are resolved and rendered**.
`OpenAIJudge.judge` builds a `doc_id -> text` map from `retrieved_docs`
(`{c.doc_id: c.text for c in retrieved_docs}`), then iterates
`answer_with_sources.sources` (the cited `doc_id`s, in emission order):

- For each cited `doc_id` present in the map, render a **separately named block keyed by
  that `doc_id`** in the user prompt (`=== doc {doc_id} ===\n{text}`). One block per
  cited doc — never a merged context blob. This per-`doc_id` isolation is what lets the
  judge answer "does _this_ doc's text support the claim?" and is the direct
  discriminator the anchor case exploits (BRAINSTORM Anchor case check).
- A cited `doc_id` **not** in the retrieved set is rendered as an explicit
  `=== doc {doc_id} (text unavailable) ===` block, so the judge can still return
  `unsupported` rather than the citation silently vanishing. (Resolution policy is a
  pure-function detail; the exact "unavailable" wording is finalized in `/implement`.)

`answer_facts` are rendered as a numbered checklist; the judge returns one `FactVerdict`
per checklist item and one `CitationVerdict` per cited `doc_id`.

## File Manifest

| File                                          | Change   | Owner (agent / direct) | Phase order |
| --------------------------------------------- | -------- | ---------------------- | ----------- |
| `src/enterprise_rag_ops/eval/questions.py`    | created  | direct                 | 1           |
| `pyproject.toml`                              | modified | direct                 | 2           |
| `src/enterprise_rag_ops/eval/__init__.py`     | created  | direct                 | 3           |
| `src/enterprise_rag_ops/eval/schema.py`       | created  | direct                 | 3           |
| `src/enterprise_rag_ops/eval/aggregate.py`    | created  | direct                 | 3           |
| `src/enterprise_rag_ops/eval/interfaces.py`   | created  | direct                 | 3           |
| `src/enterprise_rag_ops/eval/stub_judge.py`   | created  | direct                 | 3           |
| `src/enterprise_rag_ops/eval/prompt.py`       | created  | direct                 | 3           |
| `src/enterprise_rag_ops/eval/openai_judge.py` | created  | direct                 | 3           |
| `tests/eval/__init__.py`                      | created  | direct                 | 6           |
| `tests/eval/conftest.py`                      | created  | direct                 | 6           |
| `tests/eval/test_schema.py`                   | created  | direct                 | 6           |
| `tests/eval/test_aggregate.py`                | created  | direct                 | 6           |
| `tests/eval/test_judge_contract.py`           | created  | direct                 | 6           |
| `tests/eval/test_questions_loader.py`         | created  | direct                 | 6           |
| `tests/eval/test_openai_judge.py`             | created  | direct                 | 6           |
| `tests/eval/test_judge_anchor.py`             | created  | direct                 | 6           |
| `docs/adr/0001-eval-framework.md`             | modified | direct                 | 7           |
| `docs/adr/README.md`                          | modified | direct                 | 7           |

Owner is `direct` for every file — no eval/judge specialist agent exists, and DEFINE's
Infrastructure Readiness explicitly declines to scaffold one for this phase (a single
structured-output prompt + Pydantic verdict schema + pure-Python aggregation is small
and well-bounded). The `.claude/agents/` inventory confirms no candidate specialist:
only workflow agents (`brainstorm/define/design-agent`, `code-reviewer`, `kb-architect`)
exist, none with eval `kb_domains`.

Notes on placement vs. the convention's "eval harness" phase slot: the eval files live
under `src/enterprise_rag_ops/eval/` (orchestrator decision 1 — shipped/importable
library code, src-layout convention, future `rag-eval` console script), **not** a
top-level `eval/`. They map to phase-order step 3 ("core module logic") because, for
this phase, the eval layer _is_ the core module being built — there is no separate
upstream `src/` change. Tests mirror at `tests/eval/`.

### Module responsibilities

- **`eval/schema.py`** (FR-1/2/3, NFR-4) — three Pydantic models.
  `FactVerdict{fact: str, verdict: Literal["present","absent","contradicted"]}` and
  `CitationVerdict{doc_id: str, verdict: Literal["supported","unsupported"]}`, both
  `model_config = ConfigDict(extra="forbid")`. `JudgeVerdict` carries
  `per_fact: list[FactVerdict]`, `per_citation: list[CitationVerdict]`, and the three
  aggregate floats typed **`float | None`** (orchestrator decision 2). The two lists are
  the LLM-facing surface; the three floats are Python-derived and default to `None`.
  Mirrors `generation/schema.py` (same `extra="forbid"` / closed-schema invariant).
- **`eval/aggregate.py`** (FR-4) — one pure function
  `aggregate(per_fact, per_citation) -> tuple[float | None, float | None, float | None]`
  (or a small frozen result type), no LLM call, no I/O. Returns
  `fact_recall = |present| / |facts|`,
  `fact_precision = |present| / (|present| + |contradicted|)`,
  `faithfulness_ratio = |supported| / |citations|`. **Empty-denominator convention =
  `None`** (decision 2): empty `per_fact` → `fact_recall = None`; `|present|+|contradicted| == 0`
  → `fact_precision = None`; empty `per_citation` → `faithfulness_ratio = None`. An
  abstention with no facts/citations yields `(None, None, None)` — "not applicable", not
  "perfectly faithful". Deterministic (NFR-2): identical lists → byte-identical floats.
- **`eval/interfaces.py`** (FR-5, NFR-3) — the `Judge` Protocol,
  `@runtime_checkable`, single synchronous method
  `judge(question: str, answer_with_sources: AnswerWithSources, answer_facts: list[str], retrieved_docs: list[Chunk]) -> JudgeVerdict`.
  Mirrors `generation/interfaces.py` docstring tone; names the ADR-0005 swap as the
  justified seam. No same-family assumption in the contract.
- **`eval/prompt.py`** (FR-6, NFR-2) — pure builders
  `build_judge_system_prompt()` and
  `build_judge_user_prompt(question, answer, answer_facts, cited_doc_blocks)`. Renders
  `answer_facts` as a numbered checklist and each cited doc as a named `doc_id` block
  (see Cited-doc resolution). No client, no I/O, no env reads — deterministic, mirrors
  `generation/prompt.py`.
- **`eval/openai_judge.py`** (FR-6, NFR-2/4/7) — `OpenAIJudge` implements `Judge`. One
  `client.chat.completions.create` call with
  `response_format={"type":"json_schema","json_schema":{...,"strict":true}}` built from
  `JudgeVerdict`'s **LLM-facing** schema (see Schema-as-SSoT wiring); resolves cited docs;
  defensively re-validates the response through Pydantic (typed `ValidationError` on
  drift); reads `RAG_JUDGE_MODEL` (default a configurable constant, no same-family
  hard-wiring); raises a clean `RuntimeError` naming the missing env var when
  `OPENAI_API_KEY` is unset (NFR-7). After the call returns the two lists, it runs
  `aggregate(...)` and constructs the full `JudgeVerdict`. Temperature left at model
  default (GPT-5-class constraint, same as `OpenAIGenerator`).
- **`eval/stub_judge.py`** (FR-7) — `StubJudge` implements `Judge`; returns a
  deterministic `JudgeVerdict` with every supplied fact `present` and every cited
  `doc_id` `supported`, with the three aggregates computed via `aggregate(...)` (so the
  stub path also exercises real aggregation). No API key, no network. Mirrors
  `StubGenerator`.
- **`eval/questions.py`** (FR-8) — a thin typed `Question` model (`question_id`,
  `question`, `answer_facts: list[str]`, `expected_doc_ids: list[str]`, `category`) and
  `load_questions(limit: int | None = None, question_ids: list[str] | None = None) ->
Iterator[Question]`, streaming the `questions` config (`DOCUMENTS_SPLIT`-equivalent
  `test` split) at `DATASET_REVISION` imported from `enterprise_rag_ops.ingest.config`
  (single SHA SSoT). No category-filter parameter (Q5). The raw→`Question` field mapping
  is confirmed by a one-time streamed inspection during `/implement` (see Risks).
- **`tests/eval/conftest.py`** — fixtures mirroring `tests/generation/conftest.py`: a
  `FakeOpenAIClient` returning a canned structured-output payload (for `OpenAIJudge`
  message/call-shape assertions), hand-built `FactVerdict`/`CitationVerdict` lists, and a
  sample `AnswerWithSources` + `list[Chunk]` for the anchor case.
- **`docs/adr/0001-eval-framework.md`** (FR-11) — rewritten `deferred → accepted` (see
  ADR-0001 Scope). **`docs/adr/README.md`** index row updated (`0001 … accepted … 2026-05-23`).

## Schema-as-SSoT wiring (NFR-4)

`JudgeVerdict` is the canonical schema, exactly as `AnswerWithSources` is in
`OpenAIGenerator` — but with one deliberate refinement: the **three aggregate floats are
not part of the LLM-facing schema**. The LLM is asked to produce only the two verdict
lists; the floats are derived afterward in Python (FR-3/FR-4, decision 2). The wiring:

- **LLM-facing surface.** `OpenAIJudge` does **not** feed
  `JudgeVerdict.model_json_schema()` whole to the API (that schema includes the three
  floats). Instead the LLM-facing surface is the two-list subset. Two clean options for
  `/implement` (both keep a single SSoT; choose during build, no re-litigation needed):
  1. a tiny private `_LLMJudgeVerdict` Pydantic model holding only
     `per_fact` + `per_citation`, whose `model_json_schema()` feeds the `strict`
     json_schema and whose validated instance is spread into the full `JudgeVerdict`
     after aggregation; or
  2. derive the LLM-facing schema from `JudgeVerdict.model_json_schema()` by dropping the
     three float properties before sending.
     Option 1 is the cleaner mirror of the generation pattern (one Pydantic model = one
     schema, re-validated defensively) and is the recommended default; the floats then have
     no `strict`-mode `required`/`additionalProperties` friction because they never enter
     the LLM schema.
- **Defensive re-validation.** The returned JSON is validated through the LLM-facing
  model (`_LLMJudgeVerdict.model_validate_json`), so drift surfaces as a typed
  `ValidationError` (NFR-2, mirrors `OpenAIGenerator`).
- **Aggregation then assembly.** `aggregate(per_fact, per_citation)` computes the three
  `float | None` values; `OpenAIJudge` constructs the public `JudgeVerdict(per_fact,
per_citation, fact_recall, fact_precision, faithfulness_ratio)`.
- **No hand-maintained schema string.** The json_schema is always
  `model_json_schema()`-derived; there is no parallel literal schema (NFR-4).

Both verdict models are closed (`extra="forbid"` → `additionalProperties: false`), so
`strict: true` rejects any extra field server-side before Pydantic sees it (AC-1/2).

## Implementation Phases

Ordered per the harness convention (data/dataset loader → config → core `src/` → tests →
docs/ADR). Phase 4 has no separate `observability/` work. Each step is independently
testable; `/implement` validates smallest-first (`uv run pytest tests/eval -k <step>`)
then `make verify`. Within "core `src/`" the sub-order is **smallest-testable-first** per
CLAUDE.md § Engineering Behavior — pure code (schema, aggregation) before the LLM call.

1. **Dataset loader — `Question` + `load_questions`** (`eval/questions.py`). First because
   it is the dataset-schema entry and is independently inspectable. First `/implement`
   action: a one-time streamed inspection of `questions@DATASET_REVISION` to confirm the
   raw field names (mirrors Phase 2 RQ-2 / Phase 3 RQ-10). Validate:
   `uv run pytest tests/eval/test_questions_loader.py`.
2. **Config — `pyproject.toml`** (NFR-5, AC-15). Add `vcrpy` (version-bounded) to
   `[dependency-groups] dev`; add a `cassette` (or reuse-pattern) pytest marker only if
   the cassette test lands; **no** runtime dep, no eval-framework lib, no second provider
   SDK. (A `rag-eval` console script is _not_ added in Phase 4 — there is no runner yet;
   it lands when Phase 6 ships `runner.py`.)
3. **Core `src/` — verdict schema → aggregation → Protocol+stub → prompt → OpenAIJudge.**
   The single largest step, but internally ordered smallest-first and each sub-unit has
   its own test (step 6):
   a. `eval/schema.py` — the three Pydantic models (FR-1/2/3). The contract every later
   sub-unit depends on. (`AC-1/2/3`.)
   b. `eval/aggregate.py` — pure aggregation incl. the `None` empty-denominator
   convention (FR-4). Pure Python, no deps on schema-internal LLM concerns. (`AC-4`.)
   c. `eval/interfaces.py` + `eval/stub_judge.py` — the `Judge` seam and its offline
   drop-in (FR-5/7). Stub depends on schema + aggregate only. (`AC-5/8`.)
   d. `eval/prompt.py` — pure judge-prompt builders incl. cited-doc resolution
   rendering (FR-6). No `openai` import. (`AC-7`.)
   e. `eval/openai_judge.py` — the live judge: single `strict` call, LLM-facing schema,
   defensive re-validate, aggregate-then-assemble, `RAG_JUDGE_MODEL`, NFR-7 guard
   (FR-6). The `openai` import lives only here, preserving the offline invariant.
   (`AC-6`.)
   `eval/__init__.py` is created alongside (export surface kept minimal).
4. _(Eval harness wiring — n/a this phase; the judge submodule is itself the eval core.)_
5. _(Observability hooks — n/a this phase; Sprint 3.)_
6. **Tests** (`tests/eval/`, FR-9/10). Mirror `tests/generation/`: `test_schema.py`
   (closed-schema + Literal-vocab `ValidationError`, AC-1/2/3), `test_aggregate.py`
   (formula + empty-list `None` edges, AC-4), `test_judge_contract.py` (`StubJudge`
   conforms to `Judge`, all-`present`/all-`supported`, offline, AC-5/8/10),
   `test_questions_loader.py` (typed yield of all five fields, `limit`/`question_ids`,
   no category param, AC-9), `test_openai_judge.py` (fake client: exactly one
   `create` call, `strict:true` json_schema from the LLM-facing surface, prompt contains
   the facts checklist + per-`doc_id` blocks, malformed payload → `ValidationError`,
   AC-6/7), `test_judge_anchor.py` (the spurious-"Paris"-citation case →
   `CitationVerdict.verdict == "unsupported"` and `faithfulness_ratio < 1.0`, offline via
   hand-built verdict and/or fake/cassette client, AC-11). The Should-tier vcrpy cassette
   (AC-12) is wired here if landed; its live-record path is marker-gated out of
   `make verify`. The corpus-coverage caveat (AC-13) is stated as a docstring/comment in
   `test_judge_contract.py` / `test_questions_loader.py` — no field, no code.
7. **Docs + ADR** (`docs/adr/0001-eval-framework.md`, `docs/adr/README.md`, FR-11/AC-14).
   Written last so it records the as-built decision. Update the README index row.

## ADR-0001 Scope (FR-11 / AC-14)

`docs/adr/0001-eval-framework.md` rewritten from `deferred` to `accepted`
(`Date: 2026-05-23`), matching ADR-0002/0003 headings and tone:

- **Context** — Sprint 1 emits `AnswerWithSources` but nothing scores it against
  `answer_facts` or verifies citation faithfulness; "passes smoke" ≠ "correct". Sprint 2
  needs per-fact recall/precision + doc-level faithfulness, an offline-CI seam story, and
  500-q cost discipline.
- **Decision** — **custom thin judge** (`Judge` Protocol + `OpenAIJudge` + `StubJudge`;
  single structured-output prompt; pure-Python aggregation), justified by `answer_facts`
  ingestion, doc-level (per-`doc_id`) faithfulness, abstention handling (the `None`
  N/A convention), and cost (1 call/q vs. 3).
- **Alternatives Considered** — the three-way table from BRAINSTORM Decision 1 (Custom /
  DeepEval / RAGAs v0.4): per-fact recall/precision, doc-level faithfulness, seam/CI
  story, 500-q cost, lock-in; the anchor-case discriminator (B/C score the merged blob,
  miss the wrong-`doc_id` citation). Records the **LangChain/litellm rejection
  rationale** (Q2: the Protocol seam already makes call sites provider-agnostic;
  structured-output is provider-specific enough that a unifying wrapper leaks where it
  matters most).
- **Consequences** — "What we accept" (one Should-tier dev dep `vcrpy`; `OpenAIJudge`
  needs `OPENAI_API_KEY` for live runs, CI uses `StubJudge`); "What changes when it
  changes" (the `Judge` Protocol is the named **ADR-0005** swap surface for the
  cross-family judge — `ClaudeJudge` / Ollama-via-`base_url` — a new file + one wiring
  line; `JudgeVerdict` is the Phase 6 runner's input contract); "Build-time invariants"
  (closed schema + `strict:true` + defensive re-validate; aggregation deterministic;
  the `None` empty-denominator convention).

## Infrastructure Gaps

Three-layer deep check. DEFINE's Infrastructure Readiness found zero blocking gaps; this
design confirms and refines.

| Gap Type           | Area            | Detail                                                                                                                                                                                                                                                                                                                                                                                | Recommendation                                                                                                                                                                                 |
| ------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Missing domain     | `rag-eval`      | No `rag-eval` KB domain in `_index.yaml` (only `rag-retrieval`). **Non-blocking, intentionally sequenced.** Per SPRINT.md Sprint-Wide Knowledge Plan, `/new-kb rag-eval` lands **after** ADR-0001 closes — and ADR-0001 is written _in this phase_. The pillar-3 research inbox (`rag-eval-2026-05-26.md`) + DEFINE/BRAINSTORM are sufficient grounding for `/implement`.             | `/new-kb rag-eval` **after** `/review` (documents the decided design).                                                                                                                         |
| Missing concept    | `rag-eval`      | Judge-prompt design, per-`doc_id` faithfulness scoring, the per-fact recall/precision formulas under abstention (`None` N/A), and the vcrpy cassette pattern have no KB home yet. **Non-blocking** — the design choices are pinned in DEFINE Q1–Q5 + this DESIGN; `/implement` does not need KB concepts to execute. They become the seed content for the deferred `rag-eval` domain. | Fold into `/new-kb rag-eval` post-ADR (one domain, several concepts).                                                                                                                          |
| Missing concept    | `rag-retrieval` | DEFINE Infra row maps `AnswerWithSources` / `Chunk` to `rag-retrieval`; both are reused **unchanged** — no new retrieval concept is introduced. Pass; the `rag-generation` / retrieval-widening KB debt (SPRINT.md "Carried-forward KB debt") is orthogonal to Phase 4.                                                                                                               | None for Phase 4 (carried-forward debt tracked in SPRINT.md).                                                                                                                                  |
| Missing specialist | eval / judge    | No eval/judge specialist agent exists; `.claude/agents/` holds only workflow agents + `code-reviewer` + `kb-architect`, none with eval `kb_domains`. **Not warranted** (DEFINE Infra): one structured-output prompt + Pydantic schema + pure-Python aggregation is small and well-bounded; no repeated specialist context-loading anticipated at Phase 4.                             | None. Revisit only if Phase 5/6 (multi-model runner, report, cross-family prompt iteration) surfaces repeated judge-specific friction → post-phase `**Harness suggestion:**` for `/new-agent`. |

**Summary:** zero blocking gaps. The one logged item — `/new-kb rag-eval` — is
deliberately sequenced _after_ ADR-0001 per SPRINT.md, not a Phase-4 blocker. No
specialist agent is recommended.

## Consistency Check

Non-trivial phase (>2 modules, multi-edit DEFINE), so the full six-pass run applies.
Cross-checked DEFINE ↔ DESIGN and the constitution (CLAUDE.md § Engineering Behavior +
§ Conventions, ADR-0002/0003, `_index.yaml`).

**Verdict: 🟡 MINOR DRIFT** — one known/accepted drift (CLAUDE.md architecture map),
flagged for a batched doc fix; no unresolved CRITICAL/HIGH; all 11 FR + 15 AC map to
manifest entries.

| ID  | Severity | Pass                 | Location                                      | Finding                                                                                                                                                                                                                                                                                                              | Suggested fix                                                                                                                                                                |
| --- | -------- | -------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | LOW      | 4 Constitution       | `CLAUDE.md` § Architecture vs. eval placement | CLAUDE.md's architecture map shows a **top-level `eval/`**; this design places eval at `src/enterprise_rag_ops/eval/` (orchestrator decision 1: src-layout, importable, future `rag-eval` script). **Known, accepted drift** — code reality will lead the doc.                                                       | Batched CLAUDE.md edit _after_ this phase lands (CLAUDE.md edits are cache-cost-batched per § Conventions). **Do not edit CLAUDE.md now.** Note logged for the orchestrator. |
| C2  | LOW      | 6 Inconsistency      | DEFINE FR-5/AC-5 vs. live code                | DEFINE's `Judge.judge` signature takes `retrieved_docs: list[Chunk]`; the live `rag-ask` path produces chunks via `retriever.retrieve_chunks` / `ContextAssembler` (not the older `retrieve` doc-level path). The judge contract is consistent with the as-built Phase 3 flow — no conflict, noted for traceability. | None — confirm at `/implement` that judge call sites receive the assembled `list[Chunk]`.                                                                                    |
| C3  | LOW      | 3 Underspecification | DEFINE FR-8 / `eval/questions.py`             | The raw `questions`-config field name for the question text is not pinned (`docs/dataset.md` lists `gold_answer`/`answer_facts`/`expected_doc_ids` but the retrieval smoke maps the text to `query`). `Question.question` is the model field; the raw→model mapping is unconfirmed.                                  | Resolve via the step-1 one-time streamed inspection (mirrors Phase 2 RQ-2 / Phase 3 RQ-10). Already in the Implementation Phases.                                            |
| C4  | —        | 1 Duplication        | DEFINE FR-3 ↔ FR-4                            | FR-3 ("floats derived in Python") and FR-4 ("pure-Python aggregation computes the floats") overlap. Not a conflict — FR-3 states the schema property, FR-4 the function. Design assigns them to distinct files (`schema.py` vs. `aggregate.py`).                                                                     | No action; complementary, not duplicative.                                                                                                                                   |
| C5  | —        | 2 Ambiguity          | DEFINE FR-4 (empty-denominator)               | DEFINE left the empty-denominator convention "pinned in `/design`". Resolved here to **`None`** (orchestrator decision 2), reflected in `JudgeVerdict` field types (`float \| None`) and `aggregate`. No remaining `TODO`/`???`.                                                                                     | Resolved.                                                                                                                                                                    |
| C6  | —        | 4 Constitution       | NFR-3 / NFR-5 vs. § Engineering Behavior      | `Judge` Protocol seam is justified by the **named ADR-0005** cross-family swap (in-sprint, Phase 5) — same grounds as the `Generator` seam in ADR-0003, not "in case". No `ClaudeJudge`/Ollama pre-built. No LangChain/litellm/second SDK. **Constitution-aligned.**                                                 | No action; this is the seam discipline working as intended.                                                                                                                  |
| C7  | —        | 5 Coverage           | DEFINE FR-1..11 / AC-1..15                    | Every FR maps to ≥1 manifest entry (FR-1/2/3→`schema.py`; FR-4→`aggregate.py`; FR-5→`interfaces.py`; FR-6→`openai_judge.py`+`prompt.py`; FR-7→`stub_judge.py`; FR-8→`questions.py`; FR-9/10→`tests/eval/*`; FR-11→`docs/adr/0001`). NFR-5 dev-dep→`pyproject.toml`. No orphan manifest entries.                      | No action; full bidirectional coverage.                                                                                                                                      |

Stranger-test note: this DESIGN is git-tracked and contains only system content
(architecture, schema, phase roles) — no budget hours, no career/portfolio framing, no
private-planning references.

## Risks & Trade-offs

| Risk                                                                                                                                                                                                                     | Mitigation                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LLM-facing schema must exclude the three aggregate floats** — feeding `JudgeVerdict.model_json_schema()` whole would put `fact_recall`/etc. into the `strict` schema and let the LLM emit (wrong) floats.              | The LLM-facing surface is the two-list subset only (recommended: a private `_LLMJudgeVerdict` with just `per_fact`+`per_citation`); the floats are derived after the call. Asserted by `test_openai_judge.py` (the sent json_schema has no float properties).                                               |
| **`strict:true` + nested-list schema friction** — OpenAI `strict` mode requires every property `required` and `additionalProperties:false` on nested objects; a list of closed Pydantic models must serialize correctly. | Both verdict models already carry `extra="forbid"`; Pydantic v2 `model_json_schema()` emits `additionalProperties:false`. Same path `OpenAIGenerator` proved. If `$defs`/`$ref` handling needs flattening for `strict`, that is an `/implement` detail caught by the fake-client test before any live call. |
| **Empty-denominator `None` propagation** — downstream Phase 6 averaging must treat `None` as N/A (exclude), not coerce to 0.                                                                                             | Phase 4 only _produces_ the `None` (decision 2); the design documents the contract in `JudgeVerdict`'s docstring and ADR-0001 consequences. Phase 6's averaging is out of scope here but the contract is recorded so it cannot be silently misread.                                                         |
| **Raw `questions`-field name unknown** (C3) — guessing the question-text key risks a loader that yields empty `question`.                                                                                                | One-time streamed dataset inspection is the _first_ `/implement` action (step 1), mirroring the established Phase 2/3 pattern; the loader is written against the confirmed schema, not a guess.                                                                                                             |
| **Offline-CI invariant** — a stray `from openai import OpenAI` outside `openai_judge.py` would let `make verify` pass on a dev box with the SDK cached but fail on a clean clone.                                        | The `openai` import lives **only** in `eval/openai_judge.py` (mirrors the generation invariant); `schema.py`/`aggregate.py`/`interfaces.py`/`prompt.py`/`stub_judge.py`/`questions.py` import no `openai`. `make verify` runs the eval tests minus the gated live/cassette marker.                          |
| **Cassette is Should-tier** — if vcrpy is not landed, AC-12 does not fail the phase, but the live `OpenAIJudge` path then has only fake-client coverage.                                                                 | Acceptable per AC-12 (Should-tier). `StubJudge` + the fake-client `test_openai_judge.py` carry the contract offline; the anchor case (FR-10) is provable via hand-built verdicts without any live call.                                                                                                     |

**ADR-worthy decisions:** the eval-framework choice itself is ADR-0001 (written this
phase, FR-11). The `Judge` seam's cross-family swap is **ADR-0005** (Phase 5) — named
here, not decided here. No new ADR beyond ADR-0001 is warranted for Phase 4.

## Next Step

→ `/implement sprint-2/phase-4-perfact-judge` — no blocking infrastructure gaps; proceed
directly. First action is the one-time streamed inspection of `questions@DATASET_REVISION`
to confirm the raw field mapping for `eval/questions.py` (resolves C3). The `/new-kb
rag-eval` recommendation is deferred to post-ADR-0001 per SPRINT.md; the CLAUDE.md
architecture-map fix (C1) is a batched doc change for the orchestrator, not part of this
phase's edits.
