"""Unit tests for OpenAIGenerator's generate_with_stats implementation (AC-3)."""

from __future__ import annotations

from types import SimpleNamespace

from enterprise_rag_ops.generation.interfaces import Generator
from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator
from enterprise_rag_ops.retrieval.schema import Chunk


class FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeOpenAIClient:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        usage = FakeUsage(self.prompt_tokens, self.completion_tokens)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def test_openai_generator_generate_with_stats():
    """AC-3: OpenAIGenerator.generate_with_stats times call and returns AnswerWithSources + CallStats."""
    canned_payload = '{"answer": "Paris is the capital.", "sources": ["doc_1"]}'
    fake_client = FakeOpenAIClient(canned_payload, prompt_tokens=120, completion_tokens=40)

    generator = OpenAIGenerator(model="gpt-5-nano-test", client=fake_client)
    chunks = [Chunk(chunk_id="doc_1::0", doc_id="doc_1", text="Paris is the capital of France.")]

    result, stats = generator.generate_with_stats(chunks, "What is the capital of France?")

    assert result.answer == "Paris is the capital."
    assert result.sources == ["doc_1"]

    assert stats.input_tokens == 120
    assert stats.output_tokens == 40
    assert stats.latency_s > 0.0
    assert stats.model == "gpt-5-nano-test"
    assert stats.system == "openai"

    # Assert generator protocol is untouched: only generate method is in Protocol methods
    assert issubclass(OpenAIGenerator, Generator)
    # Check that Generator protocol itself only specifies generate
    protocol_methods = [m for m in dir(Generator) if not m.startswith("_")]
    assert "generate" in protocol_methods
    assert "generate_with_stats" not in protocol_methods
