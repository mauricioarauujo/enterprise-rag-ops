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

## Common Pitfalls

| Don't                                                         | Do                                                                                  |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Pass `AnswerWithSources` directly as Gemini `response_schema` | Use `_GeminiResponseSchema` (open mirror); enforce closed-schema our side           |
| Count only `candidates_token_count` for Gemini cost           | Add `thoughts_token_count` (thinking tokens billed separately)                      |
| Forget to `getattr(..., 0)` on usage fields                   | All three providers use defensive reads — missing metadata returns 0, never crashes |
| Add a provider without updating `_GENERATOR_FACTORY`          | One-line dict entry in `eval/runner.py` is the wiring point                         |

## Related Documentation

| Topic                              | Path                                         |
| ---------------------------------- | -------------------------------------------- |
| Full structured-output explanation | `concepts/structured-output-per-provider.md` |
| Generator seam + dispatch          | `concepts/generator-seam.md`                 |
| Add-a-generator recipe             | `patterns/add-a-generator.md`                |
| Token accounting detail            | `concepts/per-provider-token-accounting.md`  |
| Full Index                         | `index.md`                                   |
