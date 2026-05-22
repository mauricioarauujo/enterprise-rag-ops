"""Tests for the prompt builder (FR-7, AC-7)."""

from __future__ import annotations

from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.retrieval.schema import Chunk


def test_system_prompt_is_byte_identical_across_calls():
    """AC-7: same inputs → byte-identical output."""
    assert build_system_prompt() == build_system_prompt()


def test_system_prompt_includes_schema_and_role():
    prompt = build_system_prompt()
    assert "enterprise knowledge assistant" in prompt
    assert '"answer"' in prompt
    assert '"sources"' in prompt
    assert "additionalProperties" in prompt


def test_user_prompt_numbered_context_format():
    chunks = [
        Chunk(chunk_id="doc_a::0", doc_id="doc_a", text="alpha"),
        Chunk(chunk_id="doc_b::0", doc_id="doc_b", text="beta"),
    ]
    prompt = build_user_prompt(chunks, "What is alpha?")
    assert prompt == "[1] doc_a: alpha\n[2] doc_b: beta\n\nWhat is alpha?"


def test_user_prompt_is_byte_identical_across_calls():
    chunks = [Chunk(chunk_id="doc_a::0", doc_id="doc_a", text="alpha")]
    assert build_user_prompt(chunks, "Q?") == build_user_prompt(chunks, "Q?")


def test_user_prompt_empty_context_still_includes_question():
    """Defensive — abstention short-circuits upstream, but the function must not crash."""
    prompt = build_user_prompt([], "Q?")
    assert prompt.endswith("Q?")
