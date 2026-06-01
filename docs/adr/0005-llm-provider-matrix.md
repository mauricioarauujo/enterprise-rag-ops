# ADR 0005: LLM Provider and Model Matrix for RAG Evaluation and Observability

## Status

accepted

## Date

2026-05-24

## Context

Production-grade RAG systems require systematic evaluation of their generation quality (faithfulness, answer recall) and downstream capabilities. Relying on a single LLM provider for both generation and evaluation raises concern about same-family bias (where a model or models from the same provider rate their own output higher or share similar systematic failures). Furthermore, developers need a cost-effective, low-latency setup for local development ($0 compute) alongside a production-grade remote setup.

We need to formalize which LLM providers and models are used, their roles (generator vs. judge), and how we resolve the same-family independence concern.

## Decision

We adopt the following LLM provider and model matrix:

1. **OpenAI**: Primary production-grade baseline.
   - **Generation**: `gpt-5-nano-2025-08-07` — the production default (`DEFAULT_MODEL` in `generation/openai_generator.py`, overridable via `RAG_GEN_MODEL`). Chosen for strong structured-output support (`strict: true`), low latency, and low cost.
   - **Evaluation (Judge)**: `gpt-4o` or `gpt-4o-mini` for fast judge feedback.

2. **Anthropic**: Primary multi-model generator.
   - Used in the multi-model sweeps (Phase 6) to run generation using `claude-3-5-haiku` or `claude-3-5-sonnet` to compare against the OpenAI baseline.
   - Serves as the cross-family generator to assess whether an OpenAI-based judge exhibits same-family bias.

3. **Ollama**: Local baseline.
   - Running local models (e.g. `llama3` or `mistral`) at $0 cost for local development and regression checks.

To handle same-family bias:

- During evaluation sweeps, we run cross-evaluations: we evaluate OpenAI generated answers with an Anthropic-based judge (and vice-versa) to isolate same-family scoring bias.

## Consequences

- Multi-model sweeps can run cleanly comparing OpenAI and Anthropic answers.
- Local development has a zero-cost path using Ollama.
- Prompts must remain model-agnostic where possible, or adapt schemas to each provider's capabilities.

## Amendment (2026-06-01) — Google / Gemini as third generator family

4. **Google (Gemini)**: Third multi-model generator (Sprint 4, Phase 10).
   - **Generation**: `gemini-2.5-flash-lite` — added to the multi-model sweep behind the
     proven `Generator` Protocol (`generation/gemini_generator.py`), overridable via env
     var `RAG_GEN_MODEL_GOOGLE`. Uses native JSON-schema structured output
     (`response_schema` in `GenerateContentConfig`); the output is re-validated our side
     via `AnswerWithSources.model_validate_json` (`extra="forbid"`).
   - **Schema-dialect note (provider friction, found at cassette-record time):** Gemini's
     structured-output schema dialect **rejects `additionalProperties`**, which
     `AnswerWithSources` emits via `extra="forbid"` (a live `400 INVALID_ARGUMENT`:
     "Unknown name `additional_properties`"). So the schema handed to the SDK is an
     **open mirror** (`_GeminiResponseSchema`, same fields, no `extra="forbid"`); the
     **closed**-schema contract is still enforced our side by `model_validate_json`. This is the
     per-provider structured-output divergence (OpenAI `strict` / Anthropic forced
     tool-use / Gemini open-schema-validated-our-side) — a candidate for the
     `rag-generation` KB.
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
