# generator-seam

> **Purpose**: The `Generator` Protocol, the `AnswerWithSources` output contract, abstention handling, the model-agnostic shared prompt, and the `_GENERATOR_FACTORY` dispatch.
> **Confidence**: HIGH (codebase + ADR-0003 + ADR-0005)
> **MCP Validated**: 2026-06-01

## Overview

The generation layer is a single Protocol seam that hides three concrete LLM providers behind an identical interface. All wiring knowledge lives in three files: `generation/interfaces.py` (the seam), `generation/schema.py` (the output contract), and `eval/runner.py` (the dispatch). Nothing else in the package imports provider-specific SDK modules.

## The Protocol

```python
# generation/interfaces.py
@runtime_checkable
class Generator(Protocol):
    def generate(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> AnswerWithSources: ...
```

Every concrete implementation (`OpenAIGenerator`, `AnthropicGenerator`, `GeminiGenerator`, `StubGenerator`) adds `generate_with_stats` on top of `generate`:

```python
def generate(self, context_chunks, question) -> AnswerWithSources:
    result, _, _ = self.generate_with_stats(context_chunks, question)
    return result

def generate_with_stats(
    self, context_chunks, question
) -> tuple[AnswerWithSources, CallStats, RawCall]: ...
```

`generate_with_stats` returns a **3-tuple**: the validated answer, token/latency stats, and a `RawCall` transport holding the raw request and serialized response for bronze storage (ADR-0010). `generate_with_stats` is **off-Protocol** — the `Generator` Protocol exposes only `generate`. See `rag-eval` → `concepts/stats-capture-seam.md` for the seam rationale and `concepts/raw-payload-serialization.md` for the `RawCall` and `_serialize_response` algorithm.

## Output Contract: AnswerWithSources

```python
# generation/schema.py
class AnswerWithSources(BaseModel):
    model_config = ConfigDict(extra="forbid")   # closed schema
    answer: str
    sources: list[str]                          # doc_id values cited

ABSTAIN_ANSWER = "I don't have enough information to answer this question."
```

**Invariants:**

- `extra="forbid"` serializes to `additionalProperties: false` in JSON Schema. OpenAI's `strict: true` enforces this server-side; other providers enforce it client-side via Pydantic re-validation.
- `ABSTAIN_ANSWER` is the single sentinel string. It lives in `schema.py` to be importable by both `cli.py` (retrieval gate) and `prompt.py` (generator instruction) without an import cycle.
- Abstention is handled upstream: the retrieval gate short-circuits without an LLM call when `retrieve_chunks()` returns `[]`. The generator prompt also instructs the model to emit the exact sentinel when context is insufficient.

## Model-Agnostic Shared Prompt

```python
# generation/prompt.py — pure functions, no I/O
def build_system_prompt() -> str:
    # Role + abstention instruction + AnswerWithSources JSON schema
    ...

def build_user_prompt(context_chunks: list[Chunk], question: str) -> str:
    # "[1] doc_id: text\n[2] doc_id: text\n...\n\nquestion"
    ...
```

Both functions are pure and deterministic (byte-identical output for identical inputs). All three providers call them unchanged — the prompt is provider-agnostic.

## Dispatch: `_GENERATOR_FACTORY`

```python
# eval/runner.py
_GENERATOR_FACTORY = {
    "openai":     OpenAIGenerator,
    "anthropic":  AnthropicGenerator,
    "google":     GeminiGenerator,
}
```

`model.system` (from `RunConfig`) is the dict key. Adding a fourth provider is one new entry here plus the matching implementation file.

## Seam Justification

ADR-0003 names the Generator Protocol as the fourth seam (alongside `Embedder`, `VectorStore`, `Retriever` from Sprint 1). The swap surface is explicitly scoped: a new provider = one new `<provider>_generator.py` file + one `_GENERATOR_FACTORY` line. No other file changes.

## Related

- [concepts/structured-output-per-provider.md](structured-output-per-provider.md) — how each provider forces the schema
- [concepts/per-provider-token-accounting.md](per-provider-token-accounting.md) — CallStats field mapping
- [concepts/raw-payload-serialization.md](raw-payload-serialization.md) — RawCall model, \_serialize_response algorithm, privacy guarantee
- [patterns/add-a-generator.md](../patterns/add-a-generator.md) — full add-a-provider recipe
- ADR-0003 (`docs/adr/0003-generation.md`) — seam decision + abstention design
- ADR-0005 (`docs/adr/0005-llm-provider-matrix.md`) — three-provider matrix + Gemini amendment
