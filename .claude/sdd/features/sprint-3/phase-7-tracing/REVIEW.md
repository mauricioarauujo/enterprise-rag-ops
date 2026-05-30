# Review: sprint-3/phase-7-tracing — Phoenix Replay Exporter & ADR-0004 Acceptance

**Branch:** `sprint-3/phase-7-tracing` | **Date:** 2026-05-28 (initial) / 2026-05-30 (resolved) | **Verdict:** ✅ READY

## Summary

Mechanical gate is clean — `make lint test` passes (200 tests after regression test
was added). All six non-blocking findings from the initial review were applied. A
runtime defect surfaced at the live exit demo (`POST /` → 405 because
`register(endpoint=...)` was missing the OTLP-HTTP `/v1/traces` suffix) was diagnosed
against the running Phoenix server, fixed with a pure `split_endpoint` helper inside
the seam, and locked with an offline regression test. AC-11 was cleared via the
maintainer's exit-demo walk through a failed trace in the Phoenix UI. Ready to PR.

## Resolution log (2026-05-30)

- **6 non-blocking findings applied** in `chore(observability): apply /review polish`.
- **Runtime endpoint defect** fixed in `fix(observability): normalize Phoenix endpoint
to OTLP-HTTP path` — `phoenix_client.split_endpoint(endpoint) -> (otlp_url, base_url)`
  ensures `register()` always gets `…/v1/traces` and `Client()` always gets the bare
  host; new offline test `test_split_endpoint_normalizes_otlp_and_base_url` covers bare
  host, trailing slash, pre-suffixed URL, and non-default host:port.
- **Live exit demo re-run:** 999 traces + 3943 scores ingested cleanly; zero 405s,
  zero annotation 404s.
- **AC-11 cleared by maintainer walk:** opened a failed trace in the Phoenix UI,
  navigated the four-span tree (chain → retriever / generation / judge), read the
  per-span annotations, and identified the failure mode from the span tree + scores.

## Mechanical Checks

| Step     | Status | Notes                                                              |
| -------- | ------ | ------------------------------------------------------------------ |
| Format   | PASS   | `ruff format --check` clean over `src`/`tests`                     |
| Lint     | PASS   | `ruff check` clean; `prettier --check` clean                       |
| Tests    | PASS   | 199 passed / 17 deselected (`-m "not corpus and not smoke"`), 5.6s |
| Offline? | PASS   | New tests use `FakeScoreSink` + 2-record JSONL; no network/Phoenix |

## Issues

<details>
<summary>⚠️ <code>docs/adr/0004-observability-tool.md:1</code> — ADR title still says "Langfuse"</summary>

The H1 and Decision body still read `Langfuse Self-Hosted, OTEL-Native Records` /
`Primary tool: Langfuse (self-hosted)`. The new `## Acceptance Note` at the bottom
correctly records Phoenix was deployed with hardware rationale, which is exactly what
DEFINE FR-9 / AC-9 specified. But a reader landing on the ADR sees "Langfuse" in the
title and may not scroll to the bottom note.

**Fix:** Either tighten the title to e.g.
`# ADR 0004: Observability & Cost-Tracking Tool — OTEL-Native Records (Phoenix deployed)`
or add a one-line preamble under the H1 before `## Status` pointing to the Acceptance
Note. Body's "Primary tool: Langfuse" line can stay as historical context once the title
or preamble makes the deployed reality unambiguous.

</details>

<details>
<summary>⚠️ <code>infra/phoenix/docker-compose.yml:1</code> — obsolete <code>version</code> key</summary>

`version: "3.8"` has been ignored by Docker Compose v2+ and emits a deprecation warning
on recent Docker Desktop versions. No functional impact today; will become noise or a
hard error later.

**Fix:** Delete line 1 entirely (`version: "3.8"` + blank line).

</details>

<details>
<summary>⚠️ <code>pyproject.toml:21</code> — <code>arize-phoenix-client</code> has no version constraint</summary>

`arize-phoenix-otel>=0.16.0` carries a lower bound; `arize-phoenix-client` carries none.
The verified write-back path (`Client().spans.log_span_annotations_dataframe`) exists in
the currently-installed `2.7.0`, but a future `uv sync` that resolves to an older or
incompatible major would silently break the exporter at runtime. NFR-4 in DEFINE
explicitly flagged dep pinning as a `/design`-time item.

**Fix:**

```toml
"arize-phoenix-client>=2.7.0",
```

(Upper bound optional per house convention; lower bound protects against regression.)

</details>

<details>
<summary>⚠️ <code>src/enterprise_rag_ops/observability/attributes.py:88-146</code> — spec drift: <code>explanation</code> column dropped</summary>

DEFINE FR-5 and DESIGN line 191 both list `explanation (str)` as an optional column in
the score-row contract. `build_score_rows` omits it. Phoenix accepts rows without it, so
this is not a runtime bug — but it is a doc/code drift a future maintainer will hit.

**Fix:** Drop `explanation` from DEFINE/DESIGN (preferred — pre-computed scores have no
natural explanation), or add `"explanation": ""` to each row dict.

</details>

<details>
<summary>⚠️ <code>.claude/sdd/features/sprint-3/phase-7-tracing/DEFINE.md:217</code> — stranger-test drift: "~5h budget"</summary>

NFR-6 reads `(Budget — ~5h) — The phase fits a ~5h budget`. The SDD directory is
tracked. "~5h budget" is personal time allocation (Mauricio's weekly capacity), not a
system property — a stranger learns nothing about the system from it. Pattern matches a
finding from an earlier sprint review.

**Fix:** Restate NFR-6 as a scope constraint (e.g. `NFR-6 (Minimal scope — one module +
CLI + infra)`), or drop the line. Code/tests/ADRs are unaffected; this is SDD doc
hygiene.

</details>

<details>
<summary>⚠️ <code>src/enterprise_rag_ops/observability/phoenix_client.py:77</code> — <code>reset_project</code> swallows all exceptions</summary>

The bare `except Exception` is intentional for the "project doesn't exist yet" /
"undeletable default" cases — but it also masks auth failures and network errors. If a
real deletion silently fails, a re-run produces duplicate traces (defeats FR-4
idempotency guarantee).

**Fix (low-risk):** narrow the except to the specific 404-style error the Phoenix
client raises for "project not found", and let auth/network errors propagate. Acceptable
to defer — the `make trace-reset` volume-wipe fallback (DESIGN § Reset-and-replay)
already guarantees clean state for the exit demo. Worth a `# TODO(observability)`
comment naming the seam.

</details>

**Cleared during review (parent-flagged risks, confirmed non-issues):**

- `openinference_span_kind="chain"` (lowercase) — `OITracer.start_as_current_span` accepts
  lowercase Literal values and normalises to uppercase `'CHAIN'` / `'LLM'` etc. on the
  written attribute. Code is correct as-is. (code-reviewer verified live.)
- `trace.get_tracer("replay-exporter", tracer_provider=self.provider)` vs Phoenix-idiomatic
  `self.provider.get_tracer(__name__)` — both return the same `OITracer` instance because
  OTEL's `trace.get_tracer(..., tracer_provider=X)` delegates to `X.get_tracer(...)`.
  Functionally identical. (code-reviewer verified type equality.)

## Acceptance Criteria

| AC  | Status | Evidence                                                                                                                                                                                                                                                   |
| --- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | ✅     | `infra/phoenix/docker-compose.yml`: single `arizephoenix/phoenix:version-15.0.0`, ports 6006+4317, `PHOENIX_WORKING_DIR=/mnt/data`, named volume. `make trace-up` defined.                                                                                 |
| 2   | ✅     | `replay_jsonl` parses each line into `EvalRecord` and emits one trace per record; `summary.traces_exported == 2` over the 2-record fixture.                                                                                                                |
| 3   | ✅     | Four-span tree (CHAIN→RETRIEVER, LLM gen, LLM judge) with parent_id=chain; `retrieval.documents.{i}.{id,rank}` only — no `content`/`score`.                                                                                                                |
| 4   | ✅     | `sink.reset_project(project)` called before any `start_span`; second `replay_jsonl` re-resets (`projects_reset == [project, project]`).                                                                                                                    |
| 5   | ✅     | Scores keyed on captured `span_id` per metric; `None` cost omitted (record 2 gen + total); `None` `fact_recall`/`faithfulness_ratio` skipped (record 2).                                                                                                   |
| 6   | ✅     | CLI flags `--results`/`--endpoint`/`--project`/`--dry-run` parse; endpoint precedence flag > env > `http://localhost:6006` (offline tests cover all 3).                                                                                                    |
| 7   | ✅     | `make export-traces` runs `uv run rag-export-traces --results $(RESULTS_FILE)` with default `results/baseline.jsonl`; in `.PHONY`.                                                                                                                         |
| 8   | ✅     | `.gitignore` adds `!results/baseline.jsonl`; `results/baseline.jsonl` (1.3 MB / 999 records) committed; run-specific JSONL still gitignored.                                                                                                               |
| 9   | ✅     | Status is `accepted`; title + preamble now name Phoenix as the deployed tool; Acceptance Note records Phoenix + hardware rationale + pinned tag + unchanged wire format.                                                                                   |
| 10  | ✅     | `tests/observability/test_exporter.py` (5 tests, +1 regression for `split_endpoint`) passes offline; no cassette, no Phoenix, no key.                                                                                                                      |
| 11  | ✅     | Exit demo run on 2026-05-30 — `make trace-up && make export-traces` ingested 999 traces + 3943 scores from the committed baseline; maintainer walked a failed trace in the Phoenix UI and read the failure mode from the span tree + attached annotations. |
| 12  | ✅     | Diff touches no file under `src/enterprise_rag_ops/eval/`, no `configs/`, no Phase 6 module. Only `observability/` + `infra/phoenix/` + config files + ADR.                                                                                                |
| 13  | ✅     | `--dry-run` parses without sink calls; `test_exporter_dry_run` asserts zero spans/resets/scores.                                                                                                                                                           |
| 14  | ✅     | `attributes.py:39-44` documents the `--enrich-from-index` seam in a comment; no LanceDB/BM25 import in `observability/`.                                                                                                                                   |

**14/14 ✅** — all acceptance criteria cleared.

## Knowledge Capture Suggestions

| What was learned                                                                                                                                               | Suggested KB domain | Action                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------- |
| Phoenix replay-exporter pattern: vendor seam (`phoenix_client.py`) + pure attribute mapping (`attributes.py`) + thin orchestrator (`exporter.py`)              | `observability`     | `/new-kb observability` |
| OTEL/OpenInference span-attribute mapping: CHAIN→RETRIEVER→LLM(gen)→LLM(judge); `retrieval.documents.{i}.document.{id,rank}` flattening; `None`-safe cost rule | `observability`     | concept                 |
| Reset-and-replay idempotency (Phoenix has no upsert-by-seed; clear project + capture span_id in-process)                                                       | `observability`     | concept                 |
| Score write-back via `Client().spans.log_span_annotations_dataframe(annotator_kind="CODE")` keyed on captured `span_id` (vs deprecated `log_evaluations`)      | `observability`     | pattern                 |
| `OITracer` accepts lowercase Literal `openinference_span_kind` values and normalises to uppercase — non-obvious from public docs                               | `observability`     | concept gotcha          |

**Recommended:** run `/new-kb observability` at sprint-close per SPRINT.md (deferred
until ADR-0004 was accepted, which it now is). Five concrete concepts/patterns above
seed the domain.

## KB Staleness

No existing KB domain documents Phoenix or the exporter (`observability` does not yet
exist in `_index.yaml`). `rag-eval` covers `EvalRecord`/`CallStats` (the exporter's
read-only input contract), which Phase 7 did not change — no staleness there. Nothing
to update in `rag-retrieval` or `rag-generation`.

## ADR

No new ADR required. ADR-0004 was the planned acceptance and is accepted with title +
preamble now naming Phoenix unambiguously. No architectural decision in Phase 7 falls
outside ADR-0004's boundary: the exporter pattern, span-tree shape, and
reset-and-replay idempotency are implementation details inside the boundary ADR-0004
already governs. The fail-loud price-validation backlog (ADR-0007 amendment) is
explicitly out of scope per DEFINE.

## Suggested Next Steps

1. **Open the PR** for `sprint-3/phase-7-tracing → main` (two commits ready:
   `chore(observability): apply /review polish` + `fix(observability): normalize
Phoenix endpoint to OTLP-HTTP path`).
2. **At sprint-close:** run `/new-kb observability` to capture the five concepts above.

### Follow-ups logged (not for this PR)

- Phoenix `Total Cost` and token-usage dashboard panels render as $0 / empty because
  Phoenix v15's rollup reads the old OTel attribute names (`gen_ai.usage.prompt_cost`
  / `prompt_tokens`); we write app-derived `cost_usd` and the new OTel-GenAI names
  (`input_tokens` / `output_tokens`). Per-trace `cost_usd_total` is correct on the
  chain span. Two fixes possible at Phase 8: dual-write the legacy attribute names,
  or build a custom cost dashboard reading the JSONL.
- `Trace Latency` in Metrics reflects replay latency (~ms), not real inference
  latency (`latency_s` lives in the per-span attribute). Worth a docstring note on
  the exporter if Phase 8 surfaces a latency dashboard.
