"""Canonical document model and ingest errors.

`Document` is the contract every downstream phase consumes: ingest produces it,
Phase 2 retrieval indexes it. It is the validation boundary — adapters hand raw
dataset records here, and malformed records are rejected rather than propagated.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class UnknownSourceTypeError(ValueError):
    """Raised when a dataset record carries a `source_type` with no registered adapter.

    Surfacing this loudly (rather than dropping the record) is required by FR-3:
    a new source type appearing in a future dataset revision must fail ingest, not
    silently shrink the corpus.
    """

    def __init__(self, source_type: str) -> None:
        super().__init__(
            f"No adapter registered for source_type {source_type!r}. "
            "Add it to enterprise_rag_ops.ingest.config.SOURCE_TYPES."
        )
        self.source_type = source_type


class Document(BaseModel):
    """A single normalized corpus document.

    Fields:
        id: Stable unique identifier (the dataset's `doc_id`). Used by Phase 2 to
            score retrieval against `expected_doc_ids`.
        source_type: The enterprise source the document came from (e.g. ``confluence``).
        text: The document body. Never empty.
        metadata: Raw fields not mapped to a top-level attribute (e.g. ``title``).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source_type: str
    text: str
    metadata: dict = Field(default_factory=dict)

    @field_validator("id", "source_type", "text")
    @classmethod
    def _non_empty(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return value
