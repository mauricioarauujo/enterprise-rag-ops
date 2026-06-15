# Review: sprint-8/phase-1-faithfulness-schema — Supporting-Doc Attribution on FactVerdict

**Branch:** `sprint-8/phase-1-faithfulness-schema` | **Date:** 2026-06-14 | **Verdict:** ✅ READY

## Summary

Adds an additive, nullable `supporting_doc_id` to `FactVerdict` so the judge attributes
each gold fact to the retrieved doc that substantiates it (or `None`). The strict-mode
JSON-schema shape is forced via a `__get_pydantic_json_schema__` hook, the judge prompt
gains a distinct `RETRIEVED DOCUMENTS` menu block, and a post-validation hallucination
guard collapses any out-of-set id to `None`. Clean, fully test-covered, backward-compatible.
No blocking issues from either the mechanical gate or independent review.

## Scope

`origin/main...HEAD` is empty (pre-commit SDD flow). Reviewed the **working-tree** scope:
`git diff HEAD` over 4 `src/` files + 7 `tests/` files; SDD artifacts are the only untracked
addition.

## Mechanical Checks

| Step   | Status | Notes                                       |
| ------ | ------ | ------------------------------------------- |
| Format | PASS   | `ruff format --check` — 135 files formatted |
| Lint   | PASS   | `ruff check src tests` — all checks passed  |
| Tests  | PASS   | 331 passed, 17 deselected (`make test`)     |

## Issues

<details>
<summary>⚠️ Empty <code>RETRIEVED DOCUMENTS</code> block when <code>retrieved_docs=[]</code> (non-blocking)</summary>

`src/enterprise_rag_ops/eval/prompt.py:85-95` — with an empty retrieved set the block
renders its header and a blank body, sending the judge a "pick a doc_id" instruction with
no candidates. The guard collapses everything to `None` anyway, so it is not a correctness
bug, and the production retriever returns `k` results unless it abstains. Optional fix:
conditionally append the block only when `retrieved_docs` is non-empty, or document the
empty-body intent in the docstring. Not required for this phase.

</details>

<details>
<summary>⚠️ <code>__get_pydantic_json_schema__</code> mutates the resolved <code>props</code> dict in place (non-blocking)</summary>

`src/enterprise_rag_ops/eval/schema.py:70-78` — the in-place mutation is correct because
Pydantic v2's `resolve_ref_schema` returns a fresh schema per `model_json_schema()` call
(no cross-call caching), and AC-2 verifies the emitted shape fails closed. Purely a
defensive note for whoever next touches the hook; no change needed.

</details>

## Acceptance Criteria

| AC    | Requirement                                                 | Status | Evidence                                                                                                    |
| ----- | ----------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------- |
| AC-1  | Additive nullable field, default `None`                     | ✅ MET | `test_schema.py::test_fact_verdict_supporting_doc_id_additive_default_none`                                 |
| AC-2  | Strict shape: in `required` + `["string","null"]`           | ✅ MET | `test_schema.py::test_supporting_doc_id_is_strict_compatible_nullable` (asserts real `model_json_schema()`) |
| AC-3  | `RETRIEVED DOCUMENTS` block, distinct from CITED            | ✅ MET | `test_prompt.py`, `test_judge_anchor.py`                                                                    |
| AC-4  | Rubric instruction line in system prompt                    | ✅ MET | `test_prompt.py::test_system_prompt_contains_supporting_doc_id_rubric_line`                                 |
| AC-5  | Hallucination guard collapses out-of-set id                 | ✅ MET | `test_judge_anchor.py::test_hallucination_guard_collapses_out_of_set_doc_id`                                |
| AC-6  | `StubJudge` emits `None`                                    | ✅ MET | `test_judge_contract.py::test_stub_judge_emits_none_supporting_doc_id`                                      |
| AC-7  | Serialises as explicit `null`, old records validate         | ✅ MET | `test_records.py::test_supporting_doc_id_serialises_null_not_absent`                                        |
| AC-8  | `aggregate` byte-identical with/without field               | ✅ MET | `test_aggregate.py::test_supporting_doc_id_does_not_affect_aggregates`                                      |
| AC-9  | Canned payload re-recorded (no VCR cassette)                | ✅ MET | `conftest.py::canned_verdict_payload` updated, in-set + hallucinated ids                                    |
| AC-10 | Cost note recorded, no new cost mechanism                   | ✅ MET | Comment at `openai_judge.py:95-98`                                                                          |
| AC-11 | `make lint test` green, mirrored coverage, no schema string | ✅ MET | All `src/` changes mirrored in `tests/eval/`                                                                |

## KB Staleness

| KB File                                    | What Changed                                                                                                                                                                                                                                                            | Impact                                             | Action                                                                                                                                                                         |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `rag-eval/patterns/per-fact-judge-call.md` | The OpenAI `strict: true` nullable field now requires a `__get_pydantic_json_schema__` override emitting `{"type": ["string","null"]}` + forced `required` membership. KB currently documents `required`/`additionalProperties` but is thin on the nullable-union case. | Future nullable strict fields will re-derive this. | `/update-kb rag-eval` — add the nullable-strict-union override note (already anticipated in DEFINE § Infra Readiness; deferred to after phase-1 confirmed the exact emission). |

## Suggested Next Steps

1. Commit the phase (Conventional Commits, e.g. `feat(sprint-8/phase-1): per-fact supporting_doc_id attribution`) and open the PR.
2. Run `/update-kb rag-eval` to capture the strict-mode nullable-union override in `per-fact-judge-call.md` — the one knowledge item this phase surfaced.
3. Proceed to phase-2 (root-cause linkage) once merged.
