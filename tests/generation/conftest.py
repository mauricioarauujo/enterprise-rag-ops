"""Shared fixtures for generation tests.

The fixture store is a minimal `VectorStore`-shaped fake that satisfies the
single Protocol method `ContextAssembler` calls — no LanceDB on disk needed
for the offline pipeline-contract path (NFR-1).
"""

from __future__ import annotations

import pytest

from enterprise_rag_ops.retrieval.schema import Chunk


class FakeVectorStore:
    """`VectorStore`-shaped fake — only `fetch_chunks_by_chunk_ids` is exercised."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

    def fetch_chunks_by_chunk_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        requested = set(chunk_ids)
        return [c for c in self._chunks if c.chunk_id in requested]


class FakeRetriever:
    """`Retriever`-shaped fake — returns pre-canned chunk hits."""

    def __init__(self, chunk_hits: list[tuple[str, str, float]]) -> None:
        self._chunk_hits = chunk_hits

    def retrieve_chunks(
        self,
        query: str,
        top_k: int = 10,
        source_type_filter: str | None = None,
    ) -> list[tuple[str, str, float]]:
        return list(self._chunk_hits)


@pytest.fixture
def fixture_chunks() -> list[Chunk]:
    return [
        Chunk(chunk_id="doc_a::3", doc_id="doc_a", text="The PTO policy allows 20 days off."),
        Chunk(chunk_id="doc_b::1", doc_id="doc_b", text="Deploy freeze starts Friday 5pm PT."),
        Chunk(
            chunk_id="doc_c::2",
            doc_id="doc_c",
            text="SEV1 incidents require a page within 5 minutes.",
        ),
    ]


@pytest.fixture
def fixture_store(fixture_chunks) -> FakeVectorStore:
    return FakeVectorStore(fixture_chunks)


@pytest.fixture
def fixture_retriever() -> FakeRetriever:
    # Winning (relevant) chunk per doc — note non-zero chunk offsets, the case
    # the old lex-smallest policy got wrong.
    return FakeRetriever([("doc_a::3", "doc_a", 0.92), ("doc_b::1", "doc_b", 0.71)])
