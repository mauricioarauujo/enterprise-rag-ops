# DEFINE: sprint-8/phase-1-faithfulness-schema — Supporting-Doc Attribution on FactVerdict

**Sprint/Phase:** sprint-8/phase-1-faithfulness-schema | **Date:** 2026-06-14

Approach **B (full retrieved-set attribution, reading (b))** is LOCKED by the user: the
judge picks which retrieved doc substantiates each gold fact, or `None` if none does.
Approach A (cite-only) is a confirmed **Won't**. This phase is the **schema + emission +
persistence half only**; root-cause linkage (phase 2) and Phoenix spans (phase 3) are
explicit Won'ts.

---

## Requirements

### Functional

- **FR-1 — Nullable field on `FactVerdict`.** `FactVerdict` (in `eval/schema.py`) gains
  `supporting_doc_id: str | None = None`: the `doc_id` of the retrieved document that
  most directly substantiates the gold fact, or `None` when no retrieved doc covers it.
  The field is additive — existing `FactVerdict(fact=..., verdict=...)` construction
  stays valid (default `None`).

- **FR-2 — Strict-mode-compatible JSON schema.** `_LLMJudgeVerdict.model_json_schema()`
  (which embeds `FactVerdict` via `per_fact: list[FactVerdict]`) must place
  `supporting_doc_id` in the `required` array of the `FactVerdict` sub-schema with a
  nullable type union `{"type": ["string", "null"]}` — **not** as a defaulted-optional
  field excluded from `required`. OpenAI `strict: true` rejects any property absent from
  `required`. The implementation must inspect the actual emitted schema and apply a
  Pydantic v2 override (see § Notes / FR-2 risk) if the default emission is not
  strict-compatible.

- **FR-3 — Judge emits the field (prompt block).** `build_judge_user_prompt`
  (`eval/prompt.py`) gains a new named **`RETRIEVED DOCUMENTS`** block rendering the full
  retrieved set (all chunks joined per `doc_id`, reusing the existing per-`doc_id` join
  logic), distinct from the existing **`CITED DOCUMENTS`** block. The block is the menu
  the judge picks `supporting_doc_id` from.

- **FR-4 — Rubric instruction.** `build_judge_system_prompt`/`_RUBRIC` (`eval/prompt.py`)
  gains a line instructing: for each gold fact, emit `supporting_doc_id` = the `doc_id`
  from the RETRIEVED DOCUMENTS block that most directly substantiates the fact, or `null`
  if no retrieved document covers it. (Single-phase rubric per Approach B; the two-phase
  Approach C ordering is a Could, not required here.)

- **FR-5 — Hallucination guard (post-validation).** In `OpenAIJudge.judge_with_stats`,
  after re-validating through `_LLMJudgeVerdict`, each emitted `supporting_doc_id` is
  validated against the set of `doc_id`s present in `retrieved_docs`. Any id **not** in
  that set is replaced with `None` before the public `JudgeVerdict` is assembled.

- **FR-6 — `StubJudge` conformance.** `StubJudge.judge` emits
  `supporting_doc_id=None` on every `FactVerdict` it constructs (one-line change),
  keeping the offline-CI path non-breaking and schema-conformant.

- **FR-7 — Persistence round-trips the field.** `EvalRecord.per_fact`
  (`eval/records.py`) already holds `list[FactVerdict] | None`; the new field flows
  through unchanged. JSONL serialisation must emit `supporting_doc_id` as JSON `null`
  (key present with null value) when it is `None`, so a new record's "no supporting doc"
  (`null`) is distinguishable from an old record's "field never existed" (key absent).

### Non-functional

- **NFR-1 — Non-breaking, backward-compatible.** Old eval records lacking the field
  still validate (Pydantic fills `None`). `aggregate.py` is unchanged — it counts
  verdicts (`present`/`contradicted`/`supported`), never reads `supporting_doc_id`; the
  three floats are byte-identical for any pre-existing input. This must be confirmed, not
  assumed.

- **NFR-2 — Offline determinism preserved.** All phase-1 tests run under `make test`
  with no network and no API key, via the existing `FakeOpenAIClient` canned-payload
  pattern (`tests/eval/conftest.py`). No live LLM call in the test path.

- **NFR-3 — Bounded judge-prompt growth / cost.** Approach B grows the judge user prompt
  by the full retrieved set (~+1,500–3,000 input tokens/call at k=10). Measured
  incremental cost for a full 500q×3-model sweep on `gpt-5-nano` (@ $0.05/1M input) is
  ~$0.15–0.28, keeping the total judge bill ~$1 — well under the existing `$5.00`
  `cost_ceiling_usd` guard. **No new cost mechanism is introduced**; the existing
  `cost_ceiling_usd` remains the backstop. The growth is bounded by `k` (the retrieved
  set size) and observed, not unbounded. Phase-1 development itself is ~$0 (cassette /
  fake-client replay); only a one-time cassette re-record (AC-9) spends a few cents live.

- **NFR-4 — Schema-as-SSoT preserved.** No hand-maintained parallel JSON schema string is
  introduced. The strict schema remains `_LLMJudgeVerdict.model_json_schema()`; any FR-2
  override is expressed in the Pydantic model definition, not a separate JSON blob.

---

## Acceptance Criteria

1. **AC-1 (FR-1):** `FactVerdict(fact="x", verdict="present")` constructs with
   `supporting_doc_id is None`; `FactVerdict(fact="x", verdict="present",
supporting_doc_id="doc_a")` round-trips the value. Covered in `tests/eval/test_schema.py`.

2. **AC-2 (FR-2, highest risk):** A test in `tests/eval/test_schema.py` asserts on the
   actual output of `_LLMJudgeVerdict.model_json_schema()`: within the `FactVerdict`
   `$defs` sub-schema, `"supporting_doc_id"` appears in the `required` list **and** its
   property schema is the nullable union (`{"type": ["string", "null"]}`, or the
   equivalent `anyOf` form OpenAI strict accepts). If Pydantic v2's default emission for
   `str | None = None` excludes it from `required` or uses a non-strict shape, the design
   must specify and the test must verify the override (e.g. `Field(json_schema_extra=...)`
   or a `field_serializer`/`model_json_schema` customization) that produces the
   strict-compatible shape. The test fails if the field is strict-incompatible.

3. **AC-3 (FR-3):** After judging, the rendered user prompt
   (`client.calls[0]["messages"][1]["content"]`) contains a `RETRIEVED DOCUMENTS` section
   header **and** a `=== doc <id> ===` block for every retrieved `doc_id`, distinct from
   the existing `CITED DOCUMENTS` section. Asserted in `tests/eval/test_judge_anchor.py`
   (or a sibling test in `tests/eval/`).

4. **AC-4 (FR-4):** The system prompt (`build_judge_system_prompt()`) contains the
   `supporting_doc_id` instruction line (the rubric tells the judge to pick a retrieved
   `doc_id` or `null`). Asserted as a substring in `tests/eval/test_prompt.py` (create if
   absent; mirror existing prompt-construction tests).

5. **AC-5 (FR-5, hallucination guard — anchor case):** With a `FakeOpenAIClient` canned
   payload whose `per_fact` emits a `supporting_doc_id` **not** in the `retrieved_docs`
   set, the returned `JudgeVerdict`'s corresponding `FactVerdict.supporting_doc_id`
   collapses to `None`. A second fact emitting an in-set `doc_id` retains that id
   unchanged. Anchor case in `tests/eval/test_judge_anchor.py`.

6. **AC-6 (FR-6):** `StubJudge.judge(...)` returns a `JudgeVerdict` whose every
   `per_fact` entry has `supporting_doc_id is None`. Asserted in
   `tests/eval/test_stub_judge.py` (create if absent) or the existing stub test.

7. **AC-7 (FR-7, serialisation — null vs absent):** `EvalRecord` containing a
   `FactVerdict(supporting_doc_id=None)`, serialised via the project's persistence path
   (`model_dump` / `model_dump_json` as used by `records.py`/the runner), emits
   `"supporting_doc_id": null` — the key is **present with null**, not omitted. A record
   JSON missing the key entirely still validates back into `EvalRecord` (old-record
   compatibility), and the round-tripped value is `None`. The chosen `model_dump`
   behavior (default, or `exclude_none=False` if needed) is pinned in the test. Covered in
   `tests/eval/test_records.py`.

8. **AC-8 (NFR-1, aggregate unchanged):** `aggregate(per_fact, per_citation)` returns
   byte-identical `(fact_recall, fact_precision, faithfulness_ratio)` whether or not
   `per_fact` entries carry `supporting_doc_id`. Asserted by a regression case in
   `tests/eval/test_aggregate.py` (same input with/without the field → same floats).

9. **AC-9 (cassette / canned-payload re-record):** The new RETRIEVED DOCUMENTS block
   changes the user-prompt text. The judge anchor test uses a **fake-client canned
   `_LLMJudgeVerdict` payload** (`canned_verdict_payload` in `tests/eval/conftest.py`),
   **not** an on-disk VCR cassette — so the re-record cost is: update the canned payload
   to include `supporting_doc_id` values (one in-set, one hallucinated) and update the
   prompt-assertion to expect the new block. No VCR `tests/eval/cassettes/*.yaml` file
   exists for the judge path; none needs re-recording. (Verified: only
   `abstention_info_not_found.yaml` and the generator cassettes exist; the judge anchor
   path is fake-client-based.) If a maintainer later adds a live judge cassette, the
   re-record plan is `VCR_RECORD_MODE` + the documented scrub fixture — out of scope here.

10. **AC-10 (NFR-3, cost note):** The DESIGN/implementation records (in a code comment or
    the PR body) the observed prompt-growth bound (~+1,500–3,000 tokens/call at k=10) and
    confirms no new cost mechanism is added — the `cost_ceiling_usd` guard is unchanged.
    No automated test; this is a documentation acceptance check.

11. **AC-11 (NFR-2, NFR-4 / quality gate):** `make lint test` is green. Every changed
    module (`schema.py`, `prompt.py`, `openai_judge.py`, `stub_judge.py`) has mirrored
    coverage in `tests/eval/`. No new hand-maintained schema string; strict schema is
    still `_LLMJudgeVerdict.model_json_schema()`.

---

## Resolved Open Questions

`AskUserQuestion` was not invoked: the four open questions were resolvable from the
BRAINSTORM lock + SPRINT scope + codebase evidence to their aligned defaults. Each is
flagged below as an assumption for the orchestrator to confirm before `/design`.

- **OQ-1 (strict-mode nullable emission) → resolved into AC-2.** Default: design must
  verify the real `model_json_schema()` and apply a Pydantic v2 override only if the
  emitted shape is strict-incompatible. Treated as the highest-risk item; the AC fails
  closed (test asserts the strict shape). _Assumption:_ the override, if needed, stays
  expressed in the Pydantic model (NFR-4), not a parallel JSON string.

- **OQ-2 (prompt layout — replace vs supplement) → resolved: supplement, two distinct
  sections.** The RETRIEVED DOCUMENTS block is **added separately** from the existing
  CITED DOCUMENTS block (FR-3, AC-3). Rationale: citation scoring is keyed to cited docs
  and must not change; fact attribution needs the full retrieved set. The two sections
  are unambiguous because each carries a distinct header and purpose line. _Assumption:_
  rendering a doc in both sections (when a doc is both cited and retrieved) does not
  confuse the judge — to be validated by cassette accuracy; the Could two-phase rubric
  (Approach C) is the fallback if attribution is poor.

- **OQ-3 (cassette update cost) → resolved into AC-9.** The judge anchor path uses a
  fake-client canned payload, not a VCR cassette, so "re-record" = update the canned
  `_LLMJudgeVerdict` payload + prompt assertion. No `.yaml` cassette to invalidate.

- **OQ-4 (`None` serialised as `null` vs omitted) → resolved into AC-7.** Default: pin
  the `model_dump` path so `supporting_doc_id=None` emits `"supporting_doc_id": null`
  (key present), preserving the new-`null` vs old-`absent` distinction phase 2 relies on.
  Use `exclude_none=False` if the current path would otherwise omit it. _Assumption:_ the
  runner's persistence call does not set `exclude_none=True`; verify in DESIGN.

---

## Clarity Score

| Dimension       | Score | Note                                                                                                                                                                                                                    |
| --------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**     | 3     | Root cause with evidence: failed facts carry no doc attribution, blocking the retrieval-miss diagnosis; codebase confirms `FactVerdict` has no doc field.                                                               |
| **Users**       | 2     | The eval/observability consumer (the harness operator reading the report + phase-2 root-cause linkage) is the named downstream; workflow impact is the diagnosis sentence. Internal-tooling phase, so no end-user role. |
| **Success**     | 3     | 11 measurable, falsifiable ACs; the highest-risk one (AC-2) asserts on real `model_json_schema()` output and fails closed.                                                                                              |
| **Scope**       | 3     | Full MoSCoW inherited from BRAINSTORM with an explicit Won't list (phase-2 linkage, phase-3 spans, Approach A, aggregate changes, Protocol change).                                                                     |
| **Constraints** | 3     | Strict-mode requirement, `extra="forbid"`, offline-CI/no-mock-LLM, schema-as-SSoT, bounded cost vs `cost_ceiling_usd`, null-vs-absent serialisation — all named.                                                        |

**Total: 14/15** — PASS (≥12).

---

## Infrastructure Readiness

| Dependency                                | KB domain                                                           | Specialist        | Status                                                                                                                                                                                                                                                                                 |
| ----------------------------------------- | ------------------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FactVerdict` / `_LLMJudgeVerdict` schema | `rag-eval/concepts/schema-as-ssot.md`                               | (none registered) | Ready — covers two-model split + strict constraints.                                                                                                                                                                                                                                   |
| Per-doc faithfulness rendering            | `rag-eval/concepts/per-doc-faithfulness.md`                         | (none registered) | Ready — per-`doc_id` block convention is the FR-3 model.                                                                                                                                                                                                                               |
| Per-fact judge call wiring                | `rag-eval/patterns/per-fact-judge-call.md`                          | (none registered) | Ready — four-step call pattern is the FR-5 insertion point.                                                                                                                                                                                                                            |
| OpenAI `strict` + nullable union (AC-2)   | `rag-eval/concepts/schema-as-ssot.md` (thin on `["string","null"]`) | (none)            | **Thin but sufficient.** KB documents `required`/`additionalProperties` but not the nullable-union case. No `/new-kb` now — capture as an `/update-kb rag-eval` to `per-fact-judge-call.md` **after** phase 1 confirms the exact Pydantic v2 emission (already planned in BRAINSTORM). |
| Cassette/replay (ADR-0006)                | `tests/conftest.py` `vcr_record`                                    | (none registered) | Ready — but the judge anchor path is fake-client, not VCR (AC-9).                                                                                                                                                                                                                      |
| Pydantic v2 schema emission               | (library docs)                                                      | Context7 MCP      | Use Context7 (`/pydantic/pydantic`) during DESIGN/implement to confirm the v2 `str \| None` `model_json_schema()` emission and the minimal override for AC-2.                                                                                                                          |

No `/new-kb` or `/new-agent` required: the `rag-eval` domain holds. The only KB action is
the post-phase-1 `/update-kb rag-eval` to add the nullable-strict-field note, already
anticipated in BRAINSTORM and SPRINT.

## Next Step

→ `/design sprint-8/phase-1-faithfulness-schema`
