# Review: sprint-2/phase-5-retrieval-eval — Retrieval Metrics & Gold-Aware Corpus

**Branch:** `sprint-2/phase-5-retrieval-eval` | **Date:** 2026-05-24 | **Verdict:** ✅ READY (post-fix)

## Summary

The functional core was solid from the start — metric formulas match the KB, the
None-empty-denominator convention and dedup invariant are correct, per-category
aggregation skips `None`, the gold-aware sampler is deterministic and decoupled from
`eval/`, and the `load_retriever` re-chunk fix (FR-9) is clean. The first pass flagged a
hand-fabricated cassette (🔴 I-1) and a lint failure (🔴 I-2), plus three minor issues.
**All five are now resolved.** Recording a real cassette for I-1 exposed a deeper
architectural defect — FR-8's e2e abstention was targeting the wrong layer — which is now
fixed by making the abstention sentinel a single enforced contract at both abstention
points. `make lint test` is green; the e2e abstention test replays a genuine OpenAI
response offline. See **Post-Fix Resolution** below.

## Mechanical Checks

| Step   | Status | Notes                                                                  |
| ------ | ------ | ---------------------------------------------------------------------- |
| Format | PASS   | `ruff format --check` — 83 files formatted.                            |
| Lint   | PASS   | `ruff check` clean; prettier clean (walkthrough.md fixed).             |
| Tests  | PASS   | `170 passed, 17 deselected` — offline, **no `OPENAI_API_KEY`** in env. |

Diff reviewed: `git diff dc57317...HEAD` (the 7 phase commits `a4f232f..e67820b`) plus the
post-review fixes below (uncommitted). `origin/main` is one unpushed commit behind, so
`origin/main...HEAD` is inflated with unrelated harness churn — excluded.

## Issues (all resolved)

<details>
<summary>🔴→✅ I-1 — Cassette was hand-fabricated; recording it exposed FR-8 targeting the wrong layer</summary>

`tests/eval/cassettes/abstention_info_not_found.yaml`

The original cassette was hand-written (fake `id` `chatcmpl-vcr-mocked-id`, 2023 timestamp
for a 2025 model, `body: null`, no `x-stainless-*`/`x-request-id`/`openai-organization`
headers) — functionally the mock that AGENTS.md forbids for eval assertions, defeating
ADR-0006 and NFR-8.

**Recording a real response surfaced a deeper defect** (see Post-Fix Resolution): the
sentinel is emitted only by the retrieval gate (`generation/cli.py:52`), the generator
free-form abstained, and the test called the generator directly — so the assertion could
never pass with a real model. Fixed by enforcing the sentinel at the generator.

**Now:** the committed cassette is a genuine recording (11 real-header lines, `Authorization`
scrubbed → 0 key/auth lines, contains the exact sentinel). The single live run cost < $0.01
(NFR-8). The test passes offline with no key.

</details>

<details>
<summary>🔴→✅ I-2 — `make lint` failure + absolute-path leak in walkthrough.md</summary>

`.claude/sdd/features/sprint-2/phase-5-retrieval-eval/walkthrough.md` — prettier-formatted
and all `file:///Users/mauricioaraujo/...` links rewritten to repo-relative. `make lint`
now passes with the file present.

</details>

<details>
<summary>⚠️→✅ I-3 — ADR-0005 model identity corrected</summary>

`docs/adr/0005-llm-provider-matrix.md:22` now states the generator default as
`gpt-5-nano-2025-08-07` (matching `openai_generator.py:23`), dropping the incorrect
`gpt-4o-mini` aliasing claim.

</details>

<details>
<summary>⚠️→✅ I-4 — threshold_sweep.py F1 display</summary>

`eval/threshold_sweep.py:54-60` — F1 is `None` only when undefined (either side `None`, or
0/0); a genuine `0.0` now prints as `0.0000`. Guard uses `is not None`.

</details>

<details>
<summary>⚠️→✅ I-5 — `@pytest.mark.vcr` clarified</summary>

`tests/eval/test_abstention.py` — comment added noting the marker is a selection label only;
the cassette is applied by the `vcr_record` fixture (vcrpy 6 ships no pytest plugin).

</details>

<details>
<summary>⚠️→✅ I-6 — stale `load_retriever` docstring (found on the second sweep)</summary>

`retrieval/pipeline.py:115-120` — the docstring claimed "the corpus is read once to build
the maps," which is exactly what FR-9 removed. Rewritten to state the maps are rebuilt from
the sidecar + LanceDB `source_type` column, never from `corpus.jsonl`.

</details>

## Post-Fix Resolution — the FR-8 abstention-layer defect (the substantive fix)

Recording a real cassette revealed that the fabricated one had been masking a design defect:

- The `ABSTAIN_ANSWER` sentinel was emitted **only** by the retrieval gate
  (`generation/cli.py:52`, empty-retrieval short-circuit, no LLM call).
- The generator's prompt (`generation/prompt.py`) previously said "say so plainly" — so on a
  real call the model abstained **free-form** ("The provided context does not contain…"),
  never the canonical sentinel.
- `test_e2e_abstention_paris_anchor` called `generator.generate()` directly, bypassing the
  gate — so `assert answer == ABSTAIN_ANSWER` could never pass with a real model.
- The phase's own threshold sweep is the clincher: at threshold 0.45, `info_not_found`
  gate-recall is **0.0** — every unanswerable question passes the gate to the generator. The
  **generator is the operative abstention layer**, so e2e abstention is only measurable if
  the generator emits a machine-checkable signal.

**Fix — one enforced sentinel contract at both abstention points:**

| File                                                  | Change                                                                                                                                                         |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `generation/schema.py`                                | `ABSTAIN_ANSWER` moved here (canonical home) — breaks the `cli`↔`prompt` import cycle.                                                                         |
| `generation/cli.py`                                   | re-exports `ABSTAIN_ANSWER` from `schema` (preserves NFR-5's "import from cli" path + all importers).                                                          |
| `generation/prompt.py`                                | `_ROLE` now instructs: when context is insufficient, set `answer` to **exactly** the sentinel, return empty `sources`, and do not answer from prior knowledge. |
| `tests/eval/cassettes/abstention_info_not_found.yaml` | re-recorded against the hardened prompt — the model now emits the exact sentinel.                                                                              |

Consequences: `evaluate_e2e_abstention`'s exact-match is now correct at both paths; a
parametric "Paris leak" stays distinguishable (it is simply not the sentinel); **vcrpy +
ADR-0006 are now genuinely justified** (the generator _is_ called for `info_not_found`; the
gate rarely fires), so they stay.

## Acceptance Criteria

| AC                                                                | Status | Note                                                                                                                                                                       |
| ----------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1, 3, 4, 12 — gold-aware sampler + CLI + determinism + empty-gold | ✅     | `ingest/sampler.py`, `cli.py`; `tests/ingest/*`                                                                                                                            |
| 2 — answerability inspection tally                                | ✅     | recorded in `walkthrough.md` § Answerability Inspection: 30/500 unanswerable (20 `info_not_found` + 10 `high_level`); confirms the predicate over a category-string check. |
| 5, 6, 7 — metric formulas, dedup, edge cases, None-denominator    | ✅     | `eval/retrieval_metrics.py`; `tests/eval/test_retrieval_metrics.py`                                                                                                        |
| 8 — per-category aggregation, None skipped                        | ✅     | `eval/retrieval_eval.py`                                                                                                                                                   |
| 9 — retrieval-level abstention precision/recall                   | ✅     | `eval/abstention.py:59`                                                                                                                                                    |
| 10 — e2e abstention vs imported sentinel, Paris anchor            | ✅     | **now genuinely validated** — hardened generator + real cassette; gate + generator share the sentinel                                                                      |
| 11 — `load_retriever` no corpus re-read; own first commit         | ✅     | `pipeline.py:114`; `tests/retrieval/test_pipeline_loader.py`; commit `a4f232f`                                                                                             |
| 13 — ADR-0005 written & accepted                                  | ✅     | model identity corrected (I-3)                                                                                                                                             |
| 14 — (Should) nDCG                                                | ✅     | `ndcg_at_k`; None/0.0 semantics correct                                                                                                                                    |
| 15 — (Should) sweep + Makefile + ADR-0002                         | ✅     | `threshold_sweep.py`; targets present                                                                                                                                      |
| 16 — cassette/replay offline                                      | ✅     | genuine cassette, `record_mode="none"` default, offline `make test`, auth scrubbed                                                                                         |

## Knowledge Capture Suggestions

| What was learned                                                                                                                                                                                                                                                                                                                              | KB domain       | Action                                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------ |
| Retrieval metrics + dedup + None convention + abstention scorers as implemented in `eval/`                                                                                                                                                                                                                                                    | `rag-eval`      | `/update-kb rag-eval` (post-merge; already sequenced)                    |
| **Abstention has two layers (retrieval gate + generator); the gate rarely fires for `info_not_found`, so the canonical sentinel must be enforced at the generator for e2e abstention to be measurable.** Hard-won, non-obvious — and the failure mode (free-form abstention defeats exact-match) is exactly what a fabricated cassette hides. | `rag-eval`      | fold into the `/update-kb rag-eval` pass; cross-link ADR-0006 + ADR-0003 |
| LanceDB no-vector `.search().select().to_arrow()` returns **all** rows (default-10 limit applies only to vector/FTS search) — verified on 0.30.2                                                                                                                                                                                              | `rag-retrieval` | optional one-liner                                                       |

## KB Staleness

| KB File                         | What Changed                                        | Action                                          |
| ------------------------------- | --------------------------------------------------- | ----------------------------------------------- |
| `rag-eval/` (draft, judge-only) | Phase 5 adds retrieval metrics + abstention scoring | `/update-kb rag-eval` post-merge (non-blocking) |

`rag-retrieval/concepts/retrieval-eval-metrics.md` is **not** stale — formulas consumed verbatim.

## ADR

ADR-0005 (provider matrix) and ADR-0006 (cassette/replay) are written and accepted; ADR-0005
corrected (I-3). **New recommendation:** the abstention fix changed Phase-3 generator behavior
(the prompt now enforces the exact sentinel + forbids parametric answers). This is a real
behavior change worth one line in **ADR-0003 (generation)** — "abstention is a single
canonical sentinel enforced at both the retrieval gate and the generator prompt." Recommend,
not yet written (an ADR edit is your call).

> **Numbering note (from `/design`):** cassette/replay took ADR-0006; the roadmap's penciled
> failure-mode-taxonomy ADR should move to 0007. Update `docs/planning/roadmap.md`.

## Suggested Next Steps

All review issues (I-1…I-6) and every required AC are resolved. Remaining items are optional
or post-merge:

1. (Optional, recommended) Add the one-line **ADR-0003** note on the enforced abstention
   sentinel — the only doc-consistency gap left from the Phase-3 prompt change.
2. Stage the post-review fixes — suggest a `fix(generation): enforce canonical abstention
sentinel at the generator + real cassette` commit (plus the doc/lint nits) — then open the PR.
3. Post-merge: `/update-kb rag-eval`, update the roadmap ADR numbering (0006→cassette,
   taxonomy→0007), mirror Phase-5 status into the Carreira study track.
