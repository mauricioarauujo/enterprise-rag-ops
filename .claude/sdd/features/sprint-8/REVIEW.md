# Review: sprint-8/phase-3-trace-surfacing — Per-Fact Root-Cause on the Judge Span

**Branch:** `sprint-8/phase-3-trace-surfacing` | **Date:** 2026-06-17 | **Verdict:** ✅ READY

## Summary

Phase 3 surfaces the phase-1/2 per-fact signal onto a single failed trace: each judge-span
`output.value` fact line now carries `[doc: <supporting_doc_id or —>]`, with the phase-2
root-cause label (`retrieval_gap` / `generation_gap`) appended for failed facts. The change
is a 6-line enrichment in the one production file (`attributes.py`), reusing the pure
`classify_fact_gap` leaf — mapper purity, the key set, citation lines, and the zero-lines
guard are all preserved. Lint + 353 tests green; code review found no blocking issues.

**Scope used:** working tree (`git diff HEAD`) — `origin/main...HEAD` is empty (no commits
yet, SDD pre-commit review). No untracked files.

## Mechanical Checks

| Step   | Status | Notes                                                         |
| ------ | ------ | ------------------------------------------------------------- |
| Format | PASS   | pre-commit hook applies; no drift                             |
| Lint   | PASS   | `make lint` clean                                             |
| Tests  | PASS   | 353 passed, 17 deselected (20.4s); 11 in `test_attributes.py` |

## Issues

<details>
<summary>⚠️ Non-blocking — AC-11 test guard is fixture-coupled (test_attributes.py:144-147)</summary>

`test_label_matches_classify_fact_gap_predicate` builds a record of two **failed** facts and
asserts `gap is not None` before checking the label. It satisfies AC-11 (both gap labels are
pinned), but the `gap is not None` guard only holds because the fixture has no present fact.
Optional hardening — make the loop self-describing for mixed records:

```python
if gap is not None:
    assert f"| {gap}]" in line
else:
    assert "|" not in line
```

Not required for correctness; the present-fact-omits-label path is already covered by
`test_present_fact_has_doc_no_label`.

</details>

## Acceptance Criteria

| #     | Criterion                                    | Status | Evidence                                                    |
| ----- | -------------------------------------------- | ------ | ----------------------------------------------------------- |
| AC-1  | doc suffix present (SC-4)                    | ✅     | `test_fact_line_carries_supporting_doc_id`                  |
| AC-2  | `fact: <text> -> <verdict>` prefix preserved | ✅     | `test_..._hydration_present` (exact-string)                 |
| AC-3  | doc suffix symmetric (present facts too)     | ✅     | `test_present_fact_has_doc_no_label`                        |
| AC-4  | generation_gap (absent + contradicted)       | ✅     | `test_failed_fact_generation_gap_{absent,contradicted}`     |
| AC-5  | retrieval_gap (None / out-of-set doc)        | ✅     | `test_failed_fact_retrieval_gap_none_doc`                   |
| AC-6  | present fact omits label                     | ✅     | `test_present_fact_has_doc_no_label`                        |
| AC-7  | `—` em-dash sentinel, never blank/`"None"`   | ✅     | `test_failed_fact_retrieval_gap_none_doc` (U+2014 asserted) |
| AC-8  | zero-lines (None / []) → no output.value     | ✅     | two retained hydration tests                                |
| AC-9  | citation lines byte-for-byte, after facts    | ✅     | `test_..._hydration_present` (exact block)                  |
| AC-10 | mapper purity (no phoenix/otel import)       | ✅     | `test_attributes_module_has_no_phoenix_or_otel_import`      |
| AC-11 | label == `classify_fact_gap` (no reimpl.)    | ✅     | `test_label_matches_classify_fact_gap_predicate` (see ⚠️)   |
| AC-12 | judge key set unchanged                      | ✅     | `test_judge_attrs_key_set_unchanged`                        |
| AC-13 | additive — only `attributes.py` prod diff    | ✅     | diff confirms no schema/records/exporter/ADR change         |
| AC-14 | mirrored offline tests, `__init__.py`        | ✅     | pure mapper, no network/API/cassette                        |
| AC-15 | `make lint test` green                       | ✅     | 353 passed                                                  |

All 15 met.

## KB Staleness

| KB File                                            | What Changed                                                            | Impact                                 | Action taken                                                                                                                                      |
| -------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `observability/concepts/span-attribute-mapping.md` | judge `output.value` fact-line format gained `[doc: … \| <gap>]` suffix | Doc example + prose were stale vs code | **Applied on branch** — example, em-dash/None discipline, and the `classify_fact_gap` import note all updated; verified accurate by code-reviewer |

Swept the rest of the KB for the old `fact: <text> -> <verdict>` format — only
`span-attribute-mapping.md` referenced it (now updated). `rag-eval/quick-reference.md`
mentions `FactVerdict` schema fields, not the render format — not stale.

## ADR

None. DEFINE NFR-2 / AC-13 pin this as additive within ADR-0004's already-decided
observability architecture — no new architectural decision, no new ADR. Confirmed no diff
under `docs/adr/`.

## Suggested Next Steps

1. Commit the phase — code + tests + KB together (one Conventional Commit, e.g.
   `feat(sprint-8/phase-3): surface per-fact supporting_doc_id + root-cause on judge span`).
   The KB update is already applied on this branch (lockstep with the code).
2. Open the PR against `main`.
3. (Optional) Apply the AC-11 test-guard hardening above before committing — 2-line change.
