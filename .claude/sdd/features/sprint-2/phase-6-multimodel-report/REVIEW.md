# Review: sprint-2/phase-6-multimodel-report — Multi-Model Runner & Baseline Report

**Branch:** `sprint-2/phase-6-multimodel-report` | **Date:** 2026-05-25 | **Verdict:** ✅ READY (all 8 issues fixed)

## Resolution (fixes applied 2026-05-25)

All eight issues below were fixed in this session; `make lint test` is green (**194 passed**, +1
new concurrency regression test) and the scrubbed cassette still replays offline.

- **#1** ADR-0004:35 reworded to a system-facing criterion (no time-budget/portfolio framing).
- **#2 + #8** VCR config hoisted to a new root `tests/conftest.py` that scrubs request credentials
  **and** identifying response headers (`before_record_response` — vcrpy 6 has no
  `filter_response_headers`); the two divergent local fixtures were removed, and the existing
  cassette was hand-scrubbed of `anthropic-organization-id` + `set-cookie`.
- **#3 + #5** `executor.map` result is now consumed so worker exceptions propagate; added
  `test_runner_concurrency_propagates_worker_exception`.
- **#4** cost accumulation, the `halt_run` flip, and the write-eligibility decision now happen under
  one `cost_lock`; `halt_run` is no longer read bare.
- **#5 (report k)** `k` is persisted on `EvalRecord` and read by the report (no hard-coded 10);
  table headers are now `@{k}`.
- **#6** ADR-0007 corrected (`retrieval_ranked_ids` = deduplicated doc-level IDs) + documents the new `k` field.
- **#7** report-test fixture expanded to all 10 categories with a 10-category assertion.

The original findings are retained below as the record of what was fixed.

## Summary

The runner/cost/report/CLI/Anthropic stack is well-built and the sequential baseline path
(the one `make eval-baseline` actually uses) is functionally correct: single-retriever reuse,
None→N/A propagation, the cost formula, and crash-safe per-question flushing all check out, and
all 193 tests pass offline with no key/network. Two **privacy/hygiene leaks in tracked files**
must be scrubbed before this branch goes public — a time-budget line in ADR-0004 and an Anthropic
org-id + session cookie baked into the cassette. One real correctness bug exists on the
Should-tier `--concurrency` path (silent exception loss). The published `results/baseline.{html,md}`
artifact (DESIGN step 7) is not in this branch yet — that maintainer run is gated on the cassette fix.

## Mechanical Checks

| Step   | Status | Notes                                                     |
| ------ | ------ | --------------------------------------------------------- |
| Format | PASS   | `All 97 files already formatted`                          |
| Lint   | PASS   | ruff + prettier clean                                     |
| Tests  | PASS   | `193 passed, 17 deselected` — offline, no key, no network |

## Issues

<details open>
<summary>🔴 <strong>1. Stranger-test leak: private time budget in a tracked public ADR</strong> — <code>docs/adr/0004-observability-tool.md:35</code></summary>

`- **Budget-conscious** (solo portfolio project, ~5h/week).` leaks the personal time budget and
career framing into a tracked public file. `CLAUDE.local.md`'s stranger test is explicit: time
budget and portfolio framing exist _for Mauricio_, not to help a stranger judge the _system_, so
they stay out of tracked files.

**Fix:** reword to a system-facing criterion, e.g.
`- **Budget-conscious**: self-hostable with minimal operational overhead; reviewable from a git clone with no running infra.`
(Line 29's "public MIT portfolio repo" is borderline — "public MIT repo" is verifiable/fine;
dropping "portfolio" is cleaner.)

</details>

<details open>
<summary>🔴 <strong>2. Cassette leaks Anthropic org-id + session cookie</strong> — <code>tests/eval/cassettes/anthropic_generator.yaml:108–116</code>, <code>tests/generation/test_anthropic_generator.py:95</code></summary>

The recorded response headers include `anthropic-organization-id: 7c0a0e59-bdbc-4a98-85e9-1e54c66c69da`
(a UUID that uniquely identifies the Anthropic account used to record) and a full
`set-cookie: _cfuvid=…` Cloudflare session token. Neither is needed for replay; both go public in a
tracked file. The VCR fixture filters only **request** headers (`x-api-key`, `authorization`) — there
is no response-header scrubbing.

**Fix:** add response-header filtering to the fixture and re-record (or manually scrub the YAML):

```python
vcr.VCR(
    cassette_library_dir="tests/eval/cassettes",
    record_mode=record_mode,
    filter_headers=["x-api-key", "authorization"],
    filter_response_headers=["anthropic-organization-id", "set-cookie", "cf-ray", "request-id"],
)
```

`request-id`/`traceresponse` are opaque (not account-identifying) — scrub for cleanliness but the
binding leaks are `anthropic-organization-id` and `set-cookie`.

</details>

<details>
<summary>⚠️ <strong>3. Concurrent runner swallows worker exceptions (silent incomplete JSONL)</strong> — <code>src/enterprise_rag_ops/eval/runner.py:208–210</code></summary>

`executor.map(process_one, questions)` returns a lazy iterator that is never consumed, so any
exception raised inside a worker thread is deferred into the (discarded) iterator and silently
dropped at `with`-block exit. A crashed worker under `--concurrency > 1` produces no exception, no
log, and a silently short JSONL while the run reports success. **Non-blocking** because the baseline
run uses the sequential default (`concurrency=1`, which re-raises correctly — verified by
`test_runner_flushes_jsonl_early_stop`) and `--concurrency` is Should-tier (FR-14). But the failure
mode (silent eval data loss) is exactly what this harness exists to prevent — fix now, it's one line:

```python
with ThreadPoolExecutor(max_workers=concurrency) as executor:
    for _ in executor.map(process_one, questions):
        pass
```

Then add a `test_runner.py` case: crashing generator + `concurrency=2` asserts the error propagates.

</details>

<details>
<summary>⚠️ <strong>4. <code>halt_run</code> / <code>total_cost_usd</code> read outside <code>cost_lock</code></strong> — <code>runner.py:111, 199–202</code></summary>

`halt_run` is written under `cost_lock` (line 172) but read bare (line 111); the write-guard at
199–202 evaluates `total_cost_usd - call_cost <= cost_ceiling_usd` under `write_lock`, not `cost_lock`,
so it can read a `total_cost_usd` another thread has since mutated. GIL masks this in practice and it's
Should-tier, but it's formally a race. **Fix:** read `halt_run` only inside `cost_lock` (or use a
`threading.Event`), and pass `call_cost` into the write guard rather than re-deriving from shared state.

</details>

<details>
<summary>⚠️ <strong>5. Report hard-codes <code>k=10</code>, ignoring <code>config.k</code></strong> — <code>src/enterprise_rag_ops/eval/report.py:94</code></summary>

`aggregate_retrieval_metrics(cat_qs, ranked_results, k=10)` uses a literal 10; `config.k` is never
threaded into `generate_report_data` / `render_report`, and `k` is not persisted on `EvalRecord`.
Correct for the baseline (`k: 10`), but a run with `k≠10` would silently mislabel the Recall@10 /
nDCG@10 columns. **Fix:** persist `k` on `EvalRecord`, or thread `k` through `render_report` from the CLI.

</details>

<details>
<summary>⚠️ <strong>6. ADR-0007 mislabels <code>retrieval_ranked_ids</code> as "chunk IDs"</strong> — <code>docs/adr/0007-eval-record-schema.md:52</code></summary>

The schema table says `retrieval_ranked_ids | list[str] | The chunk IDs returned by the retriever`,
but the runner stores **deduplicated doc-level IDs** (`deduplicate_ranked_ids` maps `chunk_id → doc_id`
via `split("::")[0]`). Since ADR-0007 is the schema SSoT, the description should read "deduplicated
doc-level IDs (the offline retrieval-metric input)". Docs-only.

</details>

<details>
<summary>⚠️ <strong>7. <code>test_report.py</code> under-asserts AC-9's 10-category breakdown</strong> — <code>tests/eval/test_report.py</code></summary>

AC-9 requires "all 10 question categories"; the fixture JSONL has only `basic` + `info_not_found`.
The N/A cell is asserted, but the loop is never exercised against a model with zero records in a
category (empty `cat_recs` → all-`None` metrics). **Fix:** expand the fixture to 10 categories and
assert 10 category rows render.

</details>

<details>
<summary>⚠️ <strong>8. Anthropic test defines a local VCR fixture + redundant <code>@pytest.mark.vcr</code></strong> — <code>tests/generation/test_anthropic_generator.py:86–117</code></summary>

The test wires its own `vcr_record` fixture instead of the project conftest fixture, and carries
both `@pytest.mark.vcr` and an explicit `vcr_record.use_cassette(...)` — two divergent VCR config
paths. Harmless today; consolidate onto the conftest fixture (and that's also where the response-header
filter from issue 2 should live).

</details>

## Acceptance Criteria

| AC                                                   | Status | Note                                                                                                                                   |
| ---------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1 EvalRecord round-trip, verdict-list exclusion   | ✅     | `test_records.py`                                                                                                                      |
| AC-2 per-question JSONL flush                        | ✅     | early-stop test asserts line count                                                                                                     |
| AC-3 CallStats + `*_with_stats`, Protocols untouched | ✅     | grep assertion + fake usage                                                                                                            |
| AC-4 AnthropicGenerator tool-use + RuntimeError      | ✅     | offline fake client                                                                                                                    |
| AC-5 cassette replay offline                         | ✅     | replays no-key/no-net — but leaks headers (issue 2)                                                                                    |
| AC-6 RunConfig parse / ValidationError               | ✅     | `test_config.py`                                                                                                                       |
| AC-7 retriever loaded once                           | ✅     | load-count assertion                                                                                                                   |
| AC-8 `rag-eval run` → both files                     | ✅     | `test_cli.py` stub run                                                                                                                 |
| AC-9 10-category + N/A                               | 🟡     | N/A ✅; 10-category under-asserted (issue 7)                                                                                           |
| AC-10 cost arithmetic incl. missing-price            | ✅     | parametrized `test_records.py`                                                                                                         |
| AC-11 fail-fast names `make build-index-gold`        | ✅     | runner guard + CLI catch                                                                                                               |
| AC-12 baseline.{html,md} un-gitignored + committed   | 🟡     | `.gitignore` negation ✅; files not committed (step 7 pending)                                                                         |
| AC-13 exit criterion <30 min                         | ⏳     | pending maintainer milestone run                                                                                                       |
| AC-14 ADR-0007 written                               | ✅     | proposed → accepted                                                                                                                    |
| AC-15 gpt-5-nano price verified                      | ⚠️     | ADR-0007 _asserts_ verified vs official OpenAI page — maintainer should re-confirm the $0.05/$0.40 figure is current before publishing |
| AC-16 cost-overrun guard                             | ✅     | `test_runner_cost_ceiling_overrun`                                                                                                     |
| AC-17 `--concurrency` crash-safe                     | 🟡     | happy path ✅; exception path swallows errors (issue 3)                                                                                |
| AC-18 `rag-eval report` re-render                    | ✅     | `test_cli.py`                                                                                                                          |
| AC-19 offline CI invariant                           | ✅     | 193 passed, no key/network                                                                                                             |

This branch delivers DESIGN steps 1–6. Step 7 (the one paid milestone run → commit
`results/baseline.{html,md}`) is the remaining maintainer action and is correctly _not_ in the diff.

## Knowledge Capture Suggestions

| What was learned                                                                                                                                               | Suggested KB domain           | Action                                                                |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------- |
| Eval-record JSONL schema, app-derived cost model (price-table-in-config), `CallStats`/`generate_with_stats` seam, the `string.Template` HTML+MD report pattern | `rag-eval`                    | `/update-kb rag-eval` (already sequenced post-phase in DEFINE/DESIGN) |
| VCR response-header scrubbing (`filter_response_headers`) for provider org-id/session cookies — request-only filtering is insufficient                         | `rag-eval` (cassette section) | fold into `/update-kb rag-eval`                                       |

## ADR

ADR-0007 was written this phase (no missing ADR). One content fix: the `retrieval_ranked_ids`
description (issue 6).

## Suggested Next Steps

1. **Fix the two 🔴 leaks before any push/PR** — reword `docs/adr/0004-observability-tool.md:35`;
   add `filter_response_headers` and re-record/scrub the cassette.
2. Fix the concurrency exception-swallowing one-liner (issue 3) + add the regression test, or
   document `--concurrency` as experimental.
3. Optional polish: thread `config.k` into the report (5), fix ADR-0007 wording (6), expand the
   report fixture to 10 categories (7), consolidate the VCR fixture (8).
4. Re-confirm the gpt-5-nano price (AC-15), then run `make build-index-gold` → `make eval-baseline`
   for the published baseline (DESIGN step 7) and commit `results/baseline.{html,md}`.
5. After the phase: `/update-kb rag-eval`.
