# Review: sprint-6/phase-17-qa-legibility — Question + Answer Legibility (No Re-run)

**Branch:** `sprint-6/phase-17-qa-legibility` | **Date:** 2026-06-02 | **Verdict:** ✅ READY

## Summary

Lights up the two OpenInference Info-tab keys that were unset — `output.value` (the generated
answer, always-on in the pure mapper) and `input.value` (the gold question, opt-in via
`--enrich-from-questions` at the CLI/exporter boundary) — split by data origin so the pure
mapper stays import-light. A direct mirror of the shipped Phase 16 `--enrich-from-index`
boundary pattern. Lint clean, 279 tests pass, all 8 ACs covered, no blocking issues.

## Mechanical Checks

| Step   | Status | Notes                                        |
| ------ | ------ | -------------------------------------------- |
| Format | PASS   | pre-commit `make format` ran clean on commit |
| Lint   | PASS   | `ruff check src tests` — all checks passed   |
| Tests  | PASS   | 279 passed, 17 deselected in ~20s            |

## Issues

<details>
<summary>⚠️ Function-local imports in the AC-5 test — <code>test_exporter.py</code> (<code>test_p17_ac5_*</code>)</summary>

`import inspect` and `from enterprise_rag_ops.observability import attributes as attrs_mod`
live inside the test body rather than the module import block.

**Assessment:** intentional and consistent — the phase-16 sibling `test_ac5_*` uses the same
local-import idiom for introspection/purity tests (keeps the module-under-test import
self-contained). Fixing only phase-17 would make it _inconsistent_ with phase-16. **Recommend
leaving as-is** for file-wide consistency; if it's bothersome, hoist both in a separate
test-cleanup pass, not here. Non-blocking, test passes either way.

</details>

## Acceptance Criteria

| AC   | Requirement                                                                         | Test                                                                                 | Status |
| ---- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ------ |
| AC-1 | Default = today + answer `output.value`, no question                                | `test_p17_ac1_default_answer_on_no_question`                                         | ✅     |
| AC-2 | Question hydration with a fake lookup → chain `input.value`                         | `test_p17_ac2_question_hydration_with_fake_lookup`                                   | ✅     |
| AC-3 | Answer always-on without any lookup                                                 | `test_p17_ac3_answer_always_on_without_lookup`                                       | ✅     |
| AC-4 | Missing question_id → omit + warn, no crash                                         | `test_p17_ac4_missing_question_id_omit_and_warn`                                     | ✅     |
| AC-5 | Mapper purity: emits `output.value`, not `input.value`; signature/imports unchanged | `test_p17_ac5_mapper_emits_output_value_not_input_value`                             | ✅     |
| AC-6 | Offline — no gold file read, content from in-memory map                             | `test_p17_ac6_offline_no_gold_file`                                                  | ✅     |
| AC-7 | CLI wires the gold map (patched `load_questions`); `--help` lists flag              | `test_p17_ac7_cli_wires_question_map_only_with_flag`, `test_p17_ac7_help_lists_flag` | ✅     |
| AC-8 | Dry-run skips the gold load                                                         | `test_p17_ac8_dry_run_skips_gold_load`                                               | ✅     |

**Reviewer-confirmed correctness:** the boundary mutation sets `span_attrs["chain"]["input.value"]`
**before** `sink.start_span(... attributes=span_attrs["chain"])` opens (so the attrs are
captured); missing-id is warn-and-skip (no empty string, no raise); the `and not args.dry_run`
guard correctly skips `load_questions` on dry-run; `attributes.py` imports nothing new. **No
phase-16 test was shadowed** — the `test_p17_` prefix keeps all `test_ac1..test_ac8` intact.

## KB Staleness

The `output.value` (generation) and `input.value` (chain) keys are now live, but the
`span-attribute-mapping` concept tables don't list them yet. Per the Sprint-Wide Knowledge
Plan, `/update-kb observability` is **deferred to after impl** (lands once phase 17 + phase 19
are in) — so this is a planned follow-up, not a review gap.

| KB File                                                                                             | What Changed                                                                                                                               | Impact                                                          | Action                                                                                                                                                                                    |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `observability/concepts/span-attribute-mapping.md` (Chain Span table, ~L12; Generation table, ~L44) | Chain span now carries `input.value`/`input.mime_type` (opt-in); generation span now carries `output.value`/`output.mime_type` (always-on) | Reader doesn't see the new Info-tab keys                        | `/update-kb observability` — add `input.value`/`output.value` rows; note answer is always-on, question opt-in. Deferred per plan (also refresh after phase 19 for judge/generation-input) |
| `observability/concepts/span-tree-shape.md` (L29 generation row)                                    | The generation span's "answer generation call" now surfaces the answer text via `output.value`                                             | Minor — tree-shape note could mention the answer is now legible | Fold into the same deferred `/update-kb observability`                                                                                                                                    |

## ADR

None. Confirmed in DEFINE — the coupling is a stdlib `Mapping[str, str]` passed at the boundary
(below the sprint "ADR only if non-trivial" bar; same call as Phase 16 OQ-5).

## Suggested Next Steps

1. **Open the PR** for `sprint-6/phase-17-qa-legibility` (verdict ✅ READY; the one nit is
   optional and best left for file-wide consistency).
2. **Optional manual check** — `make trace-up` then `rag-export-traces --enrich-from-questions`,
   open a failed trace, confirm the chain span Info tab shows the question and the generation
   span shows the answer (the symptom from the earlier Phoenix screenshots).
3. **Next phase** — `/brainstorm sprint-6/phase-18-evalrecord-reasoning` (the schema + ADR-0010
   decision; weigh the bronze raw-payload capture per `docs/planning/sprint-6-raw-payload-note.md`).
4. **After phase 19** — run the deferred `/update-kb observability` to record all the now-live
   Info-tab keys in one pass.
