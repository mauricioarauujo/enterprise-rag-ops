# raw-payload-serialization

> **Purpose**: How each generator (and the OpenAI judge) serializes the live SDK response into a JSON-able dict for bronze storage, and how the request side is built without capturing auth credentials.
> **Confidence**: HIGH (codebase-grounded, Phase-19; MCP check confirms pydantic-v2 fast path is valid for both OpenAI and Anthropic SDK objects)
> **MCP Validated**: 2026-06-03

## Overview

Phase-19 added a raw-payload capture layer. Every `generate_with_stats` (and `judge_with_stats`) now returns a third value: a `RawCall` Pydantic transport model holding the exact request sent and a serialized form of the provider's response. This data feeds the bronze tier (ADR-0010) and is never written to the gold `EvalRecord`.

## RawCall Transport Model

```python
# eval/raw_call.py
class RawCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: dict[str, Any]   # model + messages/contents + sampling params actually sent
    response: dict[str, Any]  # provider response serialized to a JSON-able dict
```

`RawCall` is kept in `eval/raw_call.py` and deliberately not in `eval/records.py` — it is a transient transport container, not a persisted schema artifact. It is `extra="forbid"` to prevent accidental field addition.

## Protocol Boundary

`generate_with_stats` / `judge_with_stats` are **off-Protocol**. The `Generator` / `Judge` Protocols (`generation/interfaces.py`, `eval/interfaces.py`) expose only `generate` / `judge`, which call `*_with_stats` internally and discard the third value. Callers that only need an answer remain unaffected.

## The \_serialize_response Algorithm

One `_serialize_response(response: Any) -> dict[str, Any]` per provider module. Uniform three-stage algorithm:

**Stage 1 — Fast path (pydantic v2 model_dump)**

```python
if hasattr(response, "model_dump"):
    return response.model_dump(mode="json")
```

OpenAI `ChatCompletion` and Anthropic `Message` are pydantic v2 `BaseModel` subclasses — `model_dump(mode="json")` produces a fully JSON-serializable dict. Gemini's `GenerateContentResponse` is also pydantic v2; its fast path additionally ensures `response.text` is present (the `.text` convenience property is not always included in `model_dump` output):

```python
# gemini_generator.py fast path — extra step for .text
res = response.model_dump(mode="json")
if hasattr(response, "text") and "text" not in res:
    with contextlib.suppress(Exception):
        res["text"] = response.text
return res
```

**Stage 2 — Manual fallback (known fields, omit missing)**

Reached only if the fast path raises. Per-provider known fields read with `getattr(obj, field, None)`; fields present only if the value is not `None`. Never raises.

| Provider  | Fallback fields captured                                                                                                                                                   |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenAI    | `model`, `system_fingerprint`, `choices[].{finish_reason, message.{content, refusal}}`, `usage.{prompt_tokens, completion_tokens, total_tokens}`                           |
| Anthropic | `model`, `stop_reason`, `content[].{type, name, input, text}`, `usage.{input_tokens, output_tokens}`                                                                       |
| Google    | `text`, `model_version`, `candidates[].{finish_reason, content.{role, parts[].text}}`, `usage_metadata.{prompt_token_count, candidates_token_count, thoughts_token_count}` |

**Stage 3 — Hard-failure catch-all**

```python
except Exception as e:
    return {"_serialization_error": type(e).__name__}
```

A serialization error never crashes a sweep run. The `_serialization_error` key signals in the bronze record that the response body is absent.

## Request-Side Privacy Guarantee (ADR-0010 §4)

The `request` dict is assembled from **local variables** — the model string, messages/contents, and sampling params actually passed to the SDK call. It is never built by introspecting the client object. This ensures auth headers and API keys are structurally absent from the bronze payload.

```python
# openai_generator.py / openai_judge.py pattern
request = {
    "model": self._model,
    "messages": messages_sent,         # list built locally before the call
    "response_format": response_format,
}

# anthropic_generator.py pattern
request = {
    "model": self._model,
    "max_tokens": 4096,
    "system": system_prompt,
    "messages": [{"role": "user", "content": user_prompt}],
    "tools": tools,
    "tool_choice": {"type": "tool", "name": "emit_answer"},
}

# gemini_generator.py pattern
request = {
    "model": self._model,
    "contents": user_prompt,
    "system_instruction": system_prompt,
    "response_mime_type": "application/json",
}
```

## Gemini Fast-Path Side Effect: sdk_http_response

When the Gemini fast path (`model_dump`) succeeds, the serialized dict may include an `sdk_http_response` field emitted by the SDK object. This field contains **response headers only** (`body: null`). It does not contain secrets — the Gemini API key travels on the _request_ side, not the response. This field can be used for debugging (e.g., rate-limit headers) and is harmless in the bronze tier.

## Shared Serializer: OpenAI Generator + Judge

The OpenAI judge imports `_serialize_response` from `openai_generator` rather than defining a copy:

```python
# eval/openai_judge.py
from enterprise_rag_ops.generation.openai_generator import _serialize_response
```

Both receive the identical `ChatCompletion` shape from `client.chat.completions.create`, so one implementation is the single source of truth.

## Common Mistakes

| Don't                                                           | Do                                                                        |
| --------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Build the request dict by reading `client._base_url` or headers | Build it from local vars (model, messages, params) before the API call    |
| Skip the fast path and always use manual fallback               | Try `model_dump(mode="json")` first — it is cheaper and complete          |
| Raise on serialization failure                                  | Catch all exceptions; return `{"_serialization_error": "<type>"}` instead |
| Duplicate `_serialize_response` for the OpenAI judge            | Import from `openai_generator`; same `ChatCompletion` shape               |

## Related

- `eval/raw_call.py` — `RawCall` model definition
- `rag-eval` → `concepts/eval-record-schema.md` — bronze/gold split (ADR-0010)
- `rag-eval` → `concepts/stats-capture-seam.md` — `generate_with_stats` / `judge_with_stats` rationale
- [concepts/per-provider-token-accounting.md](per-provider-token-accounting.md) — token field mapping (same defensive reads, different purpose)
