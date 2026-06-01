# DEFINE: sprint-4/phase-10-gemini-generator — Third Generator (GeminiGenerator)

**Sprint/Phase:** sprint-4/phase-10-gemini-generator | **Date:** 2026-06-01

---

## Context

The multi-model sweep compares only OpenAI + Anthropic, so the "multi-model" report is a
single cross-family pair. Adding `gemini-2.5-flash-lite` as a third generator-under-test —
behind the already-proven `Generator` Protocol — makes the comparison a genuine three-way
and gives Phases 11–13 real published evidence. The seam is proven (Sprint 2/3): the change
is one new file + one factory line + one Literal widening + one config entry, no
runner/judge/observability internals touched. Gemini is a **generator only** — never the
judge (ADR-0005 independence). The Stage-0 forks are resolved: **Approach A** (native
JSON-schema structured output) and **Approach X** (run the 3-way sweep in this phase).

---

## Requirements

### Functional

MoSCoW tags carried from BRAINSTORM §Scope. Every Must is justified against the phase goal
(a real 3-way comparison behind the proven seam) and the seam-locality constraint.

| ID        | Requirement                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | MoSCoW |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| **FR-1**  | `GeminiGenerator` lives in `src/enterprise_rag_ops/generation/gemini_generator.py` and satisfies the `Generator` Protocol (`generation/interfaces.py`): it implements `generate(context_chunks, question) -> AnswerWithSources` and `generate_with_stats(context_chunks, question) -> tuple[AnswerWithSources, CallStats]`, with `generate` delegating to `generate_with_stats` (mirrors `AnthropicGenerator`).                                                                                                                                                                            | Must   |
| **FR-2**  | Structured output uses **native JSON-schema mode** (Approach A): the call passes `config=GenerateContentConfig(response_mime_type="application/json", response_schema=AnswerWithSources, system_instruction=build_system_prompt())` with `contents=build_user_prompt(context_chunks, question)`. No tool/function-calling wrapper; no raw-prompt JSON scraping. The exact param name (`response_schema` vs `response_json_schema`) is verified at `/design` against the pinned `google-genai` version — the _requirement_ is native JSON-schema structured output, not the param spelling. | Must   |
| **FR-3**  | The response is parsed and validated to `AnswerWithSources` via `AnswerWithSources.model_validate_json(resp.text)`, so `extra="forbid"` is enforced our side regardless of provider enforcement. A response that fails validation raises (no silent coercion).                                                                                                                                                                                                                                                                                                                             | Must   |
| **FR-4**  | `generate_with_stats` returns a `CallStats` built from the response with `system="google"`, `model=<resolved model id>`, `latency_s=<wall-clock around the call>`, `input_tokens` ← `resp.usage_metadata.prompt_token_count`, `output_tokens` ← `candidates_token_count + thoughts_token_count` (Gemini 2.5 thinking tokens are billed as output but excluded from `candidates_token_count` — cost-correct mapping refined at `/design`, see DESIGN §Consistency C-1), all read defensively with `getattr` (mirrors the Anthropic `usage` handling; missing metadata → 0, never crash).    | Must   |
| **FR-5**  | The constructor fails fast in `__init__` (when no client is injected) if **neither** `GEMINI_API_KEY` **nor** `GOOGLE_API_KEY` is set, raising a clear `RuntimeError` naming both vars (mirrors the `AnthropicGenerator` `ANTHROPIC_API_KEY` guard).                                                                                                                                                                                                                                                                                                                                       | Must   |
| **FR-6**  | The model id defaults to `gemini-2.5-flash-lite` and is overridable via env var `RAG_GEN_MODEL_GOOGLE` (mirrors `RAG_GEN_MODEL_ANTHROPIC`); an explicit `model=` constructor arg wins over the env var.                                                                                                                                                                                                                                                                                                                                                                                    | Must   |
| **FR-7**  | The runner factory `_GENERATOR_FACTORY` in `eval/runner.py` gains `"google": GeminiGenerator`, so `ModelConfig(system="google")` dispatches to `GeminiGenerator`.                                                                                                                                                                                                                                                                                                                                                                                                                          | Must   |
| **FR-8**  | `ModelConfig.system` in `eval/config.py` widens to `Literal["openai", "anthropic", "google"]`; `system="google"` validates and any value outside the Literal (e.g. `"gemini"`) is rejected by Pydantic.                                                                                                                                                                                                                                                                                                                                                                                    | Must   |
| **FR-9**  | `google-genai` is added as a runtime dependency in `pyproject.toml` and pinned via the lockfile (`uv sync`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Must   |
| **FR-10** | `configs/baseline.yaml` gains a price entry for `gemini-2.5-flash-lite`: `input_usd_per_1m: 0.10`, `output_usd_per_1m: 0.40`, so `compute_cost_usd` resolves a non-None cost for Gemini calls.                                                                                                                                                                                                                                                                                                                                                                                             | Must   |
| **FR-11** | One live cassette is recorded and `tests/generation/test_gemini_generator.py` (with `tests/generation/__init__.py` present) covers the offline-injected-client path, the cassette replay path, and the env-guard path — never a mocked LLM API (ADR-0006).                                                                                                                                                                                                                                                                                                                                 | Must   |
| **FR-12** | ADR-0005 is **amended** (not a new ADR): Google/Gemini added as the third generator family with its default model, and the judge/generator independence constraint is restated (Gemini never judges).                                                                                                                                                                                                                                                                                                                                                                                      | Must   |
| **FR-13** | `gemini-2.5-flash-lite` (`system: "google"`) is added to the `models` list in `configs/baseline.yaml`, and the full 500-question 3-way sweep is run to produce a 3-way results JSONL for Phase 11.                                                                                                                                                                                                                                                                                                                                                                                         | Should |
| **FR-14** | The 3-way baseline results JSONL is either committed to `results/` or explicitly documented as a gitignored, regenerable artifact (decision deferred to `/design`/implement).                                                                                                                                                                                                                                                                                                                                                                                                              | Could  |
| **FR-15** | After this phase's ADR/impl lands, `/new-kb rag-generation` seeds the carried-debt KB domain (three providers make the multi-provider `generate_with_stats` pattern concrete). Non-blocking; not part of the implement gate.                                                                                                                                                                                                                                                                                                                                                               | Could  |

### Non-functional

| ID                                               | Requirement                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **NFR-1 (Independence — hard)**                  | Gemini MUST NOT be wireable as a judge. The judge slot is resolved from `RunConfig.judge_model` (a plain string) through `OpenAIJudge` only; no `system`-keyed judge factory exists. No Gemini-judge wiring, Literal, or factory key is added. The judge stays OpenAI/Anthropic.                                                              |
| **NFR-2 (Offline-replayable tests)**             | All `test_gemini_generator.py` tests pass under `make test` with no network and no real API key (VCR record mode `none`; cassette committed under `tests/eval/cassettes/`, header-scrubbed per ADR-0006).                                                                                                                                     |
| **NFR-3 (Structured output validated our side)** | `AnswerWithSources` (`extra="forbid"`) is the single output schema; `model_validate_json` enforces the closed schema regardless of provider-side enforcement. No Gemini-specific output schema.                                                                                                                                               |
| **NFR-4 (Determinism)**                          | The generator adds no nondeterministic prompt construction; prompt bytes are produced solely by the shared `build_system_prompt`/`build_user_prompt`. Test assertions on the replayed cassette are deterministic.                                                                                                                             |
| **NFR-5 (Prompt-agnosticism)**                   | `GeminiGenerator` reuses the shared prompt functions verbatim — no Gemini-specific prompt text, system instruction, or schema massaging beyond what the SDK's `response_schema` param mechanically requires.                                                                                                                                  |
| **NFR-6 (Seam-locality)**                        | The change touches only: a new `gemini_generator.py`, one `_GENERATOR_FACTORY` line, the `ModelConfig.system` Literal, `pyproject.toml`, `configs/baseline.yaml`, the new test + cassette, and ADR-0005. The `Generator` Protocol (`interfaces.py`), runner internals, judge, `CallStats`/records schema, and observability are NOT modified. |

---

## Acceptance Criteria

Offline-checkable in CI unless marked **(manual/live)**.

1. **AC-1 (FR-1, FR-3, FR-4) — cassette happy path:** `test_gemini_generator.py` replays a
   recorded cassette and asserts `generate_with_stats(chunks, question)` returns a valid
   `AnswerWithSources` (answer non-empty, sources a list) **and** a `CallStats` with
   `system == "google"`, `input_tokens > 0`, `output_tokens > 0`, `latency_s > 0.0`,
   `model == <resolved model id>`.
2. **AC-2 (FR-1, FR-3) — offline injected-client path:** a fake/injected client test
   (no network) asserts the response text is parsed via `model_validate_json` into the
   expected `answer`/`sources`, and that a payload with an extra field raises
   `ValidationError` (proves `extra="forbid"` is enforced our side).
3. **AC-3 (FR-4) — token mapping:** with a fake `usage_metadata` exposing
   `prompt_token_count`/`candidates_token_count`/`thoughts_token_count`,
   `CallStats.input_tokens == prompt_token_count` and
   `output_tokens == candidates_token_count + thoughts_token_count`; a response missing
   `usage_metadata` (or with `thoughts` absent) yields the defensive `0` for each missing
   field without raising.
4. **AC-4 (FR-5) — env guard:** with both `GEMINI_API_KEY` and `GOOGLE_API_KEY` unset and
   no injected client, `GeminiGenerator()` raises `RuntimeError` naming both env vars.
   Setting either one (or injecting a client) lets construction succeed.
5. **AC-5 (FR-6) — model resolution:** default model is `gemini-2.5-flash-lite`;
   `RAG_GEN_MODEL_GOOGLE` overrides it; an explicit `model=` arg wins over the env var.
6. **AC-6 (FR-7) — runner dispatch:** a runner-level test asserts that a `ModelConfig`
   with `system="google"` resolves through `_GENERATOR_FACTORY` to `GeminiGenerator`
   (and that `openai`/`anthropic` still resolve to their existing classes).
7. **AC-7 (FR-8) — config Literal:** `ModelConfig(system="google", model_id=...)` validates;
   `ModelConfig(system="gemini")` and any other non-Literal value raise `ValidationError`.
8. **AC-8 (FR-10) — price lookup:** loading `configs/baseline.yaml` yields a `Price` for
   `gemini-2.5-flash-lite` of `0.10`/`0.40`, and `compute_cost_usd` returns a non-None cost
   for a Gemini `CallStats`.
9. **AC-9 (FR-9) — dependency:** `google-genai` is importable after `uv sync`
   (`from google import genai`), and `make lint test` passes.
10. **AC-10 (NFR-1 — independence):** an explicit test/assertion shows the judge path does
    not admit Gemini: `RunConfig.judge_model` is a string resolved only to `OpenAIJudge`,
    there is no `system`-keyed judge factory, and no `"google"` judge wiring exists. The
    `models` matrix can contain `system="google"` while `judge_model` remains an
    OpenAI/Anthropic model id. (If judge selection is purely string-based, the AC is the
    assertion that no Gemini-judge code path was added.)
11. **AC-11 (FR-11, NFR-2) — offline CI:** `make test` passes with no network and no real
    API keys; the Gemini cassette is committed and header-scrubbed.
12. **AC-12 (FR-12) — ADR amendment:** `docs/adr/0005-llm-provider-matrix.md` is amended to
    list Google/Gemini (`gemini-2.5-flash-lite`) as the third generator family and restates
    that Gemini is never the judge; no new ADR file is created.
13. **AC-13 (FR-13) — 3-way sweep (manual/live):** with the Gemini cassette recorded and
    `gemini-2.5-flash-lite` in `baseline.yaml` `models`, a documented manual run of the
    500-question sweep (`make build-index-gold` → `rag-eval` per the baseline recipe)
    produces a JSONL containing records for all three generator families. Not a unit test —
    a documented live run gated behind the recorded cassette.
14. **AC-14 (NFR-6) — seam-locality:** the implementation diff touches only the files listed
    in NFR-6; `interfaces.py`, runner internals, judge, records schema, and observability are
    unchanged.

---

## Clarity Score

| Dimension                         | Score | Note                                                                                                                                                                                                                        |
| --------------------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**                       | 3     | Root cause with evidence: the sweep compares only 2 families, degrading the "multi-model" report to a single pair; the seam is proven so the fix is localized.                                                              |
| **Users**                         | 3     | Named roles: the reviewer/hiring reader of the Phase 11 README + Phase 12 writeup (needs real 3-way numbers); the maintainer running the sweep. Workflow impact is concrete (results-first ordering protects ship phases).  |
| **Success**                       | 3     | Measurable + falsifiable: 14 ACs, each offline-checkable or a documented live run; CallStats/parse/dispatch/config/price/independence all assertable.                                                                       |
| **Scope**                         | 3     | MoSCoW with explicit Won't list (no Gemini-as-judge, no batch API, no new provider, no Protocol change) carried verbatim from BRAINSTORM.                                                                                   |
| **Constraints**                   | 3     | All constraints named: independence (hard NFR), offline-replay (ADR-0006), our-side schema validation, determinism, prompt-agnosticism, seam-locality, env-key fail-fast, pinned-SDK param verification deferred to design. |
| **Total: 15/15** — **PASS (≥12)** |       | No clarifying questions required; Stage-0 unknowns were resolved into requirements (RESOLVED facts 1–7).                                                                                                                    |

---

## Infrastructure Readiness

| Dependency                                                                                     | KB domain                                            | Specialist   | Status                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `google-genai` SDK (client init, `GenerateContentConfig`, `response_schema`, `usage_metadata`) | none (new dep)                                       | —            | OK — tool, not a domain. Context7-verified at `/design` against the pinned version; no `/new-kb` needed before design.                                                                                                                          |
| `Generator` Protocol + `generate_with_stats` contract                                          | `rag-eval` (`stats-capture-seam`)                    | kb-architect | OK — covered; `AnthropicGenerator` is the in-repo template.                                                                                                                                                                                     |
| Cassette/replay testing (ADR-0006)                                                             | `rag-eval` (`cassette-replay-eval`)                  | kb-architect | OK — reuse; cassette under `tests/eval/cassettes/`, VCR config from root `conftest.py`.                                                                                                                                                         |
| Multi-model runner factory + cost accounting                                                   | `rag-eval` (`multi-model-runner`, `cost-accounting`) | kb-architect | OK — factory + price-table seam already documented.                                                                                                                                                                                             |
| `rag-generation` KB (multi-provider generate pattern)                                          | `rag-generation`                                     | kb-architect | MISSING but **not blocking** — empty scaffold; due **after** this phase's ADR/impl via `/new-kb rag-generation` (FR-15, Could). Three providers make it concrete; decide explicitly to pay or drop the scaffold rather than carry a third time. |

**Pre-design gate:** No `/new-kb` or `/new-agent` is required before `/design`. The only KB
work (`rag-generation`) is a post-impl Could.

---

## Open Questions (for `/design` only — thin)

1. **SDK param spelling:** `response_schema=AnswerWithSources` (live 2.5 path per Context7)
   vs the newer `response_json_schema` (gemini-3) — verify against the pinned `google-genai`
   version at `/design`. The requirement (FR-2) is native JSON-schema structured output;
   only the spelling is open.
2. **`gen_ai.system` span-display value:** the OTel/observability span attribute MAY
   canonically read `"google_generativeai"`; the Literal/factory key and `CallStats.system`
   are `"google"` (RESOLVED fact 4). Confirm the span-display detail at `/design` — it does
   not change the Literal.
3. **3-way results JSONL disposition:** git-committed under `results/` vs kept gitignored and
   regenerable (FR-14, Could) — decide at `/design`/implement.

---

## Next Step

→ `/design sprint-4/phase-10-gemini-generator`
