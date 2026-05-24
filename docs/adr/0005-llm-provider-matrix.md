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
