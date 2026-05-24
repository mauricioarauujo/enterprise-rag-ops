"""Deterministic judge-prompt construction (FR-6, NFR-2).

Pure functions — no LLM client, no I/O, no env reads. Identical inputs yield
byte-identical output. Mirrors `generation/prompt.py`.

The faithfulness signal lives in how cited docs are rendered: **one separately named
block per cited `doc_id`** (`=== doc {doc_id} ===`), never a merged context blob. That
per-`doc_id` isolation is what lets the judge answer "does *this* doc support the claim?"
— the direct discriminator the anchor case exploits. A cited doc absent from the
retrieved set is rendered as an explicit `(text unavailable)` block so the judge can
still return `unsupported` rather than the citation silently vanishing.
"""

from __future__ import annotations

import json

from enterprise_rag_ops.eval.schema import _LLMJudgeVerdict

_ROLE = (
    "You are a strict RAG evaluation judge. You score a generated answer against a "
    "checklist of gold facts, and you verify that each document the answer cited "
    "actually supports the claim it was cited for. Judge only the text provided — "
    "never use outside knowledge."
)

_RUBRIC = (
    "For EACH numbered gold fact, emit one per_fact entry (same order) with verdict:\n"
    "  - present: the answer states this fact.\n"
    "  - absent: the answer does not mention this fact.\n"
    "  - contradicted: the answer asserts something that conflicts with this fact.\n"
    "For EACH cited document block, emit one per_citation entry (same order) with verdict:\n"
    "  - supported: that document's text substantiates the claim it was cited for.\n"
    "  - unsupported: that document's text does not substantiate the claim (or is "
    "unavailable)."
)


def build_judge_system_prompt() -> str:
    """System prompt = role + scoring rubric + LLM-facing JSON schema.

    The schema is the `_LLMJudgeVerdict` surface (the two verdict lists only); the
    aggregate floats are derived in Python and are not part of the LLM contract.
    """
    schema_json = json.dumps(_LLMJudgeVerdict.model_json_schema(), indent=2, sort_keys=True)
    return (
        f"{_ROLE}\n\n{_RUBRIC}\n\n"
        f"Respond with a single JSON object matching this schema:\n{schema_json}"
    )


def build_judge_user_prompt(
    question: str,
    answer: str,
    answer_facts: list[str],
    cited_docs: list[tuple[str, str | None]],
) -> str:
    """User turn = question + answer + numbered fact checklist + per-doc_id blocks.

    Args:
        question: The original question.
        answer: The answer text being judged.
        answer_facts: Gold facts, rendered as a 1-based numbered checklist.
        cited_docs: `(doc_id, text)` pairs in the answer's citation order. A `None`
            text marks a cited doc that was not in the retrieved set; it is rendered
            as an explicit ``(text unavailable)`` block.
    """
    facts_block = "\n".join(f"{i}. {fact}" for i, fact in enumerate(answer_facts, start=1))

    doc_blocks = []
    for doc_id, text in cited_docs:
        if text is None:
            doc_blocks.append(f"=== doc {doc_id} (text unavailable) ===")
        else:
            doc_blocks.append(f"=== doc {doc_id} ===\n{text}")
    cited_block = "\n\n".join(doc_blocks)

    return (
        f"QUESTION:\n{question}\n\n"
        f"ANSWER UNDER JUDGMENT:\n{answer}\n\n"
        f"GOLD FACTS (one per_fact verdict each, in order):\n{facts_block}\n\n"
        f"CITED DOCUMENTS (one per_citation verdict each, in order):\n{cited_block}"
    )
