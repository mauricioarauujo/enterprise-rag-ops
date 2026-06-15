# SPRINT 8: Per-Fact Root-Cause Attribution

**Sprint:** sprint-8 | **Date:** 2026-06-14 | **Status:** active

## Goal

Today the per-fact judge reports _that_ a fact failed, but not _which_ document it was
judged against — so root-cause analysis stops at "the answer was wrong." This sprint
threads an additive `supporting_doc_id` through the judge verdict, then uses it to turn a
failed fact into a diagnosis: "this fact failed because its supporting doc was never
retrieved." The deliverable is the eval→diagnosis linkage made concrete in the report,
the failure taxonomy, and the trace.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                     | Slug                          |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| 1     | Add optional `supporting_doc_id` to `FactVerdict` (LLM-facing surface), emit it from the judge, persist it in the eval record — additive, non-breaking.                    | `phase-1-faithfulness-schema` |
| 2     | Cross-reference each failed fact's `supporting_doc_id` against the retrieved doc ids to attribute root cause; surface it in the report and feed the failure-mode taxonomy. | `phase-2-root-cause-linkage`  |
| 3     | Surface the per-fact supporting doc on the judge span so a single failed trace explains its own root cause in Phoenix.                                                     | `phase-3-trace-surfacing`     |

Phase 3 is the thinnest and is cut first if the budget runs tight — phases 1–2 carry the
core signal.

## Sprint-Wide Knowledge Plan

Two kinds of pre-work, keyed to each phase's decision point — research lands _before_ a
phase's brainstorm/ADR, KB work lands _after_ its ADR:

| Knowledge area                              | Kind (research / KB / tech-agnostic) | Action                                                                                              | Timing              |
| ------------------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------- | ------------------- |
| Judge verdict schema + per-doc faithfulness | KB (already covered)                 | None — `rag-eval/concepts/per-doc-faithfulness` + `schema-as-ssot` hold; the field was pre-designed | Read before phase 1 |
| Failure-mode taxonomy extension             | KB (already covered)                 | None during the sprint; `update-kb observability` (failure-taxonomy) _after_ phase 2 lands          | After phase 2       |
| Phoenix judge-span attribute mapping        | KB (already covered)                 | None — `observability/span-attribute-mapping` holds; `update-kb` only if the mapping changes        | After phase 3       |

No external research and no new ADR are anticipated: the change is additive within an
already-decided architecture (the schema was explicitly designed to accept this field).
If phase 2's taxonomy extension turns out to redefine a failure label rather than refine
one, escalate to an ADR-0008 amendment at that phase's `/brainstorm`.

## Success Criteria

1. `FactVerdict` carries an optional `supporting_doc_id`; the judge emits it; the schema
   stays closed (`extra="forbid"`, OpenAI `strict`-compatible) and the field is
   non-breaking (old records and the stub judge still validate).
2. The eval report distinguishes "fact failed, supporting doc was retrieved" from "fact
   failed, supporting doc was never retrieved" for at least one worked category.
3. The failure-mode taxonomy can attribute a retrieval-miss root cause using the new
   field, not just answer-level aggregates.
4. A failed trace in Phoenix shows, per fact, the doc it was judged against (phase 3).
5. `make lint test` green; every new/changed module has a mirrored test; eval-path tests
   use the cassette/replay pattern (no mocked LLM).

## Risks

- **Judge reliability of the new field** — the LLM must emit a doc id that actually
  appears in the provided context, not a hallucinated one. Mitigation: validate the
  emitted `supporting_doc_id` against the retrieved/cited doc ids; treat an out-of-set id
  as `None`, and cover it with an anchor case.
- **Scope creep into the taxonomy** — phase 2 could balloon into a taxonomy redesign.
  Mitigation: refine existing labels with the finer signal; defer any new label to an ADR.
- **Tight budget** — phase 3 (Phoenix) is the cut line; phases 1–2 must be self-contained
  so the sprint delivers the eval→diagnosis signal even if 3 is dropped.
