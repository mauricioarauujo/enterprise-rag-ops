# Review: sprint-6/phase-19-full-trace-hydration — Re-run + Hydrate the Full Trace (close Sprint 6)

**Branch:** `sprint-6/phase-19-full-trace-hydration` | **Date:** 2026-06-03 | **Verdict:** ✅ READY

> **Update 2026-06-03 (post-fix):** all five issues from the initial review are resolved. The
> blocking I-1 was fixed operationally (`rag-classify` re-run + report re-render — see below);
> I-2–I-5 were fixed in code. `make lint test` is **green** (292 passed). AC-10 (the sprint-close
> gate) was **verified in Phoenix** on trace `qst_0498` (evidence under Acceptance Criteria). The
> DESIGN runbook was patched to add the missing `rag-classify` + `--enrich-*` export steps. Original
> findings are preserved below for the record. **All 12 ACs pass.**

## Summary

The code is excellent — the Option-A seam (`RawCall` 3rd return), the defensive per-provider
serializers, the `BronzeWriter`, and the judge verdict-hydration mapper are all correct, well-tested,
and faithful to the DESIGN. Bronze is verified locally (3000 files, all JSON-valid, no secrets) and the
core deliverable landed (`per_fact` on all 1500 records, `per_citation` on 860). The initial review
caught one blocker — the re-published `results/baseline.jsonl` was written by `rag-eval run` _without_
the follow-up `rag-classify` step, so `failure_mode` was `None` on all 1500 records, failing two
pre-existing tests and the `make lint test` gate. **This has since been fixed** by re-classifying the
baseline and re-rendering the report; the gate is green.

## Mechanical Checks

| Step   | Status          | Notes                                                                                           |
| ------ | --------------- | ----------------------------------------------------------------------------------------------- |
| Format | PASS            | `ruff format` + prettier clean after re-render                                                  |
| Lint   | PASS            | `ruff check` all checks passed                                                                  |
| Tests  | PASS (post-fix) | 292 passed, 17 deselected. _Initial run:_ 2 failed (I-1, the unclassified baseline) — now fixed |

## Issues

<details>
<summary>🔴→✅ <strong>I-1 (FIXED) — Re-published <code>baseline.jsonl</code> had <code>failure_mode: None</code> on all 1500 records → CI gate failed</strong></summary>

**Resolution applied 2026-06-03:** ran `rag-classify --results results/baseline.jsonl` (deterministic,
no LLM cost) → `failure_mode` now populated (`abstention_error: 575, incomplete: 449, correct: 351,
hallucination: 88, retrieval_miss: 37` = 1500); re-rendered `results/baseline.{html,md}`; `make lint test`
green (292 passed). The two pre-existing tests pass again. **Follow-up still open:** add the
`rag-classify` step to the DESIGN operational runbook so the next re-run doesn't repeat the miss.

**Where:** `results/baseline.jsonl` (committed `3fae613`); fails
`tests/dashboard/test_data.py::test_single_model_structure:87` and
`tests/eval/test_inspect_cli.py::test_ac8_gate_verification:185`.

**What happened.** The operational re-run (FR-11) ran `rag-eval run` and re-rendered the report, but
the runbook (DESIGN §Operational runbook) omits the `rag-classify` step. The runner never sets
`failure_mode` — it's populated by a separate `rag-classify` pass (`dashboard/data.py:68`:
"populated by rag-classify"). The **old** baseline on `main` had it populated
(`correct: 345, abstention_error: 583, hallucination: 79, incomplete: 455, retrieval_miss: 37`); the
new one is `{None: 1500}`. Both failing tests are **pre-existing** (not in this branch's diff) and
passed on `main` — they read the committed `results/baseline.jsonl` and assert the presence of
classified / `claude-haiku abstention_error` records. The full re-run dropped that column.

**Why blocking.** `make lint test` is the real gate (AGENTS.md §Implement Contract step 5; also CI on
PR). It is red. AC-12 fails.

**Fix** (operational, no LLM cost — `rag-classify` is deterministic, derives the mode from metrics
already in each record; needs HF connectivity only to load gold questions):

```bash
uv run rag-classify --results results/baseline.jsonl          # writes failure_mode back in place
uv run rag-eval report --results results/baseline.jsonl       # re-render baseline.{html,md}
make lint test                                                # confirm green
git add results/baseline.jsonl results/baseline.html results/baseline.md && git commit
```

Then add a `rag-classify` step to the DESIGN runbook so the next re-run doesn't repeat the miss.

</details>

<details>
<summary>⚠️→✅ I-2 (FIXED) — AC-8 no-bronze assertion used a CWD-relative path, not <code>tmp_path</code></summary>

**Was:** `tests/eval/test_runner.py:527` checked a CWD-relative `Path("data/raw_eval")` while the
`persist_bronze=True` half asserted under `tmp_path` — asymmetric, couldn't catch a leaking writer.

**Fix:** moved the `BronzeWriter.__init__` root monkeypatch _before both_ runs so the no-bronze
assertion now inspects `tmp_path / "raw_eval" / "test_run_no_bronze"` (the exact place a leaking
writer would write). Symmetric with the persist=True assertion.

</details>

<details>
<summary>⚠️→✅ I-3 (FIXED) — Dead <code>judge_raw is not None</code> guard in the runner</summary>

**Was:** `src/enterprise_rag_ops/eval/runner.py:276` — `judge_raw` is never `None` (the judge always
runs), so the guard was dead and misleading.

**Fix:** removed the guard; the judge bronze write is now unconditional, with a comment noting the
judge always runs (unlike generation, which is skipped on a retrieval abstain).

</details>

<details>
<summary>⚠️→✅ I-4 (FIXED) — <code>_serialize_response</code> duplicated verbatim across two modules</summary>

**Was:** identical OpenAI-shape serializer in `generation/openai_generator.py` and
`eval/openai_judge.py` — risked silent divergence.

**Fix:** `openai_judge.py` now imports `_serialize_response` from `openai_generator` (one source of
truth for the shared OpenAI `ChatCompletion` shape; eval→generation coupling already exists). Removed
the duplicate (~60 lines) and the now-unused `Any` import.

</details>

<details>
<summary>⚠️→✅ I-5 (FIXED) — AC-8 runner test did not assert "no extra gen/judge calls"</summary>

**Was:** the `persist_bronze` integration test checked files-written + JSONL-identical but not the
DEFINE AC-8 "no additional gen/judge call per question" clause.

**Fix:** wrapped the stubs in call-counting subclasses; after the persist=True run the test now asserts
exactly one generator and one judge call (counters reset between runs).

</details>

## Acceptance Criteria

| AC    | Status | Notes                                                                                                                                                                      |
| ----- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1  | ✅     | Protocols unchanged (`interfaces.py` not in diff); each `*_with_stats` returns `RawCall` 3rd element                                                                       |
| AC-2  | ✅     | Defensive serializers; `model_dump` fast path + manual fallback; `_serialization_error` catch-all, never raises                                                            |
| AC-3  | ✅     | `StubGenerator`/`StubJudge` emit minimal JSON-able `RawCall`; plain `generate`/`judge` return existing types                                                               |
| AC-4  | ✅     | Key scheme `{run_id}/{qid}__{model}__{call_type}.json`; `"w"`-mode overwrite idempotency                                                                                   |
| AC-5  | ✅     | Own `threading.Lock`; per-file flush; thread test covered                                                                                                                  |
| AC-6  | ✅     | `run_id` with `/`, `os.sep`, `..` (and empty) → `ValueError`                                                                                                               |
| AC-7  | ✅     | Hydration shape `fact: X -> absent` / `citation: d1 -> unsupported`; `text/plain`; omitted when both None/empty (a/b/c)                                                    |
| AC-8  | ✅     | `persist_bronze: bool = False`; wired in runner; JSONL byte-identical; call-count now asserted (I-5 fixed)                                                                 |
| AC-9  | ✅     | gold verdicts ✅ (per_fact 1500/1500, per_citation 860); bronze ✅ (3000 files, JSON-valid, **no secrets**); report republished ✅; failure_mode re-classified (I-1 fixed) |
| AC-10 | ✅     | **Verified 2026-06-03** on trace `qst_0498` — full chain legible in the Phoenix Info tab (evidence below)                                                                  |
| AC-11 | ✅     | `.gitignore` has `data/raw_eval/`; no Protocol/`records.py`/dashboard change; no `--enrich-from-bronze`; backward-compat holds                                             |
| AC-12 | ✅     | `make lint test` green — 292 passed (post-fix)                                                                                                                             |

**Privacy (FR-8/NFR-4) — verified clean.** A keyword scan over all 3000 bronze files flagged 101
"secret-like" hits; every one is benchmark _content_ (`...ri`**`sk-`**`based...`, "**authorization**
failures" in source docs), not a credential. The Gemini `model_dump` fast path captures
`sdk_http_response`, but it holds only **response** headers (`x-gemini-service-tier`, `content-type`,
`date`, …) with `body: null` — no request auth header, no API key. Bronze is gitignored regardless
(defense-in-depth).

**AC-10 evidence (verified 2026-06-03).** Exported with
`rag-export-traces --results results/baseline.jsonl --enrich-from-questions --enrich-from-index`
(both `--enrich-*` flags required; `make export-traces` omits them — folded into the DESIGN runbook).
Inspected trace **`qst_0498`** (gemini-2.5-flash-lite generation; category `info_not_found`) in the
Phoenix Info tab — the full chain reads end-to-end:

- **chain** → `input.value` = the question ("In the batching SLO tier benchmark methodology, what are
  the exact Redwood metering coefficients…") — Phase 17 + `--enrich-from-questions`.
- **retriever** → `retrieval.documents.0.document.content` = retrieved doc body ("## Overview This page
  specifies the dashboards…") — Phase 16 + `--enrich-from-index`.
- **generation** → `output.value` = the model answer ("…are not specified in the provided documents.
  However…") — Phase 17.
- **judge** → `output.value` = **the Phase-19 verdict**: `fact: … -> present`, `citation: dsid_008b… ->
unsupported`, `citation: dsid_0009… -> unsupported`; `output.mime_type: text/plain`. The judge span's
  own attributes correctly show `gen_ai.system: openai` / `gpt-5-nano` (judge is always OpenAI, even on
  a Gemini generation).

Two **cosmetic** Phoenix-widget artifacts noted (neither is a Phase-19 regression; both pre-exist from
Sprint 3 and are now backlogged LOW in `docs/planning/roadmap.md`): the header `Total Cost $0` (Phoenix's
native cost widget reads OpenInference `llm.token_count.*`; we emit OTEL `gen_ai.usage.*` + custom
`cost_usd` — real cost is on the attributes) and `Latency ~18ms` (the replay duration, not the real
`latency_s` of ~23s judge / ~1.2s gen). The sprint-6 goal — "a failed trace explains itself end-to-end" —
is met.

## Knowledge Capture Suggestions

| What was learned                                                                                                                                                                                        | Suggested KB domain | Action                                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------- |
| Raw-payload serialization across 3 divergent SDK response shapes (pydantic `model_dump(mode="json")` fast path + defensive manual fallback; Gemini fast path also captures `sdk_http_response` headers) | `rag-generation`    | `/update-kb rag-generation`                           |
| `RawCall` transient-transport pattern (3rd off-Protocol return, kept off gold per ADR-0007) + `BronzeWriter` (key/idempotency/own-lock/flush) coexisting with the runner's `ThreadPoolExecutor` locks   | `rag-eval`          | `/update-kb rag-eval` (`stats-capture-seam`)          |
| Judge verdict-reasoning hydration onto the judge span (`output.value` `text/plain`, guarded omit)                                                                                                       | `observability`     | `/update-kb observability` (`span-attribute-mapping`) |

These are **deferred by design** to the Sprint-Wide Knowledge Plan (per SPRINT.md / DEFINE §Users),
not Phase-19 gaps — run them at sprint-close.

## KB Staleness

None. The changed APIs (`*_with_stats` now 3-tuple, new `BronzeWriter`, judge `output.value`) are
_new_ surface the KB hasn't documented yet (captured above), not contradictions of existing KB
content. The deferred `/update-kb` runs will fold them in.

## ADR

No new ADR needed. ADR-0010 (ratified Phase 18) is the contract this phase **builds** — the seam is
the change it already anticipates ("built + wired + gitignored in Phase 19"). One small undocumented
nuance worth a line when `rag-generation` KB is refreshed: the live Gemini path serializes via the
`model_dump` fast path, which yields a _richer_ payload (incl. `sdk_http_response` response headers)
than the DESIGN's enumerated manual-fallback fields — acceptable for a raw archive, no decision change.

## Suggested Next Steps

1. ✅ **I-1–I-5 fixed** — baseline re-classified + report re-rendered; the four code nits applied;
   `make lint test` green (292 passed).
2. ✅ **AC-10 verified** in Phoenix on trace `qst_0498` (evidence under Acceptance Criteria).
3. ✅ **Runbook patched** — `rag-classify` + the `--enrich-*` export flags added to the DESIGN
   operational runbook so the next re-run doesn't drop `failure_mode` again.
4. ✅ **Backlog updated** — Phoenix native-widget fidelity (cost `$0` + replay latency) logged LOW/
   cosmetic in `docs/planning/roadmap.md`.
5. **Commit** the phase (baseline `{jsonl,html,md}` + `runner.py` + `openai_judge.py` + `test_runner.py`
   - DESIGN + REVIEW), then open the PR and `/sprint-close sprint-6`.
