"""Tests for `StubGenerator` (FR-10)."""

from __future__ import annotations

from enterprise_rag_ops.generation.interfaces import Generator
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.generation.stub_generator import StubGenerator
from enterprise_rag_ops.retrieval.schema import Chunk


def test_stub_satisfies_generator_protocol():
    assert isinstance(StubGenerator(), Generator)


def test_stub_returns_answer_with_sources_echoing_doc_ids():
    chunks = [
        Chunk(chunk_id="doc_a::0", doc_id="doc_a", text="alpha"),
        Chunk(chunk_id="doc_b::0", doc_id="doc_b", text="beta"),
    ]
    result = StubGenerator().generate(chunks, "Q?")
    assert isinstance(result, AnswerWithSources)
    assert result.answer == "stub"
    assert result.sources == ["doc_a", "doc_b"]


def test_stub_is_deterministic():
    chunks = [Chunk(chunk_id="doc_a::0", doc_id="doc_a", text="alpha")]
    a = StubGenerator().generate(chunks, "Q?")
    b = StubGenerator().generate(chunks, "Q?")
    assert a == b
