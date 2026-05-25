"""CI-safe `Generator` (FR-10) — no API key, no network.

Used by `tests/generation/test_generation_contract.py` to exercise the full
pipeline wiring through the `Generator` seam (NFR-2, AC-11). Same shape as
`StubEmbedder` in `retrieval/embedder.py` — a deterministic drop-in.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.records import CallStats
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


class StubGenerator:
    """Returns deterministic `AnswerWithSources(answer="stub", sources=[doc_ids])`."""

    def generate(self, context_chunks: list[Chunk], question: str) -> AnswerWithSources:
        return AnswerWithSources(
            answer="stub",
            sources=[chunk.doc_id for chunk in context_chunks],
        )

    def generate_with_stats(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> tuple[AnswerWithSources, CallStats]:
        return self.generate(context_chunks, question), CallStats(
            input_tokens=0,
            output_tokens=0,
            latency_s=0.0,
            model="stub",
            system="openai",
            cost_usd=0.0,
        )
