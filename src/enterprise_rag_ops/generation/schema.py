"""Canonical generation output schema (FR-1).

`AnswerWithSources` is the single schema source-of-truth shared by:
  - the `Generator` Protocol return type,
  - the OpenAI structured-output JSON schema (via `model_json_schema()`),
  - the `rag-ask` CLI stdout payload,
  - Sprint 2's eval-harness input.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Canonical abstention sentinel — the single string the system emits when it
# cannot answer from the retrieved context. Lives here (not in `cli.py`) so both
# abstention points can share it without an import cycle:
#   - the `rag-ask` retrieval gate (`cli.py`, empty-retrieval short-circuit), and
#   - the generator prompt (`prompt.py`), which instructs the model to emit it
#     verbatim when the context is insufficient.
# Sprint 2's eval imports it as SSoT (NFR-5) and exact-matches against it.
ABSTAIN_ANSWER = "I don't have enough information to answer this question."


class AnswerWithSources(BaseModel):
    """An LLM-produced answer with cited document identifiers.

    Fields:
        answer: Natural-language answer string. Empty string is allowed by the
            schema but flagged by the smoke gate (AC-13).
        sources: List of `doc_id` strings cited as evidence. Order is the order
            the model emitted them; deduplication is the model's responsibility.

    Invariants:
        - Both fields are required (Pydantic raises `ValidationError` on
          missing or wrong type — AC-1).
        - The schema is closed (`extra="forbid"` → `additionalProperties: false`
          in JSON Schema), so OpenAI `strict: true` mode rejects any extra fields.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(description="Natural-language answer to the user question.")
    sources: list[str] = Field(description="doc_id values cited as evidence for the answer.")
