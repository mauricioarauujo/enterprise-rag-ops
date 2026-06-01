# DESIGN: sprint-4/phase-10-gemini-generator — Third Generator (GeminiGenerator)

**Sprint/Phase:** sprint-4/phase-10-gemini-generator | **Date:** 2026-06-01

This DESIGN is the **cross-tool IMPLEMENT CONTRACT** (implement runs in Antigravity /
Gemini). The manifest, the `gemini_generator.py` skeleton, the factory/config/YAML diffs,
and the ADR amendment below are prescriptive enough that the executor needs no extra
context beyond this file, `DEFINE.md`, and the named source files.

---

## Architecture

`GeminiGenerator` is a **third `Generator` implementation behind the already-proven seam**
(`generation/interfaces.py`, the `Generator` Protocol). It is a structural sibling of
`OpenAIGenerator` and `AnthropicGenerator`: same constructor shape (`model`, `client`),
same `generate` → `generate_with_stats` delegation, same `CallStats` return. Nothing in
the seam, runner internals, judge, records schema, or observability changes.

**Wiring path (generation only):**

```
configs/baseline.yaml  models[].system = "google"
        │  (ModelConfig.system: Literal["openai","anthropic","google"])
        ▼
eval/runner.py  _GENERATOR_FACTORY["google"] = GeminiGenerator
        │  gen_factory.get(model.system) → GeminiGenerator
        ▼
GeminiGenerator(model=model.model_id)        # real GEMINI_API_KEY / GOOGLE_API_KEY
        │  .generate_with_stats(ctx_chunks, question)
        ▼
google.genai client.models.generate_content(
        model, contents=build_user_prompt(...),
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AnswerWithSources,
            system_instruction=build_system_prompt()))
        │  AnswerWithSources.model_validate_json(resp.text)   # extra="forbid" enforced our side
        ▼
(AnswerWithSources, CallStats(system="google", input_tokens, output_tokens, latency_s, model))
```

**Data flow is identical to the other two generators** — same shared prompt bytes
(`build_system_prompt` / `build_user_prompt`), same `AnswerWithSources` output schema, same
`CallStats` shape consumed downstream by `compute_cost_usd` and the `EvalRecord`.

**Independence is structural, not a guard (NFR-1 / AC-10):** the judge slot is resolved in
`runner.py` from `RunConfig.judge_model` (a plain string) through `OpenAIJudge` only. There
is **no `system`-keyed judge factory**. Adding `"google"` to the _generator_ factory cannot
make Gemini a judge, because the judge path never reads `system`. This phase adds **no**
Gemini-judge Literal, factory key, or wiring. The `models` matrix may contain
`system="google"` while `judge_model` stays an OpenAI model id.

**Token-accounting nuance (cost-correctness — bake in verbatim):** Gemini 2.5 thinking
tokens are **billed as output** but are **NOT** included in `candidates_token_count`.
Therefore the cost-accurate output mapping is:

```
output_tokens = (candidates_token_count or 0) + (thoughts_token_count or 0)
input_tokens  = prompt_token_count or 0
```

read defensively with `getattr(..., 0)`. This never undercounts cost regardless of whether
thinking is enabled. (Disabling thinking via `ThinkingConfig(thinking_budget=0)` is a
documented _alternative_, not adopted — the defensive sum is correct in all thinking states
and keeps the generator prompt-agnostic.) This is a **deliberate deviation** from the
DEFINE FR-4 wording (which only names `candidates_token_count`); see the Consistency Check
(C-1) — DEFINE's "(mirrors the Anthropic `usage` handling; missing metadata → 0, never
crash)" intent is preserved and cost-correctness is strengthened.

---

## File Manifest

Ordered by the phase convention (config/schema → core module → eval wiring → tests → docs).
Every file is owner **direct** (no specialist agent exists for the generation module).

| #   | File                                                    | Change          | Contains                                                                                                                                                                                                                                                                                                    | FRs / ACs                            | Owner  |
| --- | ------------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ------ |
| 1   | `pyproject.toml`                                        | MODIFY          | Add `"google-genai>=1.0,<2.0"` to `[project].dependencies`; `uv sync` to pin in lockfile.                                                                                                                                                                                                                   | FR-9, AC-9                           | direct |
| 2   | `src/enterprise_rag_ops/eval/config.py`                 | MODIFY          | Widen `ModelConfig.system` Literal to `Literal["openai", "anthropic", "google"]` (one-line change, line 22).                                                                                                                                                                                                | FR-8, AC-7                           | direct |
| 3   | `configs/baseline.yaml`                                 | MODIFY          | Add `prices` block for `gemini-2.5-flash-lite` (`0.10`/`0.40`); add the `models` entry (`system: "google"`) — the `models` add is the FR-13 Should, the price add is the FR-10 Must.                                                                                                                        | FR-10, FR-13, AC-8, AC-13            | direct |
| 4   | `src/enterprise_rag_ops/generation/gemini_generator.py` | CREATE          | `GeminiGenerator` class — full skeleton below. `DEFAULT_MODEL = "gemini-2.5-flash-lite"`, env guard (`GEMINI_API_KEY` / `GOOGLE_API_KEY`), `RAG_GEN_MODEL_GOOGLE` override, `generate` → `generate_with_stats`, `generate_content` call, token mapping, `CallStats(system="google")`, logging.              | FR-1..FR-6, AC-1..AC-5               | direct |
| 5   | `src/enterprise_rag_ops/eval/runner.py`                 | MODIFY          | Import `GeminiGenerator`; add `"google": GeminiGenerator` to `_GENERATOR_FACTORY`. Exact lines below.                                                                                                                                                                                                       | FR-7, AC-6                           | direct |
| 6   | `tests/generation/test_gemini_generator.py`             | CREATE          | Offline injected-client tests (parse + `extra="forbid"`), token-mapping test (incl. thoughts-token sum + missing-metadata→0), env-guard test, model-resolution test, and the `@pytest.mark.vcr` cassette replay test. Mirrors `test_anthropic_generator.py`. `tests/generation/__init__.py` already exists. | FR-1..FR-6, FR-11, AC-1..AC-5, AC-11 | direct |
| 7   | `tests/eval/cassettes/gemini_generator.yaml`            | CREATE          | One live-recorded cassette (record mode `once`, header-scrubbed by the root `conftest.py` VCR config). Replayed offline at mode `none`.                                                                                                                                                                     | FR-11, NFR-2, AC-1, AC-11            | direct |
| 8   | `tests/eval/test_runner.py`                             | MODIFY (extend) | Add one dispatch test: a `ModelConfig(system="google")` resolves through `_GENERATOR_FACTORY` to `GeminiGenerator` (and `openai`/`anthropic` still resolve). Uses the existing `generator_classes` injection / a direct factory-dict assertion — no network.                                                | FR-7, AC-6                           | direct |
| 9   | `tests/eval/test_config.py`                             | MODIFY (extend) | Add: `ModelConfig(system="google", model_id=...)` validates; `ModelConfig(system="gemini", ...)` raises `ValidationError`.                                                                                                                                                                                  | FR-8, AC-7                           | direct |
| 10  | `tests/eval/test_records.py`                            | MODIFY (extend) | Add a Gemini price-lookup test: a `Price(0.10, 0.40)` for `gemini-2.5-flash-lite` yields a non-None `compute_cost_usd` for a `CallStats(system="google")`. (Co-located with the existing `compute_cost_usd` tests in `test_records.py`.)                                                                    | FR-10, AC-8                          | direct |
| 11  | `docs/adr/0005-llm-provider-matrix.md`                  | MODIFY          | Append the amendment paragraph(s) drafted below — Google/`gemini-2.5-flash-lite` as 3rd generator family; restate Gemini-never-judges; note price source. No new ADR file.                                                                                                                                  | FR-12, AC-12                         | direct |

**Not modified (NFR-6 / AC-14 seam-locality guarantee):** `generation/interfaces.py`,
`runner.py` internals (only the factory dict + import line change), `eval/openai_judge.py`,
`eval/records.py` (`CallStats` / `EvalRecord` schema), and all of `observability/`.

**FR-14 (Could) decision:** the 3-way results JSONL is kept **gitignored and regenerable**
(`results/` is already gitignored per `.gitignore`). Do not commit a 500-question JSONL.
Document the regeneration recipe in the run note (AC-13). Rationale: large regenerable
artifact, matches the established `results/` convention; committing it would bloat the repo
and fail the stranger test (it is run-state, not system knowledge).

---

## The `GeminiGenerator` skeleton (write nearly verbatim)

`src/enterprise_rag_ops/generation/gemini_generator.py`:

```python
"""Google-Gemini-backed `Generator` using native JSON-schema structured output (FR-2).

Calls `client.models.generate_content` with a `GenerateContentConfig` carrying
`response_mime_type="application/json"` + `response_schema=AnswerWithSources`, so the
model returns schema-shaped JSON. Defensively re-validates through Pydantic
(`model_validate_json`) so any drift surfaces as a typed `ValidationError`, and
`extra="forbid"` is enforced our side regardless of provider enforcement.

Token accounting: Gemini 2.5 thinking tokens are billed as output but are NOT included
in `candidates_token_count`, so output = candidates + thoughts (read defensively) to
stay cost-accurate. Mirrors `anthropic_generator.py` / `openai_generator.py` structure.
"""

from __future__ import annotations

import logging
import os
import time

from google import genai
from google.genai import types

from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "gemini-2.5-flash-lite"


class GeminiGenerator:
    """`Generator` implementation using Google Gemini native JSON-schema output (FR-2).

    Default model is `gemini-2.5-flash-lite`; override via env var `RAG_GEN_MODEL_GOOGLE`.
    An explicit `model=` constructor arg wins over the env var. The client auto-reads
    `GEMINI_API_KEY` or `GOOGLE_API_KEY` (GOOGLE wins if both set); inject `client=` for
    offline tests.
    """

    def __init__(self, model: str | None = None, client: genai.Client | None = None) -> None:
        if client is None:
            if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                # Clean error, not an SDK stack trace (mirrors the Anthropic/OpenAI guard).
                raise RuntimeError(
                    "Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set — required for "
                    "GeminiGenerator. Set one in your shell or .env before running evaluation."
                )
            client = genai.Client()
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL_GOOGLE", DEFAULT_MODEL)

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        """Call Gemini and return a validated `AnswerWithSources`."""
        result, _ = self.generate_with_stats(context_chunks, question)
        return result

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats]:
        """Call Gemini and return a validated `AnswerWithSources` along with `CallStats`."""
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(context_chunks, question)

        start_time = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnswerWithSources,
                system_instruction=system_prompt,
            ),
        )
        latency = time.perf_counter() - start_time

        result = AnswerWithSources.model_validate_json(response.text)

        # Token accounting. Gemini 2.5 thinking tokens are billed as output but are NOT
        # in candidates_token_count, so output = candidates + thoughts (read defensively;
        # missing metadata → 0, never crash).
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        candidates = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
        thoughts = getattr(usage, "thoughts_token_count", 0) or 0 if usage else 0
        output_tokens = candidates + thoughts

        stats = CallStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            model=self._model,
            system="google",
        )

        logger.info(
            "generation.google sources=%s context_doc_ids=%s input_tokens=%d output_tokens=%d latency_s=%.3f",
            result.sources,
            [c.doc_id for c in context_chunks],
            input_tokens,
            output_tokens,
            latency,
        )
        return result, stats
```

> **Note on `getattr(...) or 0`:** the `or 0` coalesces a present-but-`None` field
> (the SDK exposes these counts as `int | None`) to `0`. Keep both the `getattr` default
> and the `or 0` — `getattr` covers a missing attribute, `or 0` covers an explicit `None`.

---

## Exact diffs

### `src/enterprise_rag_ops/eval/config.py` (line 22)

```diff
-    system: Literal["openai", "anthropic"]
+    system: Literal["openai", "anthropic", "google"]
```

### `src/enterprise_rag_ops/eval/runner.py` (imports + factory dict)

```diff
 from enterprise_rag_ops.generation.anthropic_generator import AnthropicGenerator
 from enterprise_rag_ops.generation.cli import ABSTAIN_ANSWER
 from enterprise_rag_ops.generation.context import ContextAssembler
+from enterprise_rag_ops.generation.gemini_generator import GeminiGenerator
 from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator
```

```diff
 _GENERATOR_FACTORY = {
     "openai": OpenAIGenerator,
     "anthropic": AnthropicGenerator,
+    "google": GeminiGenerator,
 }
```

### `configs/baseline.yaml`

Add the `models` entry (FR-13 Should) under the existing `models:` list:

```yaml
- model_id: "gemini-2.5-flash-lite"
  system: "google"
```

Add the price entry (FR-10 Must) under `prices:`:

```yaml
# gemini-2.5-flash-lite price verified against Google's official Gemini API pricing (AC-8).
gemini-2.5-flash-lite:
  input_usd_per_1m: 0.10
  output_usd_per_1m: 0.40
```

---

## ADR-0005 amendment text (append to `docs/adr/0005-llm-provider-matrix.md`)

Append a new section after `## Consequences` (do **not** create a new ADR file):

```markdown
## Amendment (2026-06-01) — Google / Gemini as third generator family

4. **Google (Gemini)**: Third multi-model generator (Sprint 4, Phase 10).
   - **Generation**: `gemini-2.5-flash-lite` — added to the multi-model sweep behind the
     proven `Generator` Protocol (`generation/gemini_generator.py`), overridable via env
     var `RAG_GEN_MODEL_GOOGLE`. Uses native JSON-schema structured output
     (`response_schema=AnswerWithSources` in `GenerateContentConfig`); the output is
     re-validated our side via `model_validate_json` (`extra="forbid"`).
   - **Evaluation (Judge)**: never. Gemini is a generator only.
   - **Pricing**: `0.10` input / `0.40` output USD per 1M tokens, per Google's official
     Gemini API pricing page (recorded in `configs/baseline.yaml`). Cost-accurate output
     tokens = `candidates_token_count + thoughts_token_count` (Gemini 2.5 thinking tokens
     are billed as output but excluded from `candidates_token_count`).

**Independence restated:** adding Google widens the _generator_ matrix to a genuine
three-way comparison (OpenAI / Anthropic / Google). The judge slot is unchanged: it is
resolved from `RunConfig.judge_model` (a plain string) through `OpenAIJudge` only, with no
`system`-keyed judge factory. Gemini cannot be wired as a judge, preserving the
same-family-bias guarantee this ADR exists to enforce.
```

---

## Cassette / recording note

- **Record once (maintainer, live):** export a real `GEMINI_API_KEY` (or `GOOGLE_API_KEY`),
  then run the cassette test with `VCR_RECORD_MODE=once`:
  `VCR_RECORD_MODE=once uv run pytest tests/generation/test_gemini_generator.py -k live_replay`.
- **Cassette path:** `tests/eval/cassettes/gemini_generator.yaml` (same dir as
  `anthropic_generator.yaml`; the root `tests/conftest.py` `vcr_record` fixture points
  there).
- **Scrubbing:** the shared fixture already filters request credentials
  (`authorization`, `x-api-key`) and identifying response headers. **Add the Gemini key
  header to the request filter** if the SDK transmits the key in a header the current list
  misses — verify the recorded YAML contains no key/secret before committing (manual
  inspection is part of the record step; this is the stranger-test gate). If the SDK sends
  the key as a `x-goog-api-key` header or a `?key=` query param, extend
  `_FILTER_REQUEST_HEADERS` / add a `filter_query_parameters=["key"]` to the fixture —
  flagged as a **record-time check**, not a blind assumption.
- **CI replay:** mode `none` (the fixture default) — `make test` replays offline with no
  network and no key (NFR-2, AC-11).

---

## Implementation Phases

Smallest-testable-first; each step is independently `make lint test`-able.

1. **Dep + config Literal + price + their unit tests (fully offline, no SDK call).**
   - `pyproject.toml` add `google-genai`; `uv sync`.
   - `eval/config.py` Literal widening + `test_config.py` Literal tests (AC-7).
   - `configs/baseline.yaml` price block + `test_records.py` price-lookup test (AC-8).
   - Runner dispatch can be asserted offline with a stub/injected generator
     (`test_runner.py`, AC-6) — does not need the real SDK call.
   - Gate: `uv run pytest tests/eval/test_config.py tests/eval/test_records.py tests/eval/test_runner.py` then `make lint test`.

2. **`GeminiGenerator` + injected-client tests + env-guard test (offline).**
   - Create `gemini_generator.py` (skeleton above).
   - `test_gemini_generator.py` offline path: fake/injected client, `model_validate_json`
     parse, `extra="forbid"` raises (AC-2); token mapping incl. thoughts-sum + missing
     metadata → 0/0 (AC-3); env-guard raises naming both vars (AC-4); model resolution
     default / `RAG_GEN_MODEL_GOOGLE` / explicit-arg precedence (AC-5).
   - Wire `runner.py` factory + import.
   - Gate: `uv run pytest tests/generation/test_gemini_generator.py` then `make lint test`.

3. **Record the live cassette + the replay test.**
   - Record `gemini_generator.yaml` (live, `VCR_RECORD_MODE=once`), scrub-verify, commit.
   - `@pytest.mark.vcr` replay test (AC-1, AC-11): valid `AnswerWithSources` + `CallStats`
     with `system=="google"`, `input_tokens>0`, `output_tokens>0`, `latency_s>0.0`,
     `model==<resolved id>`.
   - Gate: `make test` (offline replay must pass with no key).

4. **ADR-0005 amendment** (text above). Gate: `make lint` (markdown only).

5. **[Should] baseline.yaml `models` add + the documented 3-way sweep run (AC-13).**
   - Add `gemini-2.5-flash-lite` to `models` (diff above).
   - Run the documented manual sweep (`make build-index-gold` → `rag-eval` per the baseline
     recipe in MEMORY) producing a JSONL with all three families. JSONL stays gitignored in
     `results/` (FR-14 decision). This is a live run, not a pytest.

---

## Test Strategy

The injected-client tests carry most coverage (no network); the cassette covers the real
wire path. AC-13 (3-way sweep) is a documented manual run, not a pytest.

| Test (file)                                                       | Asserts                                                                                                                                                                                                       | AC                             |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `test_gemini_generator.py::test_offline_injected_client`          | Injected fake client → `generate_with_stats` returns expected `answer`/`sources` parsed via `model_validate_json`; a payload with an extra field raises `ValidationError` (proves `extra="forbid"` our side). | AC-2 (FR-1, FR-3)              |
| `test_gemini_generator.py::test_token_mapping`                    | Fake `usage_metadata` with `prompt/candidates/thoughts` counts → `input_tokens == prompt`, `output_tokens == candidates + thoughts`; a response with no `usage_metadata` yields `0/0` without raising.        | AC-3 (FR-4)                    |
| `test_gemini_generator.py::test_env_guard`                        | Both `GEMINI_API_KEY` and `GOOGLE_API_KEY` unset + no client → `RuntimeError` naming both vars; setting either (or injecting client) succeeds.                                                                | AC-4 (FR-5)                    |
| `test_gemini_generator.py::test_model_resolution`                 | Default `gemini-2.5-flash-lite`; `RAG_GEN_MODEL_GOOGLE` overrides; explicit `model=` wins over env.                                                                                                           | AC-5 (FR-6)                    |
| `test_gemini_generator.py::test_live_replay` (`@pytest.mark.vcr`) | Replays `gemini_generator.yaml` offline → valid `AnswerWithSources` + `CallStats(system=="google")`, `input_tokens>0`, `output_tokens>0`, `latency_s>0.0`, `model==resolved`.                                 | AC-1 (FR-1/3/4), AC-11 (NFR-2) |
| `test_runner.py` (extend)                                         | `ModelConfig(system="google")` resolves through `_GENERATOR_FACTORY` to `GeminiGenerator`; `openai`/`anthropic` still resolve.                                                                                | AC-6 (FR-7)                    |
| `test_config.py` (extend)                                         | `ModelConfig(system="google", model_id=...)` validates; `system="gemini"` raises `ValidationError`.                                                                                                           | AC-7 (FR-8)                    |
| `test_records.py` (extend)                                        | `Price(0.10, 0.40)` for `gemini-2.5-flash-lite` → non-None `compute_cost_usd` for a `system="google"` `CallStats`.                                                                                            | AC-8 (FR-10)                   |
| (no new test) AC-9                                                | `from google import genai` importable after `uv sync`; `make lint test` green.                                                                                                                                | AC-9 (FR-9)                    |
| (assertion, not new code) AC-10                                   | No `system`-keyed judge factory exists; no `"google"` judge wiring added. Verified by inspection + the unchanged judge path (independence is structural).                                                     | AC-10 (NFR-1)                  |
| (manual/live) AC-13                                               | Documented 3-way sweep producing a JSONL with all three families.                                                                                                                                             | AC-13 (FR-13)                  |
| (diff inspection) AC-14                                           | Diff touches only NFR-6 files; `interfaces.py`, runner internals, judge, records schema, observability unchanged.                                                                                             | AC-14 (NFR-6)                  |

No mocked LLM API anywhere (ADR-0006): offline tests use an **injected fake client**
(mirrors `FakeAnthropicClient`), not a patched SDK; the live path uses the **cassette**.

---

## Infrastructure Gaps (3-layer check)

| Gap Type           | Area              | Detail                                                                                                                                                                                                                                                            | Recommendation                                                                                         |
| ------------------ | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Missing domain     | —                 | None. `google-genai` is a **tool/dep, not a knowledge domain** — no KB domain warranted (mirrors how `openai`/`anthropic` SDKs are not KB domains). The proven seam patterns live in `rag-eval`.                                                                  | No `/new-kb` before implement.                                                                         |
| Missing concept    | `rag-eval`        | None blocking. `stats-capture-seam`, `cassette-replay-eval`, `multi-model-runner`, `cost-accounting` all cover this phase. The token-mapping thoughts-sum nuance is a _new concept worth capturing post-impl_ (the multi-provider `generate_with_stats` pattern). | Defer to FR-15 Could → `/update-kb` (or seed `rag-generation`) **after** ADR/impl lands. Non-blocking. |
| Missing specialist | generation module | None. No specialist owns `generation/`; all manifest files are owner **direct**. The change is small, conventional, and template-driven (`anthropic_generator.py`).                                                                                               | No `/new-agent`.                                                                                       |
| Missing dependency | `pyproject.toml`  | `google-genai` not present — added by FR-9 (manifest #1).                                                                                                                                                                                                         | In-scope; not an infra gap requiring a harness command.                                                |

**Layer summary — agent alignment:** the only KB domain this touches (`rag-eval`) lists
`kb-architect` as its agent; no specialist agent participates in implement. No agent's
`kb_domains` need to change.

**Confirmed expected outcome (per the task brief):** no new KB/agent before design. The
`google-genai` dep (in-scope FR-9) and the post-impl `rag-generation` KB (FR-15, Could) are
the only "gaps" — both already anticipated in DEFINE's Infrastructure Readiness table.

---

## Consistency Check (6 passes)

**Verdict: 🟡 MINOR DRIFT** — one intentional, design-strengthening deviation from a DEFINE
FR (C-1), documented and reconciled here; no CRITICAL/HIGH drift; no constitution violation.

| ID  | Severity | Pass                   | Location                                                             | Finding                                                                                                                                                                                                                                                                                                                                                                                                                   | Suggested fix                                                                                                                                                                                                                                                                                                                                                     |
| --- | -------- | ---------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | MEDIUM   | Inconsistency          | DEFINE FR-4 / AC-3 vs DESIGN token mapping                           | DEFINE FR-4 maps `output_tokens ← candidates_token_count` only; AC-3's fake `usage_metadata` exposes only `prompt`/`candidates`. DESIGN uses `output = candidates + thoughts` for cost-correctness (Gemini 2.5 thinking tokens billed as output, excluded from `candidates`). This is an **intentional strengthening**, not a contradiction — it preserves FR-4's "defensive `getattr`, missing → 0, never crash" intent. | Implement the sum (cost-correct). AC-3's existing two-field fake still passes (`thoughts` absent → `getattr → 0`, output == candidates). **Add** a third AC-3 sub-assertion with `thoughts_token_count` set, asserting `output == candidates + thoughts`. Record this as the resolution of DEFINE Open-Question token-accounting; do not silently rewrite DEFINE. |
| C-2 | LOW      | Ambiguity              | DEFINE FR-2 / Open-Q 1 — `response_schema` vs `response_json_schema` | DEFINE left the SDK param spelling open "verified at `/design`".                                                                                                                                                                                                                                                                                                                                                          | RESOLVED here: pin `google-genai>=1.0,<2.0` and use `response_schema=AnswerWithSources` (live 2.5 path, Context7-confirmed). `response_json_schema` is the gemini-3 spelling — not used. No further ambiguity.                                                                                                                                                    |
| C-3 | LOW      | Ambiguity              | DEFINE Open-Q 3 / FR-14 — JSONL disposition                          | DEFINE deferred commit-vs-gitignore to `/design`.                                                                                                                                                                                                                                                                                                                                                                         | RESOLVED: gitignored + regenerable in `results/` (matches convention; stranger test). Documented in manifest.                                                                                                                                                                                                                                                     |
| C-4 | LOW      | Underspecification     | Cassette key-header scrubbing                                        | DEFINE says "header-scrubbed" but the Gemini SDK may send the key as `x-goog-api-key` or `?key=`, which the current `_FILTER_REQUEST_HEADERS` does not cover.                                                                                                                                                                                                                                                             | Flagged as a **record-time check** in the cassette note: inspect the recorded YAML; extend the filter (`filter_query_parameters=["key"]` / add header) before committing. Not a silent assumption.                                                                                                                                                                |
| C-5 | —        | Duplication            | —                                                                    | No duplicated/overlapping requirements found between DEFINE and DESIGN.                                                                                                                                                                                                                                                                                                                                                   | —                                                                                                                                                                                                                                                                                                                                                                 |
| C-6 | —        | Constitution alignment | AGENTS.md §Engineering Behavior + §Conventions; ADR-0005/0006        | English ✓; mirrored test per new module ✓ (`test_gemini_generator.py`); cassette/replay no-mock rule ✓ (injected client + cassette, never a patched SDK); seam discipline ✓ (new file behind proven Protocol, no seam pre-building, no speculative scope); independence ✓ (no judge wiring); stranger test ✓ (JSONL gitignored, key scrubbed). **No constitution violation → no auto-CRITICAL.**                          | —                                                                                                                                                                                                                                                                                                                                                                 |
| C-7 | —        | Coverage               | DEFINE FR-1..FR-15, NFR-1..NFR-6, AC-1..AC-14 ↔ manifest             | Every Must/Should FR maps to ≥1 manifest entry (see manifest FR column + Test Strategy AC column). Could items: FR-14 resolved (gitignore), FR-15 deferred (post-impl, non-blocking, correctly out of the implement gate). No DEFINE requirement is unmapped; no manifest entry references an undefined component.                                                                                                        | —                                                                                                                                                                                                                                                                                                                                                                 |

**Pass-by-pass:** (1) Duplication — none (C-5). (2) Ambiguity — two open params resolved
(C-2, C-3); one low ambiguity flagged as a record-time check (C-4). (3) Underspecification —
C-4 only; all FRs have concrete objects/measures. (4) Constitution — clean (C-6), no
CRITICAL. (5) Coverage — complete both ways (C-7). (6) Inconsistency — one intentional,
documented strengthening (C-1, MEDIUM), reconciled without rewriting DEFINE.

---

## Risks & Trade-offs

- **Token-mapping deviation (C-1)** is the one judgement call. Trade-off: strict
  DEFINE-literal fidelity (`candidates` only) vs cost-correctness (`candidates + thoughts`).
  Chosen cost-correctness because undercounting output cost silently breaks the
  `cost_accounting` guarantee the eval harness exists to provide, and the defensive sum is
  correct in _all_ thinking states. **Worth a one-line ADR-0005 note** (included in the
  amendment) so the mapping rationale is discoverable.
- **`google-genai` version pin (`>=1.0,<2.0`):** `response_schema` (live 2.5) vs
  `response_json_schema` (gemini-3) diverge across the SDK's evolution. The `<2.0` cap and
  the `response_schema` spelling are coupled — if the lockfile resolves a version where the
  param differs, the cassette record step will fail fast (good). Verify the resolved version
  at `uv sync` time.
- **Cassette key leakage** (C-4): the highest-consequence risk for a _public_ repo. Mitigated
  by the mandatory record-time scrub-verify step. Do not commit the cassette without
  inspecting it for `key=` / `x-goog-api-key`.
- **3-way sweep cost/time** (AC-13): ~$0.10–0.15 + ~2–3h on the 8 GB Air per the baseline
  recipe. Gated behind the recorded cassette; gitignored output keeps the repo clean.
- **No new ADR needed** beyond the 0005 amendment — the seam, cassette pattern, and cost
  accounting are all already-accepted decisions.

---

## Next Step

→ `/implement sprint-4/phase-10-gemini-generator` (runs in Antigravity / Gemini against this
DESIGN). No infra gaps block implement: `google-genai` is added in manifest #1; the
`rag-generation` KB seed is a post-impl Could (FR-15), out of the implement gate.
