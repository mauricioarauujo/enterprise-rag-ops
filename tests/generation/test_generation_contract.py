"""Offline pipeline-contract test (FR-11, AC-11, NFR-1).

Wires fixture retriever (chunk hits) + fixture store + `ContextAssembler` +
`StubGenerator` through the `Generator` seam. No network, no API key, no model
download — exercises the full
`(chunk_id, doc_id, score) → list[Chunk] → AnswerWithSources` wiring.
"""

from __future__ import annotations

from enterprise_rag_ops.generation.context import ContextAssembler
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.generation.stub_generator import StubGenerator


def test_full_pipeline_with_stub_generator(fixture_retriever, fixture_store):
    """Retriever chunk hits → assembler → stub generator yields AnswerWithSources."""
    chunk_hits = fixture_retriever.retrieve_chunks("any question")
    context = ContextAssembler(store=fixture_store).assemble(chunk_hits)
    result = StubGenerator().generate(context, "any question")

    assert isinstance(result, AnswerWithSources)
    # Sources echo the retrieval order (fused-rank order preserved by assembler).
    assert result.sources == ["doc_a", "doc_b"]


def test_full_pipeline_unique_doc_ids_in_sources(fixture_retriever, fixture_store):
    """Sources must contain no duplicate doc_ids (best-chunk-per-doc → stub echo)."""
    chunk_hits = fixture_retriever.retrieve_chunks("any question")
    context = ContextAssembler(store=fixture_store).assemble(chunk_hits)
    result = StubGenerator().generate(context, "any question")
    assert len(result.sources) == len(set(result.sources))
