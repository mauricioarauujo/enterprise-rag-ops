# RAG Generation Quick Reference

> Fast lookup tables. For full explanations, see linked concept/pattern files.

## Per-Provider Structured-Output Mechanism

| Provider  | `system` key | Mechanism                                                                                                                    | SDK call shape                 |
| --------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| OpenAI    | `openai`     | `response_format={"type":"json_schema","json_schema":{"name":...,"schema":...,"strict":True}}`                               | `chat.completions.create(...)` |
| Anthropic | `anthropic`  | Forced tool-use: `tools=[{"name":"emit_answer","input_schema":schema}]` + `tool_choice={"type":"tool","name":"emit_answer"}` | `messages.create(...)`         |
| Google    | `google`     | `GenerateContentConfig(response_mime_type="application/json", response_schema=_GeminiResponseSchema)`                        | `models.generate_content(...)` |

**Invariant across all three:** re-validate the response via `AnswerWithSources.model_validate_json(raw)` (or `.model_validate(dict)` for Anthropic tool input) regardless of provider-side enforcement.

## Token-Usage Field Mapping

| Provider  | Input tokens                        | Output tokens                                   | Notes                                                                                                           |
| --------- | ----------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| OpenAI    | `usage.prompt_tokens`               | `usage.completion_tokens`                       | `getattr(usage, ..., 0)` defensive read                                                                         |
| Anthropic | `usage.input_tokens`                | `usage.output_tokens`                           | `getattr(usage, ..., 0)` defensive read                                                                         |
| Google    | `usage_metadata.prompt_token_count` | `candidates_token_count + thoughts_token_count` | Gemini 2.5 thinking tokens billed as output but absent from `candidates`; both read with `getattr(..., 0) or 0` |

## Key-Scrub Headers for Cassettes

| Provider  | Request header(s) | Query param |
| --------- | ----------------- | ----------- |
| OpenAI    | `authorization`   | —           |
| Anthropic | `x-api-key`       | —           |
| Google    | `x-goog-api-key`  | `key`       |

Configured once in `tests/conftest.py` via `vcr.VCR(filter_headers=..., filter_query_parameters=["key"])`.

## Retry Hardening

| Provider  | Knob                                                                                           | Value               | Rationale                                              |
| --------- | ---------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------------------------ |
| OpenAI    | `OpenAI(timeout=120.0)`                                                                        | SDK default retries | Tier not throttled in sweeps                           |
| Anthropic | `Anthropic(max_retries=8, timeout=120.0)`                                                      | 8 retries           | Tier-1 output-token/min cap; SDK honours `retry-after` |
| Google    | `HttpRetryOptions(attempts=8, http_status_codes=[429,500,502,503,504])` + `timeout=120_000` ms | 8 retries           | Transient 503 "high demand" spike mid-sweep            |

## Env-var Model Override

| Provider  | Env var                   | Default model               |
| --------- | ------------------------- | --------------------------- |
| OpenAI    | `RAG_GEN_MODEL`           | `gpt-5-nano-2025-08-07`     |
| Anthropic | `RAG_GEN_MODEL_ANTHROPIC` | `claude-haiku-4-5-20251001` |
| Google    | `RAG_GEN_MODEL_GOOGLE`    | `gemini-2.5-flash-lite`     |

## RawCall / Bronze Capture

| Item                       | Detail                                                                                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Transport model            | `eval/raw_call.py` — `RawCall(request: dict, response: dict)`, `extra="forbid"`                                                                            |
| Where returned             | 3rd element of `generate_with_stats` / `judge_with_stats` (off-Protocol)                                                                                   |
| Persisted                  | Bronze tier only (ADR-0010); **not** in gold `EvalRecord`                                                                                                  |
| Serializer                 | `_serialize_response(response)` in each provider module; fast path `model_dump(mode="json")`; manual fallback; catch-all `{"_serialization_error": "..."}` |
| Request privacy            | Built from local vars (model, messages, params); never introspects client object                                                                           |
| Gemini `sdk_http_response` | Fast path emits response headers only (`body: null`); no secrets                                                                                           |
| Shared serializer          | `openai_judge` imports `_serialize_response` from `openai_generator` (same ChatCompletion shape)                                                           |

## Gemini Operational Gotchas (ADR-0011)

| Gotcha                       | Detail                                                                                                                                                                             |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No logprobs on Gemini 2.5    | `response_logprobs=True` or `logprobs=N` → `400 INVALID_ARGUMENT: "Logprobs is not enabled"` on Flash and Flash-Lite                                                               |
| Older logprob models retired | `gemini-1.5-flash`, `gemini-2.0-flash` → 404; no fallback available                                                                                                                |
| Confidence signal workaround | Add `confidence: float` to `_GeminiResponseSchema` + `_CONFIDENCE_ADDENDUM` on system prompt; strip field before `AnswerWithSources` validation; ride `CallStats.confidence_score` |

## Router Cascade Composite (ADR-0012)

| Item            | Detail                                                                                                           |
| --------------- | ---------------------------------------------------------------------------------------------------------------- |
| Conformance     | Structural `Generator` via `generate` — no inheritance, no `_GENERATOR_FACTORY`, `interfaces.py` untouched       |
| Escalation rule | Escalate unless `confidence_score >= threshold` AND not `ABSTAIN_ANSWER`; missing confidence → escalate          |
| Combined cost   | Single owner: cheap always + strong iff escalated, `None`→`0.0`; `model="router"`, conf/`gen_raw` = cheap's      |
| Cost-guard pair | Runner skips recompute when `cost_usd` is pre-set → router's combined cost survives (`rag-eval` cost-accounting) |

## Common Pitfalls

| Don't                                                           | Do                                                                                             |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Pass `AnswerWithSources` directly as Gemini `response_schema`   | Use `_GeminiResponseSchema` (open mirror); enforce closed-schema our side                      |
| Set `response_logprobs` on a Gemini 2.5 `GenerateContentConfig` | Gemini 2.5 400s — use verbalized-confidence pattern instead                                    |
| Leave extra provider fields in the dict before `model_validate` | Strip Gemini-only fields (e.g. `confidence`) before calling `AnswerWithSources.model_validate` |
| Count only `candidates_token_count` for Gemini cost             | Add `thoughts_token_count` (thinking tokens billed separately)                                 |
| Forget to `getattr(..., 0)` on usage fields                     | All three providers use defensive reads — missing metadata returns 0, never crashes            |
| Add a provider without updating `_GENERATOR_FACTORY`            | One-line dict entry in `eval/runner.py` is the wiring point                                    |
| Build `RawCall.request` from `client` object introspection      | Build from local vars; auth headers are structurally absent                                    |
| Expect `generate_with_stats` to return 2 values                 | It returns `(AnswerWithSources, CallStats, RawCall)` — 3-tuple since Phase-19                  |

## Related Documentation

| Topic                              | Path                                         |
| ---------------------------------- | -------------------------------------------- |
| Full structured-output explanation | `concepts/structured-output-per-provider.md` |
| Generator seam + dispatch          | `concepts/generator-seam.md`                 |
| Add-a-generator recipe             | `patterns/add-a-generator.md`                |
| Token accounting detail            | `concepts/per-provider-token-accounting.md`  |
| Raw-payload serialization          | `concepts/raw-payload-serialization.md`      |
| Full Index                         | `index.md`                                   |
