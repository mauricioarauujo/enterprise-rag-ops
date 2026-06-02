# Review: sprint-4/phase-10-gemini-generator — Third Generator (GeminiGenerator)

**Branch:** `sprint-4/phase-10-gemini-generator` | **Date:** 2026-06-01 | **Verdict:** ✅ READY

## Summary

`gemini-2.5-flash-lite` is added as a third generator-under-test behind the proven
`Generator` seam — localized to a new file + a factory line + a config Literal + a price
entry, with the judge path untouched (independence is structural). Two real defects
surfaced only on the live wire (Gemini rejects `additionalProperties`; the SDK default
retry exhausted on a 503) and were fixed; the full 3-way sweep then completed. The
code-reviewer returned READY; its two non-blocking findings are applied.

## Mechanical Checks

| Step   | Status | Notes                                          |
| ------ | ------ | ---------------------------------------------- |
| Format | PASS   | pre-commit `make format` clean                 |
| Lint   | PASS   | ruff + prettier                                |
| Tests  | PASS   | 226 passed, 17 deselected (5 new Gemini tests) |

## Issues

<details>
<summary>⚠️ Gemini rejects <code>additionalProperties</code> (live 400) — FIXED</summary>

`gemini_generator.py` — `AnswerWithSources(extra="forbid")` emits `additionalProperties`,
which Gemini's schema dialect rejects (`400 INVALID_ARGUMENT`). **Fixed:** hand the SDK an
open mirror `_GeminiResponseSchema` (same fields, no `extra="forbid"`); the closed contract
is still enforced our side via `AnswerWithSources.model_validate_json` (FR-3). Regression
test asserts no `additionalProperties` in the schema sent.

</details>

<details>
<summary>⚠️ Sweep died on transient <code>503 UNAVAILABLE</code> (SDK default 5 retries) — FIXED</summary>

`gemini_generator.py` — the SDK default retry exhausted on a demand spike after ~34
questions. **Fixed:** `genai.Client(http_options=HttpOptions(timeout=120_000,
retry_options=HttpRetryOptions(attempts=8, http_status_codes=[429,500,502,503,504])))`,
mirroring the Anthropic generator's `max_retries=8, timeout=120`. The re-run completed all 500. Applied only when `client is None` (injected test clients skip it — correct).

</details>

<details>
<summary>⚠️ AC-1 missing <code>latency_s &gt; 0.0</code> in the cassette test — FIXED</summary>

`tests/generation/test_gemini_generator.py` — DEFINE AC-1 lists `latency_s > 0.0`, but only
the offline test asserted it. **Fixed:** added `assert stats.latency_s > 0.0` to
`test_live_replay` (the path that times the real call).

</details>

<details>
<summary>⚠️ Open-mirror field drift not machine-checked — FIXED</summary>

`tests/generation/test_gemini_generator.py` — `_GeminiResponseSchema` could silently drift
from `AnswerWithSources` (a new field there would only fail at live-call time). **Fixed:**
the regression test now asserts
`set(config.response_schema.model_fields) == set(AnswerWithSources.model_fields)` — drift
fails at test time, not in production.

</details>

<details>
<summary>⚠️ <code>test_env_guard</code> catches broad <code>Exception</code> — accepted</summary>

`tests/generation/test_gemini_generator.py:160-173` — the "key present" branch constructs a
real client and `except Exception: pass`, which could mask a construction failure. Accepted
as-is: the test's purpose is the **guard** (no-key → `RuntimeError`), and a real client
construction with a dummy key may legitimately warn/fail on auth-metadata lookups. The
positive assertion (`pytest.fail` if `RuntimeError`) is the meaningful part. Non-blocking.

</details>

## Acceptance Criteria

| AC    | Status | Evidence                                                                                                     |
| ----- | ------ | ------------------------------------------------------------------------------------------------------------ |
| AC-1  | PASS   | `test_live_replay` (cassette): valid `AnswerWithSources` + `CallStats(system="google")`, tokens>0, latency>0 |
| AC-2  | PASS   | `test_offline_injected_client` — parse + extra-field `ValidationError` + open-schema guard                   |
| AC-3  | PASS   | `test_token_mapping` — output = candidates + thoughts; 4 cases incl. missing metadata                        |
| AC-4  | PASS   | `test_env_guard` — neither key → `RuntimeError` naming both                                                  |
| AC-5  | PASS   | `test_model_resolution` — default / `RAG_GEN_MODEL_GOOGLE` / explicit precedence                             |
| AC-6  | PASS   | `test_runner.py` — `system="google"` dispatches to `GeminiGenerator`                                         |
| AC-7  | PASS   | `test_config.py` — `system="google"` validates; `"gemini"` raises                                            |
| AC-8  | PASS   | `test_records.py` — `Price(0.10,0.40)` → non-None `compute_cost_usd`                                         |
| AC-9  | PASS   | `google-genai` imports after `uv sync`; gate green                                                           |
| AC-10 | PASS   | Independence structural — no `system`-keyed judge factory; `gemini-only.yaml` judge=OpenAI                   |
| AC-11 | PASS   | `make test` offline, no network/key; cassette committed + key-scrubbed                                       |
| AC-12 | PASS   | ADR-0005 amended (Google as 3rd family + independence + schema-dialect note)                                 |
| AC-13 | PASS   | 3-way sweep completed (manual/live): 500 Gemini records → merged 1499-record 3-way JSONL                     |
| AC-14 | PASS   | Diff touches only the NFR-6 files (+ the C-4 `conftest.py` filter); seam intact                              |

## Knowledge Capture Suggestions

| What was learned                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Suggested KB domain | Action                                                                                                                                                                                     |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Structured-output-per-provider divergence** — the same `AnswerWithSources` is forced three different ways: OpenAI `strict:true`, Anthropic forced tool-use, Gemini native `response_schema` **but with an open mirror** (Gemini rejects `additionalProperties`), all validated closed our side via `model_validate_json`. Plus the per-provider **retry/timeout hardening** pattern (`max_retries`/`HttpRetryOptions`) and the **cassette key-scrub-per-provider** lesson (`x-goog-api-key` + `?key=`). | `rag-generation`    | **`/new-kb rag-generation`** — the twice-deferred scaffold is finally ripe: 3 concrete providers make the multi-provider `Generator` pattern real. This is the strongest moment to pay it. |

## KB Staleness

| KB File                                   | What Changed                                          | Impact | Action                                                   |
| ----------------------------------------- | ----------------------------------------------------- | ------ | -------------------------------------------------------- |
| `rag-eval/patterns/multi-model-runner.md` | `_GENERATOR_FACTORY` gained `"google"`                | Low    | ✅ Fixed in this review (added `google` + Phase-10 note) |
| `rag-eval/concepts/stats-capture-seam.md` | `CallStats.system` is now `openai\|anthropic\|google` | Low    | ✅ Fixed                                                 |
| `rag-eval/concepts/eval-record-schema.md` | `gen_ai.system` values now include `google`           | Low    | ✅ Fixed                                                 |

## ADR

No new ADR. **ADR-0005 was amended** (provider matrix → 3rd generator family, independence
restated, schema-dialect note). The open-schema and retry findings are implementation
detail captured in the amendment + the code; they are not separate architectural decisions.

## Suggested Next Steps

1. **`/new-kb rag-generation`** before the PR (or fold into it) — capture the
   structured-output-per-provider + retry-hardening patterns while 3 providers are concrete.
   This finally pays the twice-deferred KB debt; recommended now.
2. **Open the PR** `sprint-4/phase-10-gemini-generator → main`.
3. **Phase 11 (README/results)** decides whether to **promote** the gitignored 3-way JSONL
   to the published baseline. The 3-way finding (abstention↔hallucination tradeoff: same
   ~24% correct, but Claude over-abstains/faithful vs Gemini under-abstains/hallucinates, at
   2.7× lower cost) is the spine of the Phase 12 writeup.
