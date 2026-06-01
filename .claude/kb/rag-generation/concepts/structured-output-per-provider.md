# structured-output-per-provider

> **Purpose**: The three divergent mechanisms that force `AnswerWithSources`-shaped JSON from OpenAI, Anthropic, and Google Gemini — and the single client-side invariant that unifies all three.
> **Confidence**: HIGH (codebase-grounded + ADR-0005 amendment + Context7 / google-genai SDK docs confirmed)
> **MCP Validated**: 2026-06-01

## Overview

All three providers return a validated `AnswerWithSources`. The forcing mechanism is different for each because their structured-output APIs diverge at the schema level. The unifying invariant is: **always re-validate our side via Pydantic**, regardless of what the provider enforced on their side.

## OpenAI — `strict: true` JSON Schema

```python
# openai_generator.py
json_schema = {
    "name": "AnswerWithSources",
    "schema": AnswerWithSources.model_json_schema(),  # includes additionalProperties:false
    "strict": True,
}
response = client.chat.completions.create(
    model=self._model,
    messages=[...],
    response_format={"type": "json_schema", "json_schema": json_schema},
)
raw = response.choices[0].message.content or ""
result = AnswerWithSources.model_validate_json(raw)   # second line of defense
```

`AnswerWithSources` is passed directly — its `extra="forbid"` maps to `additionalProperties: false`, which OpenAI's `strict: true` mode enforces server-side before the response is returned.

## Anthropic — Forced Tool-Use

Anthropic has no native JSON-schema structured output; the idiomatic pattern is to define a tool and force its invocation:

```python
# anthropic_generator.py
schema = AnswerWithSources.model_json_schema()
schema.pop("title", None)
tools = [{"name": "emit_answer", "description": "...", "input_schema": schema}]

response = client.messages.create(
    model=self._model,
    max_tokens=4096,
    system=system_prompt,
    messages=[{"role": "user", "content": user_prompt}],
    tools=tools,
    tool_choice={"type": "tool", "name": "emit_answer"},   # forced
)

# Parse the tool_use block
for block in response.content:
    if block.type == "tool_use" and block.name == "emit_answer":
        tool_use_block = block
        break

result = AnswerWithSources.model_validate(tool_use_block.input)  # dict, not JSON string
```

The `tool_choice={"type": "tool", "name": "emit_answer"}` forces the model to call exactly that tool. The response arrives as a structured dict inside `block.input`, so validation uses `.model_validate(dict)` rather than `.model_validate_json(str)`.

## Google Gemini — Open-Schema Mirror + Client-Side Close

**The hard-won lesson.** Passing `AnswerWithSources` directly to `response_schema` causes a live `400 INVALID_ARGUMENT` from the Gemini API:

> `Unknown name "additional_properties": Cannot find field in google.ai.generativelanguage.v1beta.Schema`

Gemini's structured-output schema dialect does not support `additionalProperties`, which `AnswerWithSources(extra="forbid")` emits. The fix is an open-schema mirror:

```python
# gemini_generator.py
class _GeminiResponseSchema(BaseModel):
    """Open mirror — no extra="forbid", so no additionalProperties in schema."""
    answer: str
    sources: list[str]

response = client.models.generate_content(
    model=self._model,
    contents=user_prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_GeminiResponseSchema,        # open — Gemini accepts this
        system_instruction=system_prompt,
    ),
)
result = AnswerWithSources.model_validate_json(response.text)  # closed enforcement our side
```

The `_GeminiResponseSchema` fields mirror `AnswerWithSources` exactly (verified by the test: `set(config.response_schema.model_fields) == set(AnswerWithSources.model_fields)`). If a future field is added to `AnswerWithSources` but not to the mirror, the test fails — preventing a silent schema drift in live calls.

## The Unifying Invariant

Every provider path ends with a Pydantic validation call:

| Provider  | Validation call                                          |
| --------- | -------------------------------------------------------- |
| OpenAI    | `AnswerWithSources.model_validate_json(raw)`             |
| Anthropic | `AnswerWithSources.model_validate(tool_use_block.input)` |
| Google    | `AnswerWithSources.model_validate_json(response.text)`   |

This means `extra="forbid"` is enforced our side for all three — a Gemini response with an extra field still raises `ValidationError` even though the Gemini schema did not declare `additionalProperties: false`.

## Common Mistakes

**Wrong (Gemini):**

```python
# Passes AnswerWithSources directly — causes 400 INVALID_ARGUMENT
config=types.GenerateContentConfig(response_schema=AnswerWithSources)
```

**Correct:**

```python
# Open mirror to Gemini; closed enforcement via model_validate_json our side
config=types.GenerateContentConfig(response_schema=_GeminiResponseSchema)
result = AnswerWithSources.model_validate_json(response.text)
```

## Related

- [concepts/generator-seam.md](generator-seam.md) — Protocol and dispatch
- [patterns/add-a-generator.md](../patterns/add-a-generator.md) — step-by-step recipe for a new provider
- ADR-0005 amendment (`docs/adr/0005-llm-provider-matrix.md`) — schema-dialect note
