"""Tests for `ContextAssembler` (FR-6, AC-6)."""

from __future__ import annotations

import pytest

from enterprise_rag_ops.generation.context import DEFAULT_MAX_CHUNKS, ContextAssembler
from enterprise_rag_ops.retrieval.schema import Chunk


class _FakeStore:
    """Minimal `VectorStore`-shaped fake — only `fetch_chunks_by_chunk_ids` used."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

    def fetch_chunks_by_chunk_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        requested = set(chunk_ids)
        # Return in store-native order — assembler must restore rank order.
        return [c for c in self._chunks if c.chunk_id in requested]


def _chunk(doc_id: str, offset: int, text: str = "...") -> Chunk:
    return Chunk(chunk_id=f"{doc_id}::{offset}", doc_id=doc_id, text=text)


def _hit(chunk_id: str, doc_id: str, score: float) -> tuple[str, str, float]:
    return (chunk_id, doc_id, score)


def test_empty_hits_returns_empty():
    assembler = ContextAssembler(store=_FakeStore([]))
    assert assembler.assemble([]) == []


def test_fetches_the_winning_chunk_not_the_lex_smallest():
    """The relevant (ranked) chunk reaches the LLM — the bug the live smoke caught.

    doc_a's winning chunk is `::5`; the store also holds `::0` (a title). The
    assembler must surface `::5` because that is the ranked hit, never `::0`.
    """
    store = _FakeStore(
        [_chunk("doc_a", 0, "title"), _chunk("doc_a", 5, "the answer"), _chunk("doc_b", 1, "b")]
    )
    assembler = ContextAssembler(store=store)
    result = assembler.assemble([_hit("doc_a::5", "doc_a", 0.9), _hit("doc_b::1", "doc_b", 0.8)])
    assert [c.chunk_id for c in result] == ["doc_a::5", "doc_b::1"]
    assert [c.text for c in result] == ["the answer", "b"]


def test_preserves_fused_rank_order():
    """Output order matches the order of `chunk_hits`, not the store's order."""
    store = _FakeStore([_chunk("doc_a", 0), _chunk("doc_b", 0), _chunk("doc_c", 0)])
    assembler = ContextAssembler(store=store)
    result = assembler.assemble(
        [
            _hit("doc_c::0", "doc_c", 0.9),
            _hit("doc_a::0", "doc_a", 0.5),
            _hit("doc_b::0", "doc_b", 0.1),
        ]
    )
    assert [c.doc_id for c in result] == ["doc_c", "doc_a", "doc_b"]


def test_truncates_to_max_chunks():
    store = _FakeStore([_chunk(f"doc_{i}", 0) for i in range(10)])
    assembler = ContextAssembler(store=store, max_chunks=3)
    hits = [_hit(f"doc_{i}::0", f"doc_{i}", 1.0 - i * 0.05) for i in range(10)]
    result = assembler.assemble(hits)
    assert len(result) == 3
    assert [c.doc_id for c in result] == ["doc_0", "doc_1", "doc_2"]


def test_default_max_chunks_is_5():
    store = _FakeStore([_chunk(f"doc_{i}", 0) for i in range(10)])
    assembler = ContextAssembler(store=store)
    hits = [_hit(f"doc_{i}::0", f"doc_{i}", 1.0) for i in range(10)]
    assert len(assembler.assemble(hits)) == DEFAULT_MAX_CHUNKS


def test_skips_chunk_absent_from_store():
    """Stale-index defense: a hit whose chunk_id is not in the store is dropped."""
    store = _FakeStore([_chunk("doc_a", 0), _chunk("doc_c", 0)])
    assembler = ContextAssembler(store=store)
    result = assembler.assemble(
        [
            _hit("doc_a::0", "doc_a", 0.9),
            _hit("gone::0", "gone", 0.5),
            _hit("doc_c::0", "doc_c", 0.1),
        ]
    )
    assert [c.doc_id for c in result] == ["doc_a", "doc_c"]


def test_invalid_max_chunks_raises():
    with pytest.raises(ValueError, match="max_chunks must be positive"):
        ContextAssembler(store=_FakeStore([]), max_chunks=0)
    with pytest.raises(ValueError, match="max_chunks must be positive"):
        ContextAssembler(store=_FakeStore([]), max_chunks=-1)
