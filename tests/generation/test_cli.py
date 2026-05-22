"""Tests for the `rag-ask` CLI (FR-8, FR-9, AC-8, AC-14, AC-18).

Focused on the wiring: abstention short-circuit, clean error on missing
`OPENAI_API_KEY`, observability logging, JSON output shape. No real OpenAI
calls (those are exercised by the local-only `make smoke` smoke test).
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from enterprise_rag_ops.generation import cli as cli_mod
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.generation.stub_generator import StubGenerator
from enterprise_rag_ops.retrieval.schema import Chunk


class _SpyGenerator:
    """`Generator`-shaped spy: records whether `.generate` was called."""

    def __init__(self) -> None:
        self.called = False

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        self.called = True
        return AnswerWithSources(answer="should not be called", sources=[])


class _StubRetriever:
    def __init__(self, chunk_hits: list[tuple[str, str, float]]) -> None:
        self._chunk_hits = chunk_hits

    def retrieve_chunks(self, query, top_k=10, source_type_filter=None):
        return list(self._chunk_hits)


class _FakeStore:
    """`VectorStore`-shaped fake — fetch the given chunks by chunk_id."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

    def fetch_chunks_by_chunk_ids(self, chunk_ids):
        requested = set(chunk_ids)
        return [c for c in self._chunks if c.chunk_id in requested]


def test_abstain_short_circuit_does_not_call_generator(monkeypatch, capsys):
    """AC-8: empty retriever output → fixed abstain answer, no Generator call."""
    spy = _SpyGenerator()
    monkeypatch.setattr(cli_mod.pipeline, "load_retriever", lambda: _StubRetriever([]))
    monkeypatch.setattr(cli_mod, "OpenAIGenerator", lambda: spy)
    # LanceDBStore.open must NOT be reached on the abstain path either.
    monkeypatch.setattr(
        cli_mod.LanceDBStore,
        "open",
        classmethod(lambda cls, *a, **kw: pytest.fail("LanceDBStore.open called on abstain path")),
    )

    rc = cli_mod.main(["What is the meaning of life?"])
    assert rc == 0
    assert spy.called is False

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload == {"answer": cli_mod.ABSTAIN_ANSWER, "sources": []}


_HITS = [("doc_a::3", "doc_a", 0.9), ("doc_b::1", "doc_b", 0.7)]
_CHUNKS = [
    Chunk(chunk_id="doc_a::3", doc_id="doc_a", text="alpha"),
    Chunk(chunk_id="doc_b::1", doc_id="doc_b", text="beta"),
]


def test_happy_path_wires_assembler_through_generator(monkeypatch, capsys):
    """Non-empty retriever → assembler → injected generator → JSON to stdout."""
    monkeypatch.setattr(cli_mod.pipeline, "load_retriever", lambda: _StubRetriever(_HITS))
    monkeypatch.setattr(
        cli_mod.LanceDBStore, "open", classmethod(lambda cls, *a, **kw: _FakeStore(_CHUNKS))
    )
    monkeypatch.setattr(cli_mod, "OpenAIGenerator", StubGenerator)

    rc = cli_mod.main(["Q?"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["sources"] == ["doc_a", "doc_b"]
    assert payload["answer"] == "stub"


def test_happy_path_logs_context_doc_ids_and_sources(monkeypatch, capsys, caplog):
    """AC-18 / NFR-5: CLI emits an INFO record with post-assembler doc_ids + sources."""
    monkeypatch.setattr(cli_mod.pipeline, "load_retriever", lambda: _StubRetriever(_HITS))
    monkeypatch.setattr(
        cli_mod.LanceDBStore, "open", classmethod(lambda cls, *a, **kw: _FakeStore(_CHUNKS))
    )
    monkeypatch.setattr(cli_mod, "OpenAIGenerator", StubGenerator)

    with caplog.at_level(logging.INFO, logger="enterprise_rag_ops.generation.cli"):
        cli_mod.main(["Q?"])

    records = [r.getMessage() for r in caplog.records]
    assert any("context_doc_ids=" in m and "sources=" in m for m in records), records
    # Both the retrieved doc_ids and the cited sources must appear in the log line.
    line = next(m for m in records if "context_doc_ids=" in m)
    assert "doc_a" in line and "doc_b" in line


def test_missing_openai_api_key_raises_clean_runtime_error(monkeypatch):
    """AC-14 / NFR-7: clean message, not an SDK stack trace."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAIGenerator()


def test_cli_reads_question_from_stdin_when_arg_omitted(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod.pipeline, "load_retriever", lambda: _StubRetriever([]))
    monkeypatch.setattr("sys.stdin", io.StringIO("What is alpha?\n"))
    rc = cli_mod.main([])
    assert rc == 0
    assert "alpha" not in capsys.readouterr().out  # only the abstain JSON; not the question
