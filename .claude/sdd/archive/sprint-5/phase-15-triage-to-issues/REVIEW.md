# Review: sprint-5/phase-15-triage-to-issues — Triage to GitHub Issues

**Branch:** `sprint-5/phase-15-triage-to-issues` | **Date:** 2026-06-02 | **Verdict:** ✅ READY

## Summary

`rag-issues` closes the eval→action loop: it drafts one grounded GitHub Issue per failure
cluster from `triage.json`, dry-run by default, idempotent via a body-marker fingerprint, with
the integration boundary recorded in ADR-0009. The code was authored directly in Claude Code
(the `agy` delegation hung), so the `code-reviewer` agent's cold pass was the primary external
check — it found no blocking bugs; the core logic, idempotency scheme, and safety-by-default
contract were correct on first pass. Six findings (all non-blocking) were applied.

## Mechanical Checks

| Step   | Status | Notes                                            |
| ------ | ------ | ------------------------------------------------ |
| Format | PASS   | `make format` (auto-applied; pre-commit hook)    |
| Lint   | PASS   | `ruff format --check` + `ruff check` + prettier  |
| Tests  | PASS   | `make lint test` — **261 passed, 17 deselected** |

## Issues

All `code-reviewer` findings were resolved in the review-fixes commit. None blocking.

<details>
<summary>⚠️ <code>_draft_filename</code> didn't sanitize <code>/</code> — path traversal under a future taxonomy — <code>issues_cli.py</code></summary>

A cluster key containing `/` would turn `results/issues/<fm>-<cat>.md` into a subdirectory
path (`_atomic_write` calls `mkdir(parents=True)`). Not a live bug — the current `FailureMode`
enum and `category` values are safe `snake_case` — but unguarded. **Fixed:** `_draft_filename`
now replaces `/` and spaces with underscores in both `failure_mode` and `category`.

</details>

<details>
<summary>⚠️ AC-13 didn't prove the primary claim (<code>GhCliClient</code> never built) — <code>test_issues.py</code></summary>

The existing AC-13 test only asserted the pure core imports no `openai`. The DESIGN's primary
AC-13 claim — the `gh` impl is never instantiated in a dry-run — was untested; if the
safety-by-default guard ever broke, no test would catch it. **Fixed:** added
`test_ac13_ghcli_never_instantiated_in_dry_run`, which spies on `GhCliClient.__init__` and
asserts it is never called during a no-`--create` run.

</details>

<details>
<summary>⚠️ <code>repo</code> param on <code>build_issue_draft</code> was unused (no ADR anchors it) — <code>issues.py</code></summary>

FR-1 specified `repo=None`, but the param did nothing in v1 and no ADR anticipates a
body-level use (ADR-0009's named seam is the `GitHubClient` swap, not repo-qualified links) —
a minimal-scope violation at the design level. **Fixed:** dropped `repo` from
`build_issue_draft` (and the CLI call). The `--repo` flag still flows to `GhCliClient` where it
is actually used. A deliberate, documented deviation from the FR-1 literal signature.

</details>

<details>
<summary>💬 <code>|</code> in a cluster key would corrupt the GitHub search (it's the OR operator) — <code>issues.py</code></summary>

The fingerprint uses `|` as the field separator, which is also GitHub search's OR operator. No
live hazard (taxonomy-controlled), but unguarded. **Fixed:** `_cluster_identity` now raises
`ValueError` if `failure_mode` or `category` contains `|`, failing loud rather than emitting a
silently-broken dedup token.

</details>

<details>
<summary>💬 AC-12 create-branch didn't assert the returned URL is reported — <code>test_issues.py</code></summary>

`test_ac12_create_files_new_issue` checked the create call but not that the URL is printed
(AC-12 says "the returned URL is reported"). **Fixed:** added a `capsys` assertion that the
fake's returned URL appears in stdout.

</details>

<details>
<summary>💬 AC-10 exercises only the <code>os.replace</code> cleanup path, not the write-failure path — <code>test_issues.py</code></summary>

`_atomic_write` cleans up on both write failure and `os.replace` failure; the test patches only
`os.replace`. A `NamedTemporaryFile` mock to exercise the write path proved fragile (a
`MagicMock` context manager's `__exit__` returns truthy and would suppress the exception,
inverting the test). **Decision:** kept the single robust `os.replace` test and documented that
the write-failure branch is the identical `classify_cli.py` house idiom (prior art), rather than
ship a flaky mock. Non-blocking nit per the reviewer.

</details>

## Acceptance Criteria

| AC    | Status | Evidence (test in `tests/eval/test_issues.py`)                                  |
| ----- | ------ | ------------------------------------------------------------------------------- |
| AC-1  | ✅     | `test_ac1_pure_draft_from_cluster` — grounded `IssueDraft`, no I/O              |
| AC-2  | ✅     | `test_ac2_grounded_body` — rep id/text + "Observed across" models               |
| AC-3  | ✅     | `test_ac3_fingerprint_format` — exact marker; fingerprint ⊂ marker              |
| AC-4  | ✅     | `test_ac4_fingerprint_includes_schema_version` — v1 ≠ v2 fingerprint            |
| AC-5  | ✅     | `test_ac5_determinism` — two builds byte-identical                              |
| AC-6  | ✅     | `test_ac6_schema_gate_happy_path` — valid 1.0 → exit 0, draft written           |
| AC-7  | ✅     | `test_ac7_schema_gate_fail_fast` — wrong/absent version → exit 1, no drafts     |
| AC-8  | ✅     | `test_ac8_dominant_only_vs_all_clusters` — 1 file vs one-per-cluster            |
| AC-9  | ✅     | `test_ac9_empty_triage` — null dominant → no drafts, exit 0                     |
| AC-10 | ✅     | `test_ac10_atomic_write_cleanup` — `os.replace` fail → no partial, temp cleaned |
| AC-11 | ✅     | `test_ac11_dry_run_no_client_calls` — injected client untouched in dry-run      |
| AC-12 | ✅     | `test_ac12_create_skips_existing` + `..._files_new_issue` (skip + create + URL) |
| AC-13 | ✅     | `test_ac13_offline_guarantee` + `..._ghcli_never_instantiated_in_dry_run`       |
| AC-14 | ✅     | `test_ac14_console_script_and_help` + verified `uv run rag-issues --help`       |
| AC-15 | ✅     | `test_ac15_adr_exists_and_linked` — ADR-0009 sections + README index row        |

## Knowledge Capture Suggestions

This phase produced the reusable, hard-won knowledge the Sprint-Wide Knowledge Plan scheduled
for **after ADR-0009 lands** — which is now. Recommended as the next harness step:

| What was learned                                                                                                                                                            | Suggested KB domain | Action                                                                                                                |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Triage cluster → GitHub Issue: body-marker fingerprint + pre-create search idempotency, `gh`-CLI-vs-REST seam, dry-run/`--create` safety contract, best-effort dedup limits | `rag-eval`          | `/update-kb rag-eval` — add a `triage-to-issues` pattern (and optionally a `failure-triage` concept), citing ADR-0009 |

## KB Staleness

None. Changed files touch no concept that an existing KB documents as an API/enum/constraint.
`rag-eval` (`eval-record-schema`) and `observability` (`failure-taxonomy`) describe the upstream
`EvalRecord`/taxonomy that Phase 15 only consumes transitively via `triage.json` — unchanged. No
GitHub-integration domain exists yet (correctly deferred to the capture step above).

## ADR

Recorded this phase — `docs/adr/0009-triage-to-issues.md` (`accepted`, 2026-06-02), the
`gh`-CLI-vs-REST + body-marker idempotency + dry-run safety decision. The review also backfilled
the pre-existing gap where **ADR-0008 was missing from the `docs/adr/README.md` index**. No
outstanding ADR debt.

## Suggested Next Steps

1. **Open the PR** for `sprint-5/phase-15-triage-to-issues` → `main` (CI re-runs `make lint test`
   - smoke); merge when green.
2. **`/update-kb rag-eval`** — land the `triage-to-issues` pattern now that ADR-0009 exists (the
   scheduled post-ADR KB work).
3. Then **`/brainstorm sprint-5/phase-16-phoenix-enrichment`** — the independent legibility
   thread (the sprint's flex phase), or `/sprint-close sprint-5` if 16 is cut.
4. _(Personal)_ Nudge the Carreira track `estudos/enterprise_rag_ops/sprint-5.md` — Phase 15 shipped.
