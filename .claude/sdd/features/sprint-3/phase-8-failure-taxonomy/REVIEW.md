# Review: sprint-3/phase-8-failure-taxonomy — Rule-Based Failure-Mode Classifier

**Branch:** `sprint-3/phase-8-failure-taxonomy` | **Date:** 2026-05-30 | **Verdict:** ✅ READY

> **Update 2026-05-30:** all issues below were fixed in the same review session — AC-2
> priority-wins test added, the stranger-test leak scrubbed, skip-with-warning + dry-run
> stdout tests added, the distribution print moved under `--dry-run`, the `os.replace`
> temp-cleanup added, and ADR-0008 §4 clarified with the post-cascade count. `make lint
test` is green at **209 passed**. The original findings are retained below for the record.

## Summary

The classifier is correct and well-built: the five-label `StrEnum`, the first-match
cascade, the `None`-guards, and the gold-set-intersection `retrieval_miss` (not the
always-`False` `did_abstain_retrieval`) all match the DESIGN contract. Lint + 209 tests
pass offline, and the committed `results/baseline.jsonl` is fully tagged (999/999, no
`None`). The two findings that originally held it back from READY — the missing AC-2
priority-wins test and a tracked SDD file leaking a personal time-budget line — have both
been fixed, along with the four non-blocking nits.

## Mechanical Checks

| Step   | Status | Notes                                                                  |
| ------ | ------ | ---------------------------------------------------------------------- |
| Format | PASS   | `ruff format --check` — 108 files formatted; prettier OK               |
| Lint   | PASS   | `ruff check` — all checks passed                                       |
| Tests  | PASS   | 209 passed, 17 deselected — offline, no key/cassette (was 207 pre-fix) |

Baseline tagging verified: `abstention_error 441 · incomplete 268 · correct 236 ·
hallucination 33 · retrieval_miss 21` (total 999, zero untagged).

## Issues

<details>
<summary>🔴 AC-2 priority-wins not verified by any test — and the cleanest fixture is non-obvious</summary>

**`tests/eval/test_failure_taxonomy.py`** — no test exercises the cascade when two
predicates genuinely fire at once.

DEFINE AC-2 explicitly requires: "construct a record satisfying **multiple predicates**
and assert the higher-priority label wins." No current test does — edge case (iv) sets
`fact_recall=None`/`faithfulness_ratio=None`, so `is_incomplete`/`is_hallucination` never
fire there (the `None`-guards short-circuit them). The cascade order is therefore
asserted by construction but never proven against a real conflict.

**Note on the fix:** the canonical AC-2 example ("a false abstention that also has low
recall returns `abstention_error`, not `incomplete`") is degenerate against this
implementation — `is_incomplete` already guards on `not record.did_abstain_e2e`, so it
returns `False` whenever `did_abstain_e2e=True`. I verified this: that fixture leaves
`is_abstention_error` as the only firing predicate. The genuine multi-fire case is
**false-abstention + retrieval-miss** (both evaluate `True` independently):

```python
def test_cascade_priority_wins():
    """AC-2: when multiple predicates fire, the higher-priority label wins."""
    q = make_question(expected_doc_ids=["doc1"])          # answerable
    rec = make_eval_record(
        did_abstain_e2e=True,        # false abstention -> is_abstention_error True
        retrieval_ranked_ids=["doc2"],  # gold not in top-k -> is_retrieval_miss True
    )
    assert is_abstention_error(rec, q)
    assert is_retrieval_miss(rec, q)
    assert classify(rec, q) == FailureMode.ABSTENTION_ERROR  # priority wins
```

</details>

<details>
<summary>🔴 Stranger-test leak: personal time budget in a tracked SDD file</summary>

**`.claude/sdd/features/sprint-3/phase-8-failure-taxonomy/BRAINSTORM.md:110`**

> "**Overall rationale.** The budget is 5h and the user values minimum viable scope. …"

The SDD `features/` tree is tracked (committed in `fc8ff70`). "The budget is 5h" is
personal project-management context that fails the CLAUDE.local.md stranger test — it
teaches a reader nothing about the system. Fix: drop the budget clause, e.g. "The
minimal-scope constraint favours the smallest thing that proves the point." (Per the
[[no-carreira-path-automation]] memory this is managed manually — flagging, not
automating.)

</details>

<details>
<summary>⚠️ Skip-with-warning path (missing question_id) has no test</summary>

**`src/enterprise_rag_ops/eval/classify_cli.py:89-94`** — the DESIGN-pinned
"absent `question_id` → skip-with-warning, do not crash" branch is uncovered. Add a CLI
test with a record whose `question_id` is not in the patched gold map; assert it passes
through with `failure_mode is None`, a `WARNING` is logged (`caplog`), and `main` returns
`0`.

</details>

<details>
<summary>⚠️ Distribution print fires on every run, not just --dry-run</summary>

**`src/enterprise_rag_ops/eval/classify_cli.py:102-106`** — the `print("Failure mode
distribution:" …)` block runs before the `if args.dry_run` check, so a normal
`rag-classify` run also prints to stdout. The DESIGN frames this print as a `--dry-run`
feature. Either move the `print` inside the `if args.dry_run:` branch (and use
`logger.info` for the normal-mode summary), or keep it but document it in the CLI help
and ADR-0008. Low impact; behavioural-contract nit.

</details>

<details>
<summary>⚠️ test_classify_cli_dry_run does not assert the distribution was printed</summary>

**`tests/eval/test_failure_taxonomy.py:278-306`** — the test checks return code and
no-write but never captures stdout, which is the whole point of `--dry-run`. Add `capsys`
and assert `"Failure mode distribution:" in capsys.readouterr().out`.

</details>

<details>
<summary>⚠️ Temp file orphaned if os.replace raises (low real risk)</summary>

**`src/enterprise_rag_ops/eval/classify_cli.py:132`** — if `os.replace` raised, the
`.rag-classify-tmp-*.jsonl` would be left behind. In practice the temp file is created in
the **output's parent dir** (line 112), so a cross-device `os.replace` cannot occur and
this is near-unreachable — but a `try/except: temp_path.unlink(); raise` around the
replace would make it airtight. Optional.

</details>

## Acceptance Criteria

| #   | Criterion                                               | Status | Note                                                                     |
| --- | ------------------------------------------------------- | ------ | ------------------------------------------------------------------------ |
| 1   | `FailureMode` 5-member `str`-enum + round-trip          | ✅     | `StrEnum` (3.11+); `test_enum_membership`                                |
| 2   | First-match cascade, **priority-wins verified**         | ✅     | Fixed — `test_cascade_priority_wins` (false-abstention + retrieval-miss) |
| 3   | Predicates read only `EvalRecord`+`Question` by field   | ✅     | One fixture per label                                                    |
| 4   | Named threshold constants + ADR rationale               | ✅     | `0.5`/`0.5`; ADR-0008 §4 has values + baseline distribution              |
| 5   | `incomplete` semantics (not `formatting`)               | ✅     | ADR-0008 §5                                                              |
| 6   | Additive `failure_mode: str \| None`, back-compat parse | ✅     | `test_pydantic_roundtrip`                                                |
| 7   | `rag-classify` `--results`/`--output`, gold join        | ✅     | `test_classify_cli_offline` (injected gold)                              |
| 8   | New console script (not a `rag-eval` subcommand)        | ✅     | `pyproject.toml [project.scripts]`                                       |
| 9   | ADR-0008 accepted + 7 sections; ADR-0007 cross-ref      | ✅     | Both present                                                             |
| 10  | Offline tests, per-label + 5 edges, no cassette         | ✅     | `test_edge_cases_fr12_ac10`                                              |
| 11  | Additive invariant — only `failure_mode` in `eval/`     | ✅     | Diff confirms: records.py +1 line, 2 new files only                      |
| 12  | No new runtime dependency                               | ✅     | `[project.dependencies]` unchanged                                       |
| 13  | (Should) `make classify` + `.PHONY`                     | ✅     | Present                                                                  |
| 14  | (Could) `--dry-run` no-write + `--questions-revision`   | 🟡     | Both implemented + tested; dry-run stdout not asserted                   |

## KB Staleness

| KB File                          | What Changed                       | Impact | Action                                                                                                                                |
| -------------------------------- | ---------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `rag-eval/` (eval-record-schema) | `EvalRecord` gained `failure_mode` | Low    | One-line note only; the **taxonomy** itself is owned by the deferred `observability` KB per the SDD plan — not a `rag-eval` edit now. |

No breaking drift. The DEFINE/DESIGN deliberately route the decided taxonomy into a new
`observability` KB domain built at **sprint-close** (after ADR-0008 acceptance), so no KB
edit is required in this phase.

## Knowledge Capture Suggestions

| What was learned                                                                                               | Suggested KB domain | Action                                                      |
| -------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------- |
| Failure-taxonomy vocabulary, first-match cascade, and empirically-grounded thresholds-from-distribution method | `observability`     | `/new-kb observability` at sprint-close (already scheduled) |

## ADR

No missing ADR — ADR-0008 was written and **accepted** this phase, and ADR-0007 gained
the one-line cross-reference. The minor doc nuance (ADR-0008 §4 cited "37/519 ≈ 7.1%" as
the isolated-predicate hallucination rate while the final tagged count is **33**) has been
**fixed**: §4 now states the post-cascade count and explains that the cascade strips some
low-faithfulness records into `abstention_error`/`retrieval_miss` first.

## Suggested Next Steps

1. ✅ Done — `test_cascade_priority_wins` (false-abstention + retrieval-miss) added, closes AC-2.
2. ✅ Done — "5h budget" clause scrubbed from `BRAINSTORM.md:110` (stranger test).
3. ✅ Done — skip-with-warning CLI test + `capsys` dry-run assertion added; distribution
   print moved under `--dry-run` (normal mode now logs via `logger.info`); `os.replace`
   temp-cleanup added; ADR-0008 §4 clarified with the post-cascade count (33).
4. `make lint test` re-run — **209 passed**, offline. Commit the fixes, then open the PR.
5. At sprint-close: `/new-kb observability` to capture the taxonomy (already planned).
