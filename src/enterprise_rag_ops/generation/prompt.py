"""Deterministic prompt construction (FR-7, NFR-4).

Pure functions — no LLM client, no I/O, no env reads. AC-7 asserts byte-identical
output across two invocations with identical inputs.
"""

from __future__ import annotations

import json

from enterprise_rag_ops.generation.schema import ABSTAIN_ANSWER, AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

_ROLE = (
    "You are an enterprise knowledge assistant. Answer the user's question "
    "using only the numbered context provided. Cite the doc_id of every "
    "context entry you used in the `sources` field. If the context does not "
    "contain enough information to answer, you MUST set `answer` to exactly "
    f'this string — "{ABSTAIN_ANSWER}" — and return an empty `sources` list. '
    "Do not answer from prior knowledge."
)


def build_system_prompt() -> str:
    """System prompt = role + JSON output instruction + schema (Decision 4-B)."""
    schema_json = json.dumps(AnswerWithSources.model_json_schema(), indent=2, sort_keys=True)
    return f"{_ROLE}\n\nRespond with a single JSON object matching this schema:\n{schema_json}"


def build_user_prompt(context_chunks: list[Chunk], question: str) -> str:
    """User turn = numbered context block + question (FR-7).

    Format: ``[1] {doc_id}: {text}\\n[2] {doc_id}: {text}\\n...\\n\\n{question}``.
    Numbering is 1-based and matches the order of `context_chunks` (already in
    fused-rank order from `ContextAssembler`).
    """
    lines = [
        f"[{i}] {chunk.doc_id}: {chunk.text}" for i, chunk in enumerate(context_chunks, start=1)
    ]
    context_block = "\n".join(lines)
    return f"{context_block}\n\n{question}"
