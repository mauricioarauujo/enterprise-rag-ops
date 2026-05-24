# Schema-as-SSoT with a Private LLM-Facing Subset

> **Purpose**: How `_LLMJudgeVerdict` keeps the aggregate floats out of the `strict`
> JSON schema while `JudgeVerdict` remains the single source of truth for the eval
> layer's public output.
> **Confidence**: HIGH (codebase + MCP)
> **MCP Validated**: 2026-05-24

## Overview

OpenAI `strict: true` mode requires that **every** property in the schema is in
`required` and every nested object has `additionalProperties: false`. This is
incompatible with optional fields: you cannot have `fact_recall: float | None` with
`default=None` in a strict schema, because `strict` requires the LLM to emit all
fields. The solution is a two-model split:

- **`_LLMJudgeVerdict`** — private, two-list only; this is what the LLM sees.
- **`JudgeVerdict`** — public, two lists + three floats; this is what callers receive.

The floats are Python-derived and never emitted by the LLM.

## The Split

```python
# eval/schema.py

class _LLMJudgeVerdict(BaseModel):
    """LLM-facing surface — the two verdict lists only."""
    model_config = ConfigDict(extra="forbid")
    per_fact: list[FactVerdict]
    per_citation: list[CitationVerdict]

class JudgeVerdict(BaseModel):
    """Public output — two lists + Python-derived floats."""
    model_config = ConfigDict(extra="forbid")
    per_fact: list[FactVerdict]
    per_citation: list[CitationVerdict]
    fact_recall: float | None = Field(default=None, ...)
    fact_precision: float | None = Field(default=None, ...)
    faithfulness_ratio: float | None = Field(default=None, ...)
```

## Wiring in `OpenAIJudge`

```python
# eval/openai_judge.py — the three-step pattern

# 1. Feed only the LLM-facing schema to strict mode
json_schema = {
    "name": "JudgeVerdict",
    "schema": _LLMJudgeVerdict.model_json_schema(),
    "strict": True,
}

# 2. Re-validate returned JSON through the private model (typed ValidationError on drift)
llm_verdict = _LLMJudgeVerdict.model_validate_json(raw)

# 3. Derive floats in Python, then assemble the public model
fact_recall, fact_precision, faithfulness_ratio = aggregate(
    llm_verdict.per_fact, llm_verdict.per_citation
)
return JudgeVerdict(
    per_fact=llm_verdict.per_fact,
    per_citation=llm_verdict.per_citation,
    fact_recall=fact_recall,
    fact_precision=fact_precision,
    faithfulness_ratio=faithfulness_ratio,
)
```

No hand-maintained parallel schema string — the schema is always
`_LLMJudgeVerdict.model_json_schema()`. Pydantic v2 emits `additionalProperties:
false` for `extra="forbid"` models, satisfying `strict`'s requirement without extra
tooling.

## Why Not Feed `JudgeVerdict.model_json_schema()` Directly

If `JudgeVerdict` was fed to `strict` mode, the schema would include the three floats
as required fields. The LLM would be asked to emit `fact_recall` / `fact_precision` /
`faithfulness_ratio` directly — values it computes unreliably (it may disagree with
its own verdict list). Python derivation is deterministic and auditable; LLM-emitted
ratios are not.

## MCP Corroboration

OpenAI API docs confirm the `strict` requirement (source: developers.openai.com):

> `strict: true` — whether the schema is strict; requires all properties in
> `required` and `additionalProperties: false` on every nested object.

Pydantic v2 docs confirm (source: pydantic.dev):

> `extra='forbid'` raises `ValidationError` for any extra fields and emits
> `additionalProperties: false` in `model_json_schema()`.

The two-model split is therefore the minimal pattern: one Pydantic model per schema
surface, no hand-maintained JSON, no float friction in the strict contract.

## Pattern Reuse

This pattern (private LLM-facing subset + public output model with Python-derived
fields) is directly reusable for any structured-output workflow where:

- Some output fields are derived, not emitted.
- The derived fields would cause `strict` friction (optional / computed).
- You want a single code-level SSoT, not a parallel JSON string.

The generation layer uses `AnswerWithSources` as its public model — the eval layer
refines the pattern by adding the private `_LLMJudgeVerdict` split.

## Related

- [../patterns/per-fact-judge-call.md](../patterns/per-fact-judge-call.md)
- [none-empty-denominator.md](none-empty-denominator.md)
- `eval/schema.py`, `eval/openai_judge.py`
- `docs/adr/0001-eval-framework.md` § Schema as SSoT
