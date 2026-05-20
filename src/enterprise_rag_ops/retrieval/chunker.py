"""Uniform fixed-size chunking — one strategy for all source types (FR-2).

`RecursiveCharacterTextSplitter` from `langchain-text-splitters` is the
battle-tested splitter pinned by RQ-3: less custom code to own than a bespoke
implementation. The same instance is reused for every `Document`, and there is
no per-source branching — that uniformity is what makes recall comparisons
across sources meaningful in the Sprint 2 eval harness.
"""

from __future__ import annotations

from collections.abc import Iterable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.retrieval import config
from enterprise_rag_ops.retrieval.schema import Chunk


def _make_splitter() -> RecursiveCharacterTextSplitter:
    """Construct the splitter once with the Phase 2 defaults."""
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )


def chunk_document(
    document: Document,
    splitter: RecursiveCharacterTextSplitter | None = None,
) -> list[Chunk]:
    """Split a single `Document` into chunks; preserve `doc_id` on each chunk.

    `chunk_id` is deterministic: ``f"{document.id}::{offset}"`` where ``offset``
    is the 0-based position of the chunk within the document. Determinism is
    required by NFR-2 (re-running the build on the same corpus produces a
    functionally equivalent index).
    """
    splitter = splitter or _make_splitter()
    texts = splitter.split_text(document.text)
    return [
        Chunk(chunk_id=f"{document.id}::{offset}", doc_id=document.id, text=text)
        for offset, text in enumerate(texts)
    ]


def chunk_documents(documents: Iterable[Document]) -> list[Chunk]:
    """Chunk every document in `documents`, returning one ordered chunk list.

    The returned list is the single ordered sequence shared by the BM25 index,
    the embedding matrix, and the LanceDB rows (DESIGN risk: position↔chunk_id
    mapping must come from one ordered source).
    """
    splitter = _make_splitter()
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_document(doc, splitter=splitter))
    return chunks
