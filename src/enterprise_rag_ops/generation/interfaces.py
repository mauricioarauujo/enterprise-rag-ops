"""Phase 3 generation seam (FR-2, NFR-2).

Mirrors `retrieval/interfaces.py`. The named future swap is ADR-005's LLM
matrix — a `ClaudeGenerator` or `OllamaGenerator` is a new file implementing
this Protocol plus a one-line wiring change in `generation/cli.py`. No
alternative implementations are pre-built in Phase 3.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


@runtime_checkable
class Generator(Protocol):
    """Produces an `AnswerWithSources` from assembled context + question."""

    def generate(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> AnswerWithSources:
        """Return an `AnswerWithSources` for the question grounded in context.

        Callers handle abstention upstream (the empty-retrieval short-circuit
        in `rag-ask`); implementations may assume `context_chunks` is non-empty.
        """
        ...
