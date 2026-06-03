# Review: sprint-6/phase-18-evalrecord-reasoning — Persist Judge Reasoning + Generation Input (ADR-0010)

**Branch:** `sprint-6/phase-18-evalrecord-reasoning` | **Date:** 2026-06-02 | **Verdict:** ✅ READY

## Summary

Persists the judge's `per_fact` / `per_citation` verdict reasoning into the gold `EvalRecord`
schema (optional + defaulted, reusing the closed `eval/schema.py` models, populated from the
in-memory verdict at zero extra API cost) and ratifies the bronze/gold data-layering decision
in ADR-0010 as a scoped amendment to ADR-0007. Mechanical gate is green (283 passed) and the
`code-reviewer` agent returned READY with no blocking issues; all three DESIGN consistency
findings (C-1/C-2/C-3) are confirmed resolved. Two non-blocking review findings were fixed in a
follow-up (the stranger-test budget leak + ADR polish); the rest are documented below.

## Mechanical Checks

| Step   | Status | Notes                                                |
| ------ | ------ | ---------------------------------------------------- |
| Format | PASS   | pre-commit `make format` clean (125 files formatted) |
| Lint   | PASS   | `ruff check` + `prettier --check` clean              |
| Tests  | PASS   | `make test` → **283 passed, 17 deselected** (re-run) |

## Consistency-check findings (from DESIGN) — all resolved

- **C-1 (stale exclusion assertion — was the one real trap).** ✅ Resolved. The old
  `test_eval_record_roundtrip_and_exclusions` is renamed to `..._and_presence` and its four
  `not in` assertions are inverted to `in` — not duplicated. The phase would have failed `make
test` at this exact spot otherwise.
- **C-2 (weak `per_citation` assertion on AC-4).** ✅ Resolved. The AC-4 test fixture
  guarantees a cited source (`MockRetriever` → `doc_1::0` → `StubGenerator` cites it →
  `StubJudge` marks it `supported`), so `per_citation[0]` is asserted on real values, not `[]`.
- **C-3 (ADR filename slug).** ✅ Resolved. `0010-persist-judge-reasoning-bronze-gold.md`
  matches the repo's descriptive-slug convention and is referenced consistently.

## Issues

<details>
<summary>⚠️ Stranger-test leak: private time-budget framing in tracked DEFINE.md — <strong>FIXED</strong></summary>

`DEFINE.md:26,290` justified the bronze-defer scope call with "burns the ~5h/week budget on
scope creep." Per `CLAUDE.local.md` the personal time budget never goes in a tracked file. The
technical argument (a dead, un-integration-testable module = scope creep in a decision phase)
stands on its own. **Fixed in this review pass** — both lines restated in system-design terms,
no budget reference remains in any tracked artifact.

</details>

<details>
<summary>⚠️ ADR-0010 "fallback" used as a verb + thin Consequences — <strong>FIXED</strong></summary>

`0010-...md:56` "we fallback to" → "we fall back to" (verb is two words). Also added two
Consequences bullets making Phase 19's obligations explicit: (1) add the `data/raw_eval/`
`.gitignore` line before activating the writer; (2) sanitize/validate `run_id` so it cannot
contain path separators (the `data/raw_eval/{run_id}/...` key would otherwise create nested
dirs); plus a note that the `rag-eval` KB refresh is deferred and the ADR-0007 §1 table remains
the narrowed historical record. **Fixed in this review pass.**

</details>

<details>
<summary>⚠️ AC-4 "zero extra call" proof is structural, not a single tight invariant — non-blocking, left as-is</summary>

`tests/eval/test_runner.py` asserts `gen_call_count == 1` / `judge_call_count == 1`. With one
model + one question those counts are 1 regardless of population, so the assertion guards
against a _regression_ (an added LLM call during population) rather than proving the copy is
free. The zero-extra-call property is structurally guaranteed: population lives inside the
existing `EvalRecord(...)` constructor at `runner.py:242-243`, with no LLM entry point between
`judge_with_stats` (`:187`) and the build site. Field-value assertions + the call-count guard
together cover the AC-4 intent. No change needed at this maturity.

</details>

<details>
<summary>⚠️ ADR-0007 §1 schema table doesn't list the new fields — non-blocking, by design</summary>

`docs/adr/0007-eval-record-schema.md:36-55` still lists only the pre-amendment fields. This is
the documented "amendment narrows, pointer records it" pattern — ADR-0008 added `failure_mode`
the same way without editing the ADR-0007 table. The Consequences pointer (`0007:103`) is the
canonical signal. The deferred `/update-kb rag-eval` closes the gap for agents. Left as-is.

</details>

## Acceptance Criteria

| AC   | Requirement                                                                              | Status                                                                                                                        |
| ---- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| AC-1 | Fields optional + defaulted, reuse `FactVerdict`/`CitationVerdict`, no new model         | ✅ `test_eval_record_schema_ac1`                                                                                              |
| AC-2 | Populated record round-trips losslessly; JSON carries the keys + labels                  | ✅ `test_eval_record_lossless_roundtrip_ac2`                                                                                  |
| AC-3 | Pre-change JSONL loads with both fields `None`; a reader path unaffected                 | ✅ `test_eval_record_backward_compat_ac3` (incl. `load_run_records`)                                                          |
| AC-4 | Runner populates from in-memory verdict; no extra LLM call                               | ✅ `test_runner_populates_verdicts_ac4`                                                                                       |
| AC-5 | ADR-0010 complete (a–f)                                                                  | ✅ verified — scoped amendment + quote, bronze key/idempotency/built-in-19, footprint, privacy, cassette overlap, B2 fallback |
| AC-6 | ADR-0007 pointer + `EvalRecord` docstring de-drift                                       | ✅ `0007:103` pointer; docstring rewritten                                                                                    |
| AC-7 | No bronze code / no `.gitignore` / no exporter or reader edit / no re-run / no hydration | ✅ diff = only the 6 manifest files                                                                                           |

## ADR

ADR-0010 was the phase deliverable and is `accepted` — no further ADR needed. ADR-0007 carries
the amendment pointer. (No new architectural decision was made beyond what ADR-0010 records.)

## KB Staleness

| KB File                                   | What Changed                                    | Impact                                              | Action                                                                                                               |
| ----------------------------------------- | ----------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `rag-eval/concepts/eval-record-schema.md` | `EvalRecord` gained `per_fact` / `per_citation` | Concept lists the persisted fields; now missing two | `/update-kb rag-eval` — **deferred to after ADR-0010 per the Sprint-Wide Knowledge Plan (SPRINT.md), not a blocker** |

## Knowledge Capture Suggestions

Nothing net-new — the bronze/gold split, the optional-defaulted backward-compat pattern, and
the cassette-vs-bronze distinction are all already covered by `rag-eval`
(`eval-record-schema`, `stats-capture-seam`, `cassette-replay-eval`). The pending
`/update-kb rag-eval` refresh (above) is the only KB action.

## Suggested Next Steps

1. **(Optional) re-stage the review fixes** — the DEFINE/ADR edits from this pass are
   uncommitted; fold them into the branch with a follow-up commit before opening the PR.
2. **Open the PR** for `sprint-6/phase-18-evalrecord-reasoning` → `main`.
3. **After merge:** run `/update-kb rag-eval` to refresh `eval-record-schema` with the new
   fields (deferred per SPRINT.md).
4. **Then:** `/brainstorm sprint-6/phase-19-full-trace-hydration` — the re-run + bronze build +
   Phoenix hydration phase, which implements against ADR-0010's ratified bronze contract.
