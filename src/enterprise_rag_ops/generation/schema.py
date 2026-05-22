"""Canonical generation output schema (FR-1).

`AnswerWithSources` is the single schema source-of-truth shared by:
  - the `Generator` Protocol return type,
  - the OpenAI structured-output JSON schema (via `model_json_schema()`),
  - the `rag-ask` CLI stdout payload,
  - Sprint 2's eval-harness input.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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
