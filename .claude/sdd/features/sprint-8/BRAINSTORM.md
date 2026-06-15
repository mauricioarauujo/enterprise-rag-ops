# BRAINSTORM: sprint-8/phase-1-faithfulness-schema — Supporting-Doc Attribution on FactVerdict

**Sprint/Phase:** sprint-8/phase-1-faithfulness-schema | **Date:** 2026-06-14

---

## Problem Statement

Today `FactVerdict` records whether a gold fact is present/absent/contradicted in the
answer but carries no information about which document was the source (or culprit).
Phase 1 adds an optional `supporting_doc_id` to `FactVerdict`, makes the LLM emit it
under `strict` mode, validates it against the retrieved set, and persists it in the
eval record — so phase 2 can perform the root-cause cross-reference ("fact failed
because that doc was never retrieved").

---

## Suggested Research & KB Work

| Topic                                  | Coverage                                                                                                                                                     | Action                                                                                            |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Per-`doc_id` faithfulness isolation    | **Sufficient** — `rag-eval/concepts/per-doc-faithfulness.md` fully describes the per-block rendering convention and anchor case.                             | Read before implementing; no update needed.                                                       |
| Schema-as-SSoT / two-model split       | **Sufficient** — `rag-eval/concepts/schema-as-ssot.md` covers the `_LLMJudgeVerdict` / `JudgeVerdict` split and OpenAI `strict` constraints exactly.         | Read; no update needed until after implementation confirms the pattern holds for nullable fields. |
| Per-fact judge call                    | **Sufficient** — `rag-eval/patterns/per-fact-judge-call.md` describes the four-step call pattern including schema wiring.                                    | Read; may need a targeted update after phase 1 to add the nullable-field strict-mode note.        |
| OpenAI `strict` mode + nullable fields | **Thin** — the KB covers `additionalProperties: false` and `required`, but does not yet document how `strict: true` handles `["string","null"]` type unions. | No separate KB work now; capture the pattern in the pattern update after phase 1 lands.           |
| Failure-mode taxonomy                  | **Sufficient for now** — not touched in phase 1; phase 2's brainstorm will decide if a taxonomy extension needs KB work.                                     | Skip.                                                                                             |

No `--deep-research` needed. The schema decision is purely architectural; the KB and
codebase together are the complete evidence base.

---

## The Central Design Tension

The crux is **what `supporting_doc_id` means**, because that determines which documents
the judge must see when scoring each fact.

**Candidate readings:**

- **(a) Answer-citation reading:** The doc the answer explicitly cited when asserting
  this fact. Cheap — the judge already sees cited docs. But it cannot detect "fact
  absent because the right doc was never retrieved." It is citation-level attribution,
  not fact-level.

- **(b) Retrieved-set substantiation reading:** The doc in the full retrieved set whose
  text most directly substantiates this gold fact, regardless of what the answer cited.
  `None` when no retrieved doc covers the fact. This is the reading that powers the
  sprint's root-cause story: a `None` here means "the substantiating doc was not among
  those retrieved."

- **(c) Cited-set-only substantiation:** Like (b) but restricted to cited docs. Cheaper
  prompt (only cited docs rendered for fact scoring), but cannot distinguish "the right
  doc existed in the retrieved set and was ignored" from "the right doc was never
  retrieved at all."

Reading **(b)** is the only one that makes the sprint's failure diagnosis sentence
possible. It requires the judge to see doc texts when scoring facts — which today it
does not. The question is: which set of docs is rendered during fact scoring?

---

## Approaches Considered

| Approach                                                                 | Description                                                                                                                                                                                                     | Pros                                                                                                                                                                                                                  | Cons                                                                                                                                                                                                                                         | Effort |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **A — Cite-only attribution (reading a)**                                | Add `supporting_doc_id: str \| None` to `FactVerdict`. Render only cited docs in the per-fact block (already rendered for per-citation). Ask the LLM: "for this fact, which cited doc supports it — or None?"   | No new docs in prompt. Minimal prompt change. LLM already sees cited doc blocks. Simplest strict-schema wiring.                                                                                                       | Does not distinguish "right doc retrieved but uncited" from "right doc never retrieved." Phase 2 root-cause is limited to "cited doc was wrong/missing." Sprint goal is partially met but the retrieval-miss diagnosis is blocked.           | S      |
| **B — Full retrieved-set attribution (reading b)**                       | Render the full `retrieved_docs` list (all chunks joined by doc_id) as a new `RETRIEVED DOCUMENTS` block in the per-fact scoring section. Ask the LLM: "which retrieved doc substantiates this fact — or None?" | Enables the complete root-cause story: `supporting_doc_id is None` = never retrieved; `supporting_doc_id not None but fact absent` = retrieved but answer missed it. Direct discriminator for the sprint's diagnosis. | Larger prompt — up to `k` docs (typically 5–10) rendered per call. Cost grows linearly with retrieved set. Higher hallucination risk on the doc_id field (LLM must pick from a larger menu). Needs a new prompt section and rubric addition. | M      |
| **C — Cited-or-retrieved with two-phase rubric (reading b, restricted)** | Render the full retrieved set but instruct the judge to first check whether any cited doc covers the fact (fast path), then scan uncited retrieved docs only if no cited doc covers it.                         | Keeps the completeness of reading (b) while making the LLM's job easier (clear search order). Prompt is the same size as B but the rubric is more directed.                                                           | Slightly more complex rubric. The judge may not reliably follow the two-phase instruction. In practice the distinction from B is an instruction-engineering detail, not a schema change. Same schema and validation logic as B.              | M      |

---

## Recommended Approach

**Approach B (full retrieved-set attribution)**, with Approach A's cite-only path
treated as an explicit Won't — not because it is wrong but because it does not deliver
the sprint's root-cause diagnostic.

Rationale:

1. **Reading (b) is the only reading that supports the sprint goal.** Sprint success
   criterion 2 requires distinguishing "fact failed, supporting doc was retrieved" from
   "fact failed, supporting doc was never retrieved." That distinction is not resolvable
   if the judge only sees cited docs.

2. **The prompt cost increase is bounded and acceptable.** The retrieved set is already
   passed to `judge()` via the `Judge` Protocol (`retrieved_docs: list[Chunk]`). The
   judge already joins chunks by doc_id for the per-citation block. Rendering the same
   joined texts as an additional block is a prompt addition, not a new API call. At
   `k=5` typical retrieved docs, each ~300 tokens, the added prompt cost is ~1,500
   tokens — well inside the model's context and an acceptable per-call cost increment.

3. **The hallucination guard is mandatory but straightforward.** Validate the emitted
   `supporting_doc_id` against the set of doc_ids from `retrieved_docs`. Any id not in
   that set collapses to `None`. This is a three-line post-processing step; cover it
   with an anchor case in `test_judge_anchor.py`.

4. **Approach C's two-phase rubric is a prompt-engineering improvement that can be
   added without any schema change.** If the judge produces poor attributions in
   cassette tests, the rubric can be refined without touching the schema or the
   validation logic. Start with a single-phase rubric (B) and refine if needed — do
   not prematurely encode instruction-order logic.

**Schema mechanics for `strict` mode:** `supporting_doc_id` must be typed
`str | None` (JSON: `{"type": ["string","null"]}`) on `FactVerdict` in the
`_LLMJudgeVerdict` surface. Under `strict: true`, OpenAI requires every property in
`required` — so `supporting_doc_id` goes in `required` with a nullable type union,
not as an `Optional` default. The Python-side `FactVerdict` uses
`supporting_doc_id: str | None = None` so old records without the field validate
(Pydantic fills `None`). The `_LLMJudgeVerdict` surface inherits from `FactVerdict`
meaning `model_json_schema()` will include `supporting_doc_id` in `required` with the
nullable type — this is the correct strict-compatible shape.

**Non-breaking guarantee:** The `extra="forbid"` on `FactVerdict` is fine — adding a
new field is additive. Old eval records (no `supporting_doc_id`) validate because the
field defaults to `None`. The stub judge emits `FactVerdict(fact=..., verdict="present")`
and must be updated to include `supporting_doc_id=None` — a one-line change.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | Add `supporting_doc_id: str \| None = None` to `FactVerdict` in `schema.py`.                                                                                                                                                                                |
| **Must**   | Verify `_LLMJudgeVerdict.model_json_schema()` emits `supporting_doc_id` in `required` with `{"type": ["string","null"]}` — i.e., the strict-compatible nullable union — not as an optional default-excluded field. Adjust if Pydantic emits it incorrectly. |
| **Must**   | Extend `build_judge_user_prompt` to render the full retrieved set as a named `RETRIEVED DOCUMENTS` block (same per-`doc_id` join logic already used for citation blocks).                                                                                   |
| **Must**   | Extend the judge rubric in `prompt.py` to instruct: "For each gold fact, emit `supporting_doc_id`: the `doc_id` of the retrieved document that most directly substantiates the fact, or `null` if no retrieved document covers it."                         |
| **Must**   | Post-validate `supporting_doc_id` in `OpenAIJudge` after re-validating through `_LLMJudgeVerdict`: if the emitted id is not in the retrieved doc_id set, replace with `None`.                                                                               |
| **Must**   | Update `StubJudge` to emit `supporting_doc_id=None` on every `FactVerdict` (keeps the stub non-breaking and conformant).                                                                                                                                    |
| **Must**   | Add an anchor case to `test_judge_anchor.py`: judge emits a hallucinated `supporting_doc_id` not in the retrieved set → it collapses to `None`.                                                                                                             |
| **Must**   | Add/extend cassette in `test_judge_anchor.py` (or a new cassette file) for the nominal supporting-doc attribution path.                                                                                                                                     |
| **Must**   | `make lint test` green. All changed modules have mirrored test coverage.                                                                                                                                                                                    |
| **Should** | Confirm that `JudgeVerdict` serialisation (used in `records.py` and `report.py`) round-trips `supporting_doc_id=None` without breaking existing JSONL consumers.                                                                                            |
| **Should** | Confirm `eval/aggregate.py` requires no change (it only counts verdicts, not field values).                                                                                                                                                                 |
| **Could**  | Refine the rubric to a two-phase search order (Approach C's instruction) if initial cassette tests show poor attribution accuracy.                                                                                                                          |
| **Could**  | Add `supporting_doc_id` to the judge span `output.value` text rendering in `observability/attributes.py` (only if the change is truly one-liner; otherwise defer to phase 3).                                                                               |
| **Won't**  | Cross-reference `supporting_doc_id` against retrieved doc_ids to produce a root-cause label — that is phase 2's job.                                                                                                                                        |
| **Won't**  | Change any report table or failure-taxonomy rule — those are phase 2 consumers.                                                                                                                                                                             |
| **Won't**  | Surface `supporting_doc_id` as a Phoenix span attribute — that is phase 3.                                                                                                                                                                                  |
| **Won't**  | Add per-fact `supporting_doc_id` to the eval aggregate floats — it is a raw field only; aggregation logic is unchanged.                                                                                                                                     |
| **Won't**  | Use cite-only attribution (Approach A) — it cannot resolve retrieval-miss root cause.                                                                                                                                                                       |
| **Won't**  | Change the public `Judge` Protocol signature — `retrieved_docs` is already there.                                                                                                                                                                           |

---

## Open Questions

1. **How does Pydantic v2 emit the JSON schema for `str | None = None` under
   `extra="forbid"` — is `supporting_doc_id` placed in `required` with a nullable type
   union, or excluded from `required` as a defaulted optional?** OpenAI `strict: true`
   requires all properties in `required`. If Pydantic emits it outside `required` (as
   it might for fields with defaults), the schema will be rejected by OpenAI. The
   `/define` step should pin the exact Pydantic v2 emission behavior (testable with
   `FactVerdict.model_json_schema()`) and specify what override is needed if it is not
   strict-compatible as-is.

2. **Should the retrieved-docs block in the prompt replace or supplement the cited-docs
   block?** Currently the per-citation scoring is keyed to the cited-docs block. If the
   retrieved-docs block is added separately, the prompt has two doc sections (one for
   fact attribution, one for citation scoring). Does rendering docs twice (once in each
   section) confuse the judge, or is the structural separation clear enough? The
   `/define` step should settle the prompt layout.

3. **What is the expected cassette update cost?** The existing `test_judge_anchor.py`
   cassette was recorded against the current prompt. Adding a new `RETRIEVED DOCUMENTS`
   block changes the user-prompt hash, invalidating the existing cassette. The `/define`
   step should decide: re-record the existing cassette (and update the anchor test to
   include `supporting_doc_id` assertions), or add a separate new cassette file for
   the attribution tests while keeping the old cassette as-is (only possible if the old
   prompt is preserved for the old test path — which it is not, since `prompt.py` is
   shared).

4. **How does `supporting_doc_id=None` in the JSONL interact with the bronze-archive
   (`BronzeWriter`)?** The bronze payload is the raw LLM response, not the Pydantic
   model, so it is unaffected. But the gold JSONL (`EvalRecord`) serialises `FactVerdict`
   via `model_dump`. Confirm that `None` values are serialised as JSON `null` (not
   omitted) so old and new records are distinguishable: `null` = "judge said no doc
   covers this" vs. key absent = "old record, field did not exist." If Pydantic omits
   `None` by default in `model_dump`, use `model_dump(exclude_none=False)` or verify
   the existing serialisation path already retains `null`.

---

## Next Step

-> `/define sprint-8/phase-1-faithfulness-schema`
