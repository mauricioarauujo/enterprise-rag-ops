"""Unit and integration tests for AnthropicGenerator (AC-4, AC-5)."""

from __future__ import annotations

import os

import pytest

from enterprise_rag_ops.generation.anthropic_generator import AnthropicGenerator
from enterprise_rag_ops.retrieval.schema import Chunk

# --- Fake client for offline testing (AC-4) ---------------------------------


class FakeToolUse:
    def __init__(self, input_data: dict) -> None:
        self.type = "tool_use"
        self.name = "emit_answer"
        self.input = input_data
        self.id = "fake_tool_use_id"


class FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeAnthropicMessage:
    def __init__(
        self, answer: str, sources: list[str], input_tokens: int = 15, output_tokens: int = 25
    ) -> None:
        self.content = [FakeToolUse({"answer": answer, "sources": sources})]
        self.usage = FakeUsage(input_tokens, output_tokens)


class FakeAnthropicClient:
    def __init__(self, answer: str, sources: list[str]) -> None:
        self.answer = answer
        self.sources = sources
        self.calls: list[dict] = []

        class Messages:
            def create(self_inner, **kwargs):
                self.calls.append(kwargs)
                return FakeAnthropicMessage(self.answer, self.sources)

        self.messages = Messages()


def test_anthropic_generator_offline_tool_use():
    """AC-4: AnthropicGenerator correctly extracts answer and sources via forced tool use."""
    fake_client = FakeAnthropicClient(answer="Haiku generated answer.", sources=["doc_abc"])
    generator = AnthropicGenerator(model="claude-3-5-haiku-test", client=fake_client)

    chunks = [Chunk(chunk_id="doc_abc::0", doc_id="doc_abc", text="Some reference text.")]
    result, stats = generator.generate_with_stats(chunks, "Test question?")

    assert result.answer == "Haiku generated answer."
    assert result.sources == ["doc_abc"]

    assert stats.input_tokens == 15
    assert stats.output_tokens == 25
    assert stats.latency_s > 0.0
    assert stats.model == "claude-3-5-haiku-test"
    assert stats.system == "anthropic"

    # Assert forced tool use parameters are sent
    assert len(fake_client.calls) == 1
    call_kwargs = fake_client.calls[0]
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "emit_answer"}
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0]["name"] == "emit_answer"


def test_anthropic_generator_missing_api_key_raises_runtime_error(monkeypatch):
    """AC-4: constructor raises clean RuntimeError when ANTHROPIC_API_KEY is missing."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        AnthropicGenerator()


# --- VCR cassette test (AC-5) ----------------------------------------------


@pytest.fixture
def vcr_record():
    """Configure VCR with record mode pointing to the shared eval cassettes folder."""
    import vcr

    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    return vcr.VCR(
        cassette_library_dir="tests/eval/cassettes",
        record_mode=record_mode,
        filter_headers=["x-api-key", "authorization"],
    )


@pytest.mark.vcr
def test_anthropic_generator_live_replay(vcr_record, monkeypatch):
    """AC-5: Live call replayed offline via VCR cassette (no network, no key)."""
    # Ensure ANTHROPIC_API_KEY is set to a dummy value so AnthropicGenerator initializes
    # without key checks when replaying offline.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-for-replay")

    generator = AnthropicGenerator()
    chunks = [
        Chunk(
            chunk_id="test_doc::0",
            doc_id="test_doc",
            text="The default port for HTTP traffic is 80; for HTTPS it is 443.",
        )
    ]
    question = "What is the default port for HTTP traffic?"

    with vcr_record.use_cassette("anthropic_generator.yaml"):
        result, stats = generator.generate_with_stats(chunks, question)

    assert "80" in result.answer
    assert result.sources == ["test_doc"]
    assert stats.input_tokens > 0
    assert stats.output_tokens > 0
    assert stats.system == "anthropic"
