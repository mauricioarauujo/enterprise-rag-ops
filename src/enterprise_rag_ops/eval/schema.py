"""Canonical judge verdict schema (FR-1/2/3, NFR-4).

`JudgeVerdict` is the single schema source-of-truth for the eval layer, exactly as
`AnswerWithSources` is for generation — with one deliberate refinement: the **three
aggregate floats are not part of the LLM-facing schema**. The LLM produces only the two
verdict lists (`per_fact`, `per_citation`); `fact_recall` / `fact_precision` /
`faithfulness_ratio` are derived afterward in pure Python (see `eval/aggregate.py`).

The LLM-facing surface is the private `_LLMJudgeVerdict` model — the two lists only.
`OpenAIJudge` feeds `_LLMJudgeVerdict.model_json_schema()` to the OpenAI `strict`
json_schema, re-validates the response through it, then spreads the validated lists into
the public `JudgeVerdict` together with the Python-derived floats. This keeps one Pydantic
model per schema (no hand-maintained parallel schema string) while ensuring the floats
never enter the LLM contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import GetJsonSchemaHandler
from pydantic_core import CoreSchema


class FactVerdict(BaseModel):
    """Per-fact answer-scoring verdict (FR-1).

    A `present` fact is asserted by the answer; `absent` is omitted; `contradicted`
    is asserted with the opposite claim. The discrete `Literal` vocabulary is enforced
    at decode time by OpenAI `strict` mode and again by Pydantic re-validation.

    The schema is closed (`extra="forbid"` → `additionalProperties: false`), the
    invariant OpenAI `strict: true` requires. `supporting_doc_id` is an additive,
    nullable field (sprint-8/phase-1): the `doc_id` of the retrieved document that
    most directly substantiates the gold fact, or `None` when none does. It is
    backward-compatible (Python default `None`, so old records and old construction
    stay valid) yet strict-mode-compatible — the `__get_pydantic_json_schema__` hook
    below forces it into `required` with the explicit `["string", "null"]` type-union
    that OpenAI `strict: true` accepts.
    """

    model_config = ConfigDict(extra="forbid")

    fact: str = Field(description="The gold answer-fact being scored.")
    verdict: Literal["present", "absent", "contradicted"] = Field(
        description="Whether the answer states this fact, omits it, or contradicts it.",
    )
    # Additive, nullable (FR-1). Python default keeps old records / old construction
    # valid (NFR-1). The strict-mode shape (required + ["string", "null"]) is forced in
    # __get_pydantic_json_schema__ below (FR-2), with the override living in the model
    # definition rather than a parallel JSON string (NFR-4).
    supporting_doc_id: str | None = Field(
        default=None,
        description=(
            "The doc_id of the retrieved document that most directly substantiates "
            "this gold fact, or null when no retrieved document covers it."
        ),
    )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> dict[str, Any]:
        schema = handler(core_schema)
        schema = handler.resolve_ref_schema(schema)
        # Strict-mode normalization for the nullable field (OpenAI strict: true):
        #   1. explicit type-union, not Pydantic's default `anyOf` form;
        #   2. present in `required` (strict rejects any property absent from required).
        props = schema.get("properties", {})
        if "supporting_doc_id" in props:
            props["supporting_doc_id"] = {
                "type": ["string", "null"],
                "description": props["supporting_doc_id"].get("description", ""),
            }
        required = schema.setdefault("required", [])
        if "supporting_doc_id" not in required:
            required.append("supporting_doc_id")
        return schema


class CitationVerdict(BaseModel):
    """Per-citation faithfulness verdict (FR-2).

    `supported` means the cited doc's text substantiates the claim it was cited for;
    `unsupported` means it does not (the spurious-citation case). Closed schema, same
    `strict`-compatibility invariant as `FactVerdict`.
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(description="The cited document identifier.")
    verdict: Literal["supported", "unsupported"] = Field(
        description="Whether this doc's text supports the claim it was cited for.",
    )


class _LLMJudgeVerdict(BaseModel):
    """LLM-facing surface of `JudgeVerdict` — the two verdict lists only (NFR-4).

    Its `model_json_schema()` feeds the OpenAI `strict` json_schema, and the returned
    JSON is re-validated through it. The three aggregate floats are deliberately
    excluded so the LLM cannot emit (wrong) floats; they are derived in Python and added
    when constructing the public `JudgeVerdict`. Module-private by convention.
    """

    model_config = ConfigDict(extra="forbid")

    per_fact: list[FactVerdict] = Field(
        description="One verdict per supplied answer-fact, in checklist order.",
    )
    per_citation: list[CitationVerdict] = Field(
        description="One verdict per cited doc_id, in the answer's citation order.",
    )


class JudgeVerdict(BaseModel):
    """A complete per-fact + per-citation judgment of one answer (FR-3).

    The two lists are the LLM-produced surface (validated via `_LLMJudgeVerdict`); the
    three floats are **derived in Python** by `eval.aggregate.aggregate` and are never
    produced by the LLM. Each float is `None` when its denominator is empty — an
    abstention with no facts/citations yields `(None, None, None)`, meaning "not
    applicable", not "perfectly faithful". Downstream averaging (Phase 6) must treat
    `None` as N/A (exclude), not coerce to 0.

    The schema is closed; the floats default to `None` so the public model is
    constructible from the two lists alone before aggregation runs.
    """

    model_config = ConfigDict(extra="forbid")

    per_fact: list[FactVerdict] = Field(
        description="One verdict per supplied answer-fact.",
    )
    per_citation: list[CitationVerdict] = Field(
        description="One verdict per cited doc_id.",
    )
    fact_recall: float | None = Field(
        default=None,
        description="|present| / |facts|; None when there are no facts.",
    )
    fact_precision: float | None = Field(
        default=None,
        description="|present| / (|present| + |contradicted|); None when that sum is 0.",
    )
    faithfulness_ratio: float | None = Field(
        default=None,
        description="|supported| / |citations|; None when there are no citations.",
    )
