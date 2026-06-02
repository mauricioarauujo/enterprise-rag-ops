# Review: sprint-5/phase-16-phoenix-enrichment — Phoenix Trace Enrichment

**Branch:** `sprint-5/phase-16-phoenix-enrichment` | **Date:** 2026-06-02 | **Verdict:** ✅ READY

## Summary

`--enrich-from-index` activates the long-reserved FR-12 seam: `rag-export-traces` builds a
`{doc_id: text}` map from `corpus.jsonl` once at the CLI boundary and the exporter hydrates
`retrieval.documents.{i}.document.content` onto each retriever span after `build_span_attrs`
returns. The pure mapper (`attributes.py`) stays import-light and signature-stable — only its
stale stub comment changed. Default path is byte-identical to today. Lint clean, 270 tests pass,
all 8 ACs covered. No blocking issues.

## Mechanical Checks

| Step   | Status | Notes                                              |
| ------ | ------ | -------------------------------------------------- |
| Format | PASS   | `ruff format --check` + prettier — 125 files clean |
| Lint   | PASS   | `ruff check src tests` — all checks passed         |
| Tests  | PASS   | 270 passed, 17 deselected in 43s                   |

## Issues

<details>
<summary>⚠️ Wasted corpus read on <code>--enrich-from-index --dry-run</code> — <code>cli.py:115-117</code></summary>

When both flags are set, `cli.py` builds the full corpus dict before calling `replay_jsonl`,
but `replay_jsonl` short-circuits at the `dry_run` guard (`exporter.py:66-72`) before the
enrichment loop — so the read is wasted and brushes against NFR-2's "zero corpus I/O on the
default path" spirit for dry runs. No correctness harm.

**Fix:** guard the build with `if args.enrich_from_index and not args.dry_run:`, or accept it
as an implicit "is the corpus readable?" validation for dry runs and document it. Non-blocking.

</details>

<details>
<summary>⚠️ <code>_retriever_attrs</code> helper raises bare <code>StopIteration</code> — <code>test_exporter.py:432</code></summary>

`next(...)` with no default raises `StopIteration` if no retriever span exists, which is a
less legible failure than an assertion. Used by 6 tests.

**Fix (optional):** add a `None` default and assert it at call sites, or leave as-is — the
test context makes the failure readable enough.

</details>

<details>
<summary>⚠️ <code>caplog</code> not scoped to the exporter logger — <code>test_exporter.py:468</code></summary>

`caplog.at_level(logging.WARNING)` captures all loggers. Passing
`logger="enterprise_rag_ops.observability.exporter"` would tighten the AC-3 assertion. Minor;
the test passes as-is.

</details>

## Acceptance Criteria

| AC   | Requirement                                              | Test                                                                       | Status |
| ---- | -------------------------------------------------------- | -------------------------------------------------------------------------- | ------ |
| AC-1 | Opt-in default = no behavior change (no `.content`)      | `test_ac1_enrich_default_no_behavior_change`                               | ✅     |
| AC-2 | Content hydration with a fake lookup, `.id`/`.rank` kept | `test_ac2_content_hydration_with_fake_lookup`                              | ✅     |
| AC-3 | Missing doc-id → omit + warn, no crash                   | `test_ac3_missing_doc_id_omit_and_warn`                                    | ✅     |
| AC-4 | No `.score` key in v1                                    | `test_ac4_no_score_key_in_v1`                                              | ✅     |
| AC-5 | `attributes.py` purity + unchanged signature             | `test_ac5_attributes_purity_and_unchanged_signature`                       | ✅     |
| AC-6 | Offline — no LanceDB / no Phoenix                        | `test_ac6_offline_no_heavy_import`                                         | ✅     |
| AC-7 | CLI flag wires the map; `--help` lists it                | `test_ac7_cli_wires_corpus_map_only_with_flag`, `test_ac7_help_lists_flag` | ✅     |
| AC-8 | Map shape `{doc.id: doc.text}` drives hydration          | `test_ac8_map_from_corpus_drives_hydration`                                | ✅     |

**Index alignment verified:** both `build_span_attrs` (`attributes.py:35`) and the enrichment
loop (`exporter.py:84`) iterate `enumerate(record.retrieval_ranked_ids)`, so `.content` lands
at the same `i` as `.id`/`.rank`. FR-8 (`--corpus` Should) was implemented.

## KB Staleness

The seam these notes describe as "reserved for a future phase" is now **live**. The DEFINE
deliberately defers `/update-kb observability` to land after this impl (Sprint-Wide Knowledge
Plan), so this is a planned follow-up, not a review gap — but the two references are now stale:

| KB File                                                  | What Changed                                                                                                        | Impact                                      | Action                                                                                                   |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `observability/concepts/span-attribute-mapping.md:32-33` | `.content` is no longer "intentionally omitted" — it is hydrated at the exporter boundary via `--enrich-from-index` | Reader is told a live feature doesn't exist | `/update-kb observability` — note `.content` is live (Phase 16, exporter boundary); `.score` still out   |
| `observability/concepts/span-tree-shape.md:64`           | Same — `.content` no longer reserved; `.score` still reserved                                                       | Same                                        | Same refresh; also record the doc-level-ID identity assumption (`retrieval_ranked_ids` == `Document.id`) |

## Knowledge Capture Suggestions

Worth folding into the deferred `/update-kb observability` pass:

| What was learned                                                                                                                                                                                                                                                     | Suggested KB domain                          | Action       |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ------------ |
| `EvalRecord.retrieval_ranked_ids` holds **doc-level** IDs identical to `Document.id`, so content enrichment needs only a `corpus.jsonl` map — zero BM25/LanceDB/embedder import. If chunking ever makes these IDs diverge, every lookup misses and warns per record. | observability                                | `/update-kb` |
| Boundary-enrichment pattern: heavy/external reads (`read_corpus`, `CORPUS_PATH`) stay at the CLI/exporter boundary; the pure mapper consumes a plain `Mapping[str, str]` — no new Protocol needed.                                                                   | observability (`dashboard-phoenix-boundary`) | `/update-kb` |

## ADR

None needed — confirmed in DEFINE (OQ-5): the coupling is a stdlib `Mapping[str, str]` passed at
the boundary, below the sprint's "ADR only if non-trivial" bar.

## Suggested Next Steps

1. **Ship it** — open the PR for `sprint-5/phase-16-phoenix-enrichment`. The nits are optional;
   none block merge. (Consider folding the dry-run guard nit in if touching `cli.py` anyway.)
2. **After merge** — run the deferred `/update-kb observability` to refresh
   `span-attribute-mapping` + `span-tree-shape` for the now-live seam and record the doc-level-ID
   identity assumption.
