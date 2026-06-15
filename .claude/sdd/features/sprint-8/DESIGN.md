# DESIGN: sprint-8/phase-1-faithfulness-schema — Supporting-Doc Attribution on FactVerdict

**Sprint/Phase:** sprint-8/phase-1-faithfulness-schema | **Date:** 2026-06-14

> Implement stage runs in **Antigravity / Gemini** against this artifact (AGENTS.md
> § Implement Contract). This DESIGN is the contract — self-contained and precise.

---

## Overview

Approach **B** (full retrieved-set attribution, reading (b)) is LOCKED. This phase is the
**schema + emission + persistence half only** — root-cause linkage (phase 2) and Phoenix
spans (phase 3) are explicit Won'ts.

The change threads an additive, nullable `supporting_doc_id` through the judge verdict:

1. **`FactVerdict`** gains `supporting_doc_id: str | None` — emitted by the LLM under
   `strict: true`, so the field must land in the schema's `required` array with a
   nullable type union (the load-bearing AC-2 decision, resolved below).
2. The judge prompt gains a **`RETRIEVED DOCUMENTS`** block (full retrieved set, per-`doc_id`
   join) that **supplements** the existing **`CITED DOCUMENTS`** block — two distinct
   sections (OQ-2 resolved). It is the menu the judge picks `supporting_doc_id` from.
3. A **hallucination guard** in `OpenAIJudge.judge_with_stats` collapses any emitted
   `supporting_doc_id` not present in the retrieved doc-id set to `None`.
4. **Persistence** round-trips the field as JSON `null` (not omitted) — already true with
   the current `record.model_dump_json()` call (OQ-4 verified, no fix needed).

`aggregate.py` is untouched; old eval records validate unchanged (Pydantic fills `None`).

### Data flow (changed path only)

```
runner → OpenAIJudge.judge_with_stats(retrieved_docs)
           │
           ├─ build doc_text = {doc_id: "\n\n".join(chunk texts)}   ← already exists
           ├─ cited_docs   = [(doc_id, doc_text.get(doc_id)) for doc_id in sources]   ← already exists
           ├─ retrieved_docs_rendered = [(doc_id, doc_text[doc_id]) for doc_id in doc_text]   ← NEW (full set)
           │
           ├─ build_judge_user_prompt(... cited_docs=, retrieved_docs=)   ← NEW param
           │     → CITED DOCUMENTS block      (unchanged)
           │     → RETRIEVED DOCUMENTS block  (NEW)
           │
           ├─ create(... strict json_schema = _LLMJudgeVerdict.model_json_schema())
           ├─ llm_verdict = _LLMJudgeVerdict.model_validate_json(raw)   ← already exists
           ├─ HALLUCINATION GUARD: for fv in llm_verdict.per_fact:       ← NEW
           │     if fv.supporting_doc_id not in {c.doc_id for c in retrieved_docs}: → None
           ├─ aggregate(per_fact, per_citation)   ← unchanged (ignores supporting_doc_id)
           └─ JudgeVerdict(per_fact=…, …)   ← supporting_doc_id flows through inherited
                 → EvalRecord.per_fact → record.model_dump_json() → "supporting_doc_id": null|<id>
```

---

## The AC-2 schema decision (load-bearing — stated concretely)

### Verified Pydantic v2 default emission for `str | None = None`

For a field declared `supporting_doc_id: str | None = None` on a model with
`ConfigDict(extra="forbid")`, Pydantic v2's **default** `model_json_schema()` emits the
`FactVerdict` `$defs` sub-schema as:

```jsonc
"FactVerdict": {
  "additionalProperties": false,
  "properties": {
    "fact": { "type": "string", ... },
    "verdict": { "enum": ["present","absent","contradicted"], "type": "string", ... },
    "supporting_doc_id": {
      "anyOf": [ {"type": "string"}, {"type": "null"} ],   // ← anyOf form, NOT ["string","null"]
      "default": null
    }
  },
  "required": ["fact", "verdict"]                            // ← supporting_doc_id MISSING from required
}
```

This is **NOT strict-compatible**, for two independent reasons:

1. **Field excluded from `required`.** Because the field has a default (`= None`),
   Pydantic v2 omits it from `required`. OpenAI `strict: true` rejects any property absent
   from `required`. The repo's own `test_llm_facing_schema_is_strict_compatible`
   (`tests/eval/test_schema.py:66`) asserts `set(defn["required"]) == set(defn["properties"])`
   — which would **fail** on the default emission. This is the spine of the problem.
2. **`anyOf` nullable form.** OpenAI strict accepts both `{"type":["string","null"]}` and
   the `anyOf` form in current API versions, but the project KB and FR-2 standardize on
   the **explicit type-union `{"type": ["string", "null"]}`**, which is the unambiguous,
   universally-accepted shape. We normalize to it.

There is **no existing strict-mode normalization step** in `openai_judge.py` — the schema
is fed raw (`_LLMJudgeVerdict.model_json_schema()` passed directly). The current models are
strict-compatible only because every field is non-default and non-nullable. Adding a
nullable defaulted field is the first case that breaks the raw-emission assumption.

### The fix — `json_schema_extra` override on the field (NFR-4 preserving)

Express the override **in the Pydantic model definition** (NFR-4: no hand-maintained
parallel JSON string, no `model_json_schema` post-processor). Use a per-field
`json_schema_extra` that overwrites the field's sub-schema with the strict-compatible
nullable union, **and** force the field into `required`.

`json_schema_extra` on a `Field` merges into / overrides that property's schema node, but
it does **not** move the field into the parent's `required` array — Pydantic decides
`required` from the presence of a default. Two clean options; the design selects **Option A**:

**Option A (selected) — drop the Python default, keep nullability via the type, restore
back-compat with `validate_default`/a validator-free nullable.** Declaring the field
_without_ a default would force it into `required` automatically — but it would also break
the additive guarantee (old `FactVerdict(fact=…, verdict=…)` calls and old records lacking
the key would raise). So Option A is **rejected** for breaking FR-1/NFR-1.

**Option B (SELECTED) — keep `= None` for back-compat; override emission via a
`model_json_schema` classmethod hook scoped on `FactVerdict` that (i) rewrites the
`supporting_doc_id` property to `{"type": ["string","null"]}` and (ii) appends it to
`required`.** Pydantic v2 supports overriding `__get_pydantic_json_schema__` on the model
to post-process the field schema in a way that still lives _in the model definition_ (not a
separate JSON blob), satisfying NFR-4. This keeps the Python-side default `None` (FR-1 /
NFR-1 additive guarantee) while emitting the strict shape (FR-2).

**Concrete implementation (FactVerdict in `eval/schema.py`):**

```python
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import GetJsonSchemaHandler
from pydantic_core import CoreSchema


class FactVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str = Field(description="The gold answer-fact being scored.")
    verdict: Literal["present", "absent", "contradicted"] = Field(
        description="Whether the answer states this fact, omits it, or contradicts it.",
    )
    # Additive, nullable (FR-1). Python default keeps old records / old construction valid
    # (NFR-1). The strict-mode shape (required + ["string","null"]) is forced in
    # __get_pydantic_json_schema__ below (FR-2, NFR-4 — override lives in the model).
    supporting_doc_id: str | None = Field(
        default=None,
        description=(
            "The doc_id of the retrieved document that most directly substantiates this "
            "gold fact, or null when no retrieved document covers it."
        ),
    )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> dict[str, Any]:
        schema = handler(core_schema)
        schema = handler.resolve_ref_schema(schema)
        # Strict-mode normalization for the nullable field (OpenAI strict: true):
        #   1. explicit type-union, not Pydantic's default anyOf
        #   2. present in `required` (strict rejects any property absent from required)
        props = schema.get("properties", {})
        if "supporting_doc_id" in props:
            props["supporting_doc_id"] = {
                "type": ["string", "null"],
                "description": props["supporting_doc_id"].get("description", ""),
            }
        required = schema.setdefault("required", [])
        if "supporting_doc_id" not in required:
            required.append("supporting_doc_id")
        return schema
```

> **Implementer note (AC-2 — VERIFIED against installed Pydantic, 2026-06-14):** the hook
> above (`__get_pydantic_json_schema__` with `resolve_ref_schema`) was run against the
> installed Pydantic version in **both** the standalone `FactVerdict.model_json_schema()`
> and the real nested `_LLMJudgeVerdict.model_json_schema()` context (where `FactVerdict`
> lands in `$defs`). Confirmed results:
>
> - Default emission (no hook) **fails** the strict gate: `required == ['fact', 'verdict']`
>   (`supporting_doc_id` excluded) and the prop emits `anyOf`, not the type-union.
> - With the hook, `$defs.FactVerdict` emits `supporting_doc_id` typed
>   `{"type": ["string", "null"]}` **and** present in `required`; both `FactVerdict` and
>   `CitationVerdict` pass `required == properties`; `additionalProperties: false` is
>   preserved; runtime default stays `None` and `model_dump_json()` emits
>   `"supporting_doc_id":null` (so OQ-4's null-vs-absent distinction holds).
>
> Implement the hook as written — no Context7 confirmation needed. AC-2 remains the
> fail-closed gate (the test asserts on the real `_LLMJudgeVerdict.model_json_schema()`
> output). Do **not** introduce a parallel JSON string (NFR-4).

This preserves the existing `test_llm_facing_schema_is_strict_compatible` invariant
(`required == properties` for every `$def`) because `supporting_doc_id` is now in both.

### AC-2 test assertion (in `tests/eval/test_schema.py`)

```python
def test_supporting_doc_id_is_strict_compatible_nullable():
    schema = _LLMJudgeVerdict.model_json_schema()
    fv = schema["$defs"]["FactVerdict"]
    assert "supporting_doc_id" in fv["required"]              # strict requires it
    assert fv["properties"]["supporting_doc_id"]["type"] == ["string", "null"]
    # existing invariant still holds: every property is required
    assert set(fv["required"]) == set(fv["properties"])
```

---

## Component-by-component design

### 1. `eval/schema.py` — `FactVerdict` (FR-1, FR-2)

- Add `supporting_doc_id: str | None = Field(default=None, description=…)`.
- Add the `__get_pydantic_json_schema__` classmethod (above) to force the strict shape.
- `_LLMJudgeVerdict.per_fact: list[FactVerdict]` and `JudgeVerdict.per_fact:
list[FactVerdict]` inherit the field with **zero code change** — both reference
  `FactVerdict` by type, so the new field and its strict schema flow through automatically.
- `extra="forbid"` is still satisfied: adding a _declared_ field is not an "extra" field.
- Update the class docstring (currently says "an optional `supporting_doc_id` is a later
  additive … not present now") to reflect that it now exists.

### 2. `eval/prompt.py` — `build_judge_user_prompt` + rubric (FR-3, FR-4)

**New signature** — add a `retrieved_docs` param alongside the existing `cited_docs`
(OQ-2: supplement, do not replace):

```python
def build_judge_user_prompt(
    question: str,
    answer: str,
    answer_facts: list[str],
    cited_docs: list[tuple[str, str | None]],
    retrieved_docs: list[tuple[str, str]],   # NEW — (doc_id, text), full retrieved set
) -> str:
```

- Reuse the existing per-`doc_id` `=== doc {doc_id} ===` block-render logic for the new
  block (extract a tiny local helper or inline a second loop — implementer's choice;
  the retrieved block never has `None` text since it is built from `doc_text` directly).
- **Block placement (exact, so the implementer does not guess):** the new
  `RETRIEVED DOCUMENTS` block is appended **after** the existing `CITED DOCUMENTS` block.
  Final user-prompt section order:

  ```
  QUESTION:
  {question}

  ANSWER UNDER JUDGMENT:
  {answer}

  GOLD FACTS (one per_fact verdict each, in order):
  {facts_block}

  CITED DOCUMENTS (one per_citation verdict each, in order):
  {cited_block}

  RETRIEVED DOCUMENTS (the full candidate set; pick supporting_doc_id from these doc ids):
  {retrieved_block}
  ```

  `retrieved_block` is `"\n\n".join(f"=== doc {doc_id} ===\n{text}" for doc_id, text in retrieved_docs)`.

- **`_RUBRIC` addition** — append one block to the existing rubric instructing per-fact
  attribution (FR-4). Append after the existing per_fact bullet list, before the
  per_citation block, or as a trailing sentence — exact text:

  ```
  For EACH gold fact also emit supporting_doc_id: the doc_id from the RETRIEVED
  DOCUMENTS block whose text most directly substantiates that fact, or null if no
  retrieved document covers it. Pick only a doc_id shown in RETRIEVED DOCUMENTS.
  ```

  This line must appear in `build_judge_system_prompt()` output (AC-4 asserts the
  substring `supporting_doc_id` in the system prompt). Note the embedded schema in the
  system prompt now _also_ contains `supporting_doc_id` (from `_LLMJudgeVerdict.model_json_schema()`),
  which is an additional natural anchor for AC-4.

### 3. `eval/openai_judge.py` — wiring + hallucination guard (FR-3, FR-5)

- **Build the retrieved-docs block input** right after the existing `doc_text` map (line
  ~93). `doc_text` is already the per-`doc_id` joined text of the full retrieved set, so:

  ```python
  retrieved_docs_rendered = [(doc_id, text) for doc_id, text in doc_text.items()]
  ```

  (Iteration order of `doc_text` is insertion order = retrieval order, since it is built
  from a `defaultdict` populated by iterating `retrieved_docs`. Deterministic — good for
  byte-identical prompts.)

- **Pass it to the prompt builder:**

  ```python
  user_prompt = build_judge_user_prompt(
      question=question,
      answer=answer_with_sources.answer,
      answer_facts=answer_facts,
      cited_docs=cited_docs,
      retrieved_docs=retrieved_docs_rendered,   # NEW
  )
  ```

- **Hallucination guard (FR-5)** — sits **immediately after** the existing re-validation
  (`llm_verdict = _LLMJudgeVerdict.model_validate_json(raw)`, line ~126) and **before**
  `aggregate(...)`:

  ```python
  retrieved_ids = {c.doc_id for c in retrieved_docs}
  for fv in llm_verdict.per_fact:
      if fv.supporting_doc_id is not None and fv.supporting_doc_id not in retrieved_ids:
          fv.supporting_doc_id = None
  ```

  Mutating the validated `FactVerdict` in place is fine (Pydantic v2 models are mutable by
  default; `extra="forbid"` only constrains construction, not assignment to a declared
  field). The guarded `per_fact` then flows unchanged into `JudgeVerdict(per_fact=…)`.

- **Add an AC-10 cost-note comment** near the prompt build: the `RETRIEVED DOCUMENTS` block
  grows the judge user prompt by ~+1,500–3,000 input tokens/call at k=10; no new cost
  mechanism — the existing `cost_ceiling_usd` guard is the unchanged backstop.

### 4. `eval/stub_judge.py` — conformance (FR-6)

One-line change in `StubJudge.judge`:

```python
per_fact = [
    FactVerdict(fact=fact, verdict="present", supporting_doc_id=None)
    for fact in answer_facts
]
```

(Explicit `supporting_doc_id=None` documents intent; the default would also produce `None`.)

### 5. `eval/records.py` / `eval/runner.py` — persistence (FR-7, OQ-4)

- **No code change.** `EvalRecord.per_fact: list[FactVerdict] | None` already holds the new
  field via the `FactVerdict` type. The runner persists with `record.model_dump_json()`
  (`runner.py:432`) — **verified: no `exclude_none=True`**. Pydantic v2's
  `model_dump_json()` defaults to `exclude_none=False`, so `supporting_doc_id=None`
  serialises as `"supporting_doc_id": null` (key present), distinguishable from an old
  record's absent key. OQ-4 is resolved with **no fix required**.
- `StubJudge.judge_with_stats` builds `raw_call.response` via `fv.model_dump()` (lines
  62–67) — the new field flows through automatically; no change.

### 6. `eval/aggregate.py` — unchanged (NFR-1)

`aggregate` reads only `.verdict` on facts and citations; it never touches
`supporting_doc_id`. Byte-identical floats for any pre-existing input. Confirmed by code
read (`aggregate.py:30–41`). AC-8 adds a regression test, no source change.

---

## File Manifest

| File                                          | Change                                                                                                                                    | New/Modified | Mirrored test                        | Phase order     |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------ | --------------- |
| `src/enterprise_rag_ops/eval/schema.py`       | Add `supporting_doc_id` to `FactVerdict` + `__get_pydantic_json_schema__` strict-shape hook                                               | Modified     | `tests/eval/test_schema.py`          | 1 (core schema) |
| `src/enterprise_rag_ops/eval/prompt.py`       | `build_judge_user_prompt` gains `retrieved_docs` param + `RETRIEVED DOCUMENTS` block; `_RUBRIC` gains the `supporting_doc_id` instruction | Modified     | `tests/eval/test_prompt.py`          | 2 (core logic)  |
| `src/enterprise_rag_ops/eval/openai_judge.py` | Build retrieved-docs block input; pass to prompt; post-validation hallucination guard; cost-note comment                                  | Modified     | `tests/eval/test_judge_anchor.py`    | 3 (core logic)  |
| `src/enterprise_rag_ops/eval/stub_judge.py`   | One-line: emit `supporting_doc_id=None`                                                                                                   | Modified     | `tests/eval/test_judge_contract.py`  | 4 (core logic)  |
| `src/enterprise_rag_ops/eval/records.py`      | None (field flows through `FactVerdict` type)                                                                                             | Unchanged    | `tests/eval/test_records.py`         | —               |
| `src/enterprise_rag_ops/eval/runner.py`       | None (`model_dump_json()` already emits null; verified no `exclude_none`)                                                                 | Unchanged    | (covered by test_records round-trip) | —               |
| `src/enterprise_rag_ops/eval/aggregate.py`    | None (never reads the field)                                                                                                              | Unchanged    | `tests/eval/test_aggregate.py`       | —               |
| `tests/eval/test_schema.py`                   | AC-1 (construct with/without field), AC-2 (strict-shape assertion on real `model_json_schema()`)                                          | Modified     | —                                    | 6 (tests)       |
| `tests/eval/conftest.py`                      | Update `canned_verdict_payload` to include `supporting_doc_id` (one in-set `doc_real`, one hallucinated `gd_hallucinated`)                | Modified     | —                                    | 6 (tests)       |
| `tests/eval/test_judge_anchor.py`             | AC-3 (RETRIEVED DOCUMENTS block + per-doc rendering, distinct from CITED), AC-5 (hallucination-guard collapse + in-set retention)         | Modified     | —                                    | 6 (tests)       |
| `tests/eval/test_prompt.py`                   | AC-3/AC-4 (new param call; RETRIEVED block present; rubric `supporting_doc_id` line in system prompt)                                     | Modified     | —                                    | 6 (tests)       |
| `tests/eval/test_judge_contract.py`           | AC-6 (StubJudge emits `supporting_doc_id is None` on every per_fact)                                                                      | Modified     | —                                    | 6 (tests)       |
| `tests/eval/test_records.py`                  | AC-7 (null-not-absent serialisation; old-record-without-key still validates → None)                                                       | Modified     | —                                    | 6 (tests)       |
| `tests/eval/test_aggregate.py`                | AC-8 (same floats with/without the field)                                                                                                 | Modified     | —                                    | 6 (tests)       |

**No ADR.** SPRINT.md states no new ADR is anticipated; the field was pre-designed into the
schema-as-SSoT pattern. The strict-nullable emission is an implementation detail of an
already-decided architecture, not a new architectural decision.

---

## Implementation Phases (ordered per the convention)

1. **Data schema / dataset loading** — n/a (no dataset change).
2. **Config** — n/a (NFR-3: no new cost mechanism; `cost_ceiling_usd` unchanged).
3. **Core module logic (`src/`)**, in dependency order:
   1. `eval/schema.py` — `FactVerdict` field + strict-shape hook (everything else depends on it).
   2. `eval/prompt.py` — `RETRIEVED DOCUMENTS` block + rubric line.
   3. `eval/openai_judge.py` — wire the block + hallucination guard.
   4. `eval/stub_judge.py` — one-line conformance.
4. **Eval harness wiring (`eval/`)** — `records.py` / `runner.py` confirmed unchanged
   (persistence already correct).
5. **Observability hooks** — n/a (phase-3 Won't; no `observability/` change).
6. **Tests** — `test_schema.py` (AC-1, AC-2), `conftest.py` canned payload (AC-9),
   `test_judge_anchor.py` (AC-3, AC-5), `test_prompt.py` (AC-3, AC-4),
   `test_judge_contract.py` (AC-6), `test_records.py` (AC-7), `test_aggregate.py` (AC-8).
7. **Docs + ADR** — none (no ADR; AC-10 cost note is a code comment + PR body).

**Validate smallest-first:** `uv run pytest -k "schema or prompt or judge_anchor"` →
then `make lint test` (AC-11). Eval-path tests use the existing `FakeOpenAIClient` +
canned-payload double — **not** a VCR cassette for the judge path (AC-9; no judge `.yaml`
cassette exists).

---

## Infrastructure Gaps

| Gap Type           | Area                            | Detail                                                                                                                                                                                                                                                                | Recommendation                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------ | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Missing domain     | —                               | None. The `rag-eval` domain covers schema-as-SSoT, per-doc faithfulness, the per-fact judge call, and offline-CI testing.                                                                                                                                             | —                                                                                                                                                                                                                                                                                                                                                                                                            |
| Missing concept    | `rag-eval` (thin, not blocking) | The KB documents `required` + `additionalProperties:false` for strict mode but **not** the `str \| None` nullable-union emission case (`{"type":["string","null"]}` + force-into-`required` via `__get_pydantic_json_schema__`). DEFINE/BRAINSTORM already flag this. | **Post-phase-1** `/update-kb rag-eval` → add the nullable-strict-field note to `patterns/per-fact-judge-call.md` (or `concepts/schema-as-ssot.md`), once phase 1 confirms the exact Pydantic v2 hook. Also add the offline-CI judge test-double note (fake-client canned payload, not VCR, for the judge path) to `patterns/offline-ci-judge.md`. Not blocking — do it after the code confirms the emission. |
| Missing specialist | —                               | None. No specialist agent registered for `rag-eval`; phase is a direct-implement (small, surgical, single-domain).                                                                                                                                                    | —                                                                                                                                                                                                                                                                                                                                                                                                            |

**Net: no `/new-kb`, no `/new-agent` required.** Two `/update-kb rag-eval` items are
deferred to **after** phase 1 lands (capture-the-confirmed-pattern, not a blocker).

---

## Consistency Check

**Verdict: ✅ CONSISTENT** (cross-check of DEFINE ↔ DESIGN + AGENTS.md constitution + KB).
Non-trivial phase (4 src modules + 6 test files), so the full six-pass review was run.

| ID  | Severity | Pass               | Location                                         | Finding                                                                                                                                                                                 | Suggested fix                                                                                                                                                                                                                   |
| --- | -------- | ------------------ | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | LOW      | Ambiguity          | DESIGN §2 prompt rubric                          | DEFINE FR-4 leaves the rubric line's exact placement open ("gains a line"); DESIGN pins exact text + placement (after per_fact bullets).                                                | Resolved in DESIGN; no DEFINE edit.                                                                                                                                                                                             |
| C-2 | LOW      | Underspecification | DESIGN AC-2 hook signature                       | The precise Pydantic v2 hook (`__get_pydantic_json_schema__` vs `Field(json_schema_extra=)`) depends on the installed version; DESIGN selects the hook but flags Context7 confirmation. | AC-2 is fail-closed (asserts real `model_json_schema()`); implementer confirms via Context7. Acceptable — the _outcome_ (required + type-union) is pinned, only the mechanism is version-sensitive.                             |
| C-3 | LOW      | Coverage           | conftest `gd_unrelated` vs new `gd_hallucinated` | AC-5 needs a doc_id NOT in `retrieved_docs`; the existing fixtures' `sample_chunks` are `doc_real` + `gd_unrelated`, both in-set. The hallucinated id must be a third, NOT-in-set id.   | DESIGN names `gd_hallucinated` (not in `sample_chunks`) for the canned payload's collapse case; `doc_real` (in-set) for the retention case. Implementer must not reuse `gd_unrelated` as the hallucinated id (it IS retrieved). |

No CRITICAL/HIGH findings. Constitution alignment (pass 4): the change is minimal-scope
and additive, the seam (`Judge` Protocol) is unchanged (no speculative seam), no
stranger-test leak, conventions honoured (mirrored tests, no LLM mock — fake-client double).
Coverage (pass 5): all 11 ACs map to ≥1 manifest entry (AC-1/2→schema, AC-3→prompt+anchor,
AC-4→prompt, AC-5→anchor, AC-6→judge_contract, AC-7→records, AC-8→aggregate, AC-9→conftest,
AC-10→openai_judge comment+PR, AC-11→`make lint test`). No DEFINE requirement is unmapped.

---

## Risks & Trade-offs

- **AC-2 is the spine and the only real risk.** If the installed Pydantic v2 version emits
  a different shape than documented, the `__get_pydantic_json_schema__` hook may need a
  different signature (e.g. `resolve_ref_schema` is required because `FactVerdict` appears
  under `$defs` as a `$ref` — the handler must resolve the ref before mutating, or the
  mutation hits the wrong node). **Mitigation:** AC-2 fails closed against the real schema;
  confirm the hook via Context7 (`/pydantic/pydantic`) before declaring done. This is an
  implementation detail of a decided pattern — **not** an ADR.
- **Hallucination-guard mutation.** Mutating the re-validated `FactVerdict` in place
  (rather than rebuilding) is simplest and safe (mutable model, declared field). The
  alternative — rebuild via `model_copy(update=…)` — is more defensive but unnecessary;
  the in-place guard is covered by AC-5.
- **Doc rendered twice (cited + retrieved).** A doc that is both cited and retrieved appears
  in both blocks (OQ-2 accepted this; the distinct headers disambiguate). Attribution
  quality under this duplication is validated only by a live cassette run, out of scope
  here; the Approach-C two-phase rubric is the documented fallback (a Could) if attribution
  is poor — no schema change needed to adopt it later.
- **Prompt-token growth (NFR-3).** Bounded by `k`; ~+1,500–3,000 tokens/call at k=10. No new
  cost mechanism; `cost_ceiling_usd` is the unchanged backstop. Documentation-only (AC-10).

---

## Next Step

→ `/implement sprint-8/phase-1-faithfulness-schema` — runs in **Antigravity / Gemini**
(AGENTS.md § Implement Contract); build from this DESIGN + DEFINE acceptance criteria, on
branch `sprint-8/phase-1-faithfulness-schema`. **Confirm AC-2 against the live
`_LLMJudgeVerdict.model_json_schema()` first** (Context7 `/pydantic/pydantic`) — it is the
fail-closed gate. No infrastructure gaps block implementation; the two `/update-kb rag-eval`
items are deferred to after the phase lands.
