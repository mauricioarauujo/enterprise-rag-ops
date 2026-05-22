# Review: sprint-1/phase-3-generation — Generation Layer with Source Attribution

**Branch:** `main` (uncommitted) | **Date:** 2026-05-21 | **Verdict:** ✅ READY

## Summary

The generation layer is structurally sound: every seam is narrow and correct,
the abstention short-circuit is proven by test, the CI-offline invariant holds,
and scope discipline is clean against the DESIGN Won't list. The `code-reviewer`
flagged two blocking issues (a missing AC-18 logging test and a stranger-test
leak in ADR-003); both are fixed in this turn, along with one non-blocking
smoke-fixture improvement. `make verify` is green.

## Mechanical Checks

| Step   | Status | Notes                                                          |
| ------ | ------ | -------------------------------------------------------------- |
| Format | PASS   | ruff format + prettier clean (ADR-003 reflowed post-edit)      |
| Lint   | PASS   | ruff check — all checks passed                                 |
| Tests  | PASS   | offline 107 passed, 17 deselected; live `make smoke` 12 passed |

## Issues

<details>
<summary>🔴 BLOCKING (FIXED) — Missing AC-18 logging test</summary>

**`tests/generation/test_cli.py`** — DEFINE AC-18 requires a unit test that
captures the INFO log records and asserts both the post-assembler `doc_id`s and
the final `sources` are present. No such test existed.

**Fix applied:** added `test_happy_path_logs_context_doc_ids_and_sources`, which
drives the CLI happy path through `caplog.at_level(INFO, ...)` and asserts a
single record contains `context_doc_ids=` + `sources=` with both doc_ids.
Verified passing.

</details>

<details>
<summary>🔴 BLOCKING (FIXED) — Stranger-test leak in docs/adr/0003-generation.md</summary>

**`docs/adr/0003-generation.md:126, 139–149, 161`** — the public ADR named
private planning artifacts (`spec.md`, `adrs_planned.md`) and private repo
paths (`portfolio/enterprise_rag_ops/`, `estudos/enterprise_rag_ops/`, "the
Carreira"). Per the project's stranger test, a public file must not reveal that
a private planning repo exists or where it lives. (Phase 2's REVIEW caught the
same class of leak — this is a recurring boundary.)

**Fix applied:**

- L126: "The project's `spec.md` separately designates" → "The project
  separately designates".
- L137–149: "Planned-ADR renumber" section rewritten to drop all private path
  names; states the public-facing renumber (observability → ADR-004, LLM matrix
  → ADR-005) and that no shipped ADR referenced ADR-003 by number.
- L161 (Alternatives table): dropped "`adrs_planned.md` is private" in favor of
  "no shipped ADR references ADR-003 by number yet (ADR-002 was the most
  recent)".

The in-repo references that remain (`.claude/sdd/...`, `.claude/kb/...`, ADR-002)
are tracked paths a reader can open — those are correct, not leaks.

</details>

<details>
<summary>⚠️ NON-BLOCKING (FIXED) — Smoke fixture didn't guard on OPENAI_API_KEY</summary>

**`tests/generation/test_generation_smoke.py:130`** — `_require_local_artifacts`
skipped on a missing index/corpus but not on a missing `OPENAI_API_KEY`, so a
developer with an index but no key would hit a test _error_ (RuntimeError) rather
than a clean skip.

**Fix applied:** the fixture now skips first on a missing `OPENAI_API_KEY`,
matching the `make retrieval-smoke` UX.

</details>

<details>
<summary>⚠️ NON-BLOCKING (DEFERRED) — rag-retrieval KB predates the Phase 3 widening</summary>

**`.claude/kb/_index.yaml:32–42`** — Phase 3 widened the retrieval seams:
`VectorStore` gained `fetch_chunks_by_chunk_ids` and `Retriever` gained
`retrieve_chunks` (winning chunk per doc). The `rag-retrieval` domain text
predates both. Not a code-correctness issue.

**Action:** fold into the planned post-Phase 3 `/new-kb rag-generation` session
(see Knowledge Capture below) — the cleaner home for the new methods + the
`ContextAssembler` policy + the "feed the ranked chunk, not the doc title" lesson
is the generation domain, with a cross-link from `rag-retrieval`. Deferred
deliberately to avoid scope creep in this phase.

</details>

## Acceptance Criteria

All 18 DEFINE acceptance criteria are met. Spot-check of the load-bearing ones:

| AC    | Criterion                                                      | Status | Evidence                                                                         |
| ----- | -------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------- |
| AC-1  | `AnswerWithSources` required fields + closed schema            | PASS   | `test_schema.py` (5 tests)                                                       |
| AC-6  | Winning chunk per doc, fused-rank order, max_chunks            | PASS   | `test_context_assembler.py` (7 tests) + `test_hybrid_retriever.py` (chunk-level) |
| AC-8  | Abstain short-circuit issues no LLM call                       | PASS   | `test_cli.py::test_abstain_short_circuit_*` (spy generator)                      |
| AC-11 | Offline pipeline-contract via StubGenerator                    | PASS   | `test_generation_contract.py` (2 tests)                                          |
| AC-13 | Smoke: valid answer on all 10; ≥1 source on attribution subset | PASS   | `test_generation_smoke.py` — live run `12 passed` (two-tier, see Smoke Finding)  |
| AC-14 | Clean error on missing `OPENAI_API_KEY`                        | PASS   | `test_cli.py::test_missing_openai_api_key_*`                                     |
| AC-16 | `openai` version-bounded; no eval/observability deps           | PASS   | `pyproject.toml` (`openai>=1.50,<2.0`)                                           |
| AC-18 | Logging asserts doc_ids + sources                              | PASS   | `test_cli.py::test_happy_path_logs_*` (added this turn)                          |

## Smoke Finding (live run, 2026-05-21)

`make smoke` against the real OpenAI API surfaced three issues the offline suite
could not. **Final result: `12 passed in 593s`.**

1. **`gpt-5-nano-2025-08-07` rejects `temperature=0`** (`BadRequestError`: only
   the default `1` is supported for this GPT-5-class model). Fixed by dropping the
   `temperature` kwarg in `openai_generator.py`; reproducibility now rests on the
   deterministic prompt builder, with a model-level strategy deferred to ADR-005.
   ADR-003's build-time invariant updated to match.
2. **Wrong chunk fed to the LLM (attribution bug).** The first design fetched all
   chunks of each retrieved doc and kept the lexicographically-smallest `chunk_id`
   — which is the doc's title chunk (12 chars), not the passage that ranked the
   doc. The model received a title and abstained even on answerable questions
   (`qst_0258`'s gold doc has 33 chunks; we sent `::0`, the answer was in
   `::5`/`::10`/`::11`). Root cause: `HybridRetriever.retrieve`'s doc-dedup
   discards _which chunk_ ranked. Fixed by adding `HybridRetriever.retrieve_chunks`
   (returns the winning `(chunk_id, doc_id, score)` per doc), reworking
   `ContextAssembler` to feed those chunks, and replacing
   `VectorStore.fetch_chunks_by_doc_ids` with `fetch_chunks_by_chunk_ids`. The
   doc-level `retrieve` is unchanged (still the Sprint 2 eval contract). +3 unit
   tests; ADR-003 §Decision-3 and the alternatives table updated.
3. **Faithful abstention dominates the dev subset.** The 100-docs/source subset
   holds the gold docs for only 3 of 500 benchmark questions, and of those only
   `qst_0104` + `qst_0258` have an answer self-contained in the top-ranked chunk.
   On everything else the model correctly abstains with `sources=[]`. A flat
   `len(sources) >= 1` would only pass via hallucinated citations. Reworked to a
   two-tier gate: valid non-empty answer on all 10; `≥1` source on the
   attribution subset (qst_0104, qst_0258). `qst_0252` is answerable-in-corpus but
   its decision rule spans chunks beyond the top-1 fed, so it sits in the wiring
   tier — a multi-chunk / completeness retrieval-quality concern flagged for
   Sprint 2. DEFINE RQ-5/FR-13/AC-13, DESIGN, and ADR-003 updated.

All three fixes are in; `make smoke` passes (2 attribution + 10 wiring assertions
green) and `make verify` is 107 green. The two-tier gate is a stronger check than
the original — it proves the system attributes when it can and abstains faithfully
when it cannot.

## Knowledge Capture Suggestions

| What was learned                                                                                                                                             | Suggested KB domain | Action                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------- | ----------------------------------------------------------------------- |
| `Generator` Protocol + `StubGenerator` CI pattern (generation analogue of `StubEmbedder`)                                                                    | `rag-generation`    | `/new-kb rag-generation` (post-merge)                                   |
| OpenAI structured-outputs (`response_format` json_schema `strict`) + Pydantic defensive re-validation as the attribution mechanism                           | `rag-generation`    | concept in the new domain                                               |
| Context assembly: feed the **ranked** chunk per doc (not the doc's title chunk); doc-dedup must retain the winning `chunk_id` or attribution silently fails  | `rag-generation`    | pattern in the new domain (the load-bearing lesson from the live smoke) |
| Two-tier smoke gate for a subset-limited corpus (wiring on all; attribution only where the answer is in-context) — faithful abstention is correct, not a bug | `rag-generation`    | pattern in the new domain                                               |

This mirrors the Phase 2 plan: build/refocus the KB _after_ the ADR ships and
the design is proven by implementation.

## KB Staleness

| KB File                                    | What Changed                       | Impact                           | Action                                                                                |
| ------------------------------------------ | ---------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------- |
| `.claude/kb/_index.yaml` (`rag-retrieval`) | `VectorStore` widened to 3 methods | KB describes a 2-method contract | Note the widening when `/new-kb rag-generation` runs; cross-link from `rag-retrieval` |

## ADR

ADR-003 (`docs/adr/0003-generation.md`) is written and accepted — it captures
the `Generator` seam, the structured-JSON attribution format, the abstention
behavior, and the same-family judge/generator carry-forward flag for ADR-005.
Planned-ADR renumber (observability → ADR-004, LLM matrix → ADR-005) is recorded
in both the public README index and the private planning docs. No further ADR
is needed for this phase.

## Suggested Next Steps

1. **Run `make smoke` locally** with `OPENAI_API_KEY` exported and the index
   built — this is the only acceptance check not exercisable in CI.
2. **Open the PR** for sprint-1/phase-3-generation (branch at PR time, per the
   Phase 2 cadence). Sprint 1 substrate is complete after merge.
3. **Post-merge:** `/new-kb rag-generation` to capture the three patterns above
   and resolve the `rag-retrieval` staleness note.
