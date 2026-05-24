"""Phase 4 judge seam (FR-5, NFR-3).

Mirrors `generation/interfaces.py`. The named future swap is **ADR-0005**'s
cross-family judge — a `ClaudeJudge`, or an Ollama-backed judge via `base_url`, is a new
file implementing this Protocol plus a one-line wiring change at the call site. No
alternative implementations are pre-built in Phase 4, and the contract makes no
same-family assumption (Q2).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from enterprise_rag_ops.eval.schema import JudgeVerdict
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


@runtime_checkable
class Judge(Protocol):
    """Scores an `AnswerWithSources` against gold facts + the docs it cited."""

    def judge(
        self,
        question: str,
        answer_with_sources: AnswerWithSources,
        answer_facts: list[str],
        retrieved_docs: list[Chunk],
    ) -> JudgeVerdict:
        """Return a `JudgeVerdict` for one answer.

        Synchronous and single-call (Q1). `answer_facts` is the gold per-fact
        checklist; `retrieved_docs` supplies the per-`doc_id` text used to verify
        each citation in `answer_with_sources.sources`.
        """
        ...
