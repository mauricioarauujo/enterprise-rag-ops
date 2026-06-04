"""Schemas for evaluation records, call statistics, and cost calculations (FR-1, FR-2, FR-8).

Integrates with OpenTelemetry (OTEL) GenAI semantic conventions format as defined in ADR-0004.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict

logger = logging.getLogger("enterprise_rag_ops.eval.records")


class Price(BaseModel):
    """Configuration prices per 1M tokens (FR-9)."""

    input_usd_per_1m: float
    output_usd_per_1m: float


class CallStats(BaseModel):
    """Metrics captured for a single LLM execution (FR-2)."""

    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str
    system: str
    cost_usd: float | None = None
    confidence_score: float | None = None


def compute_cost_usd(stats: CallStats, price: Price | None) -> float | None:
    """Calculate the USD cost of a call from token usage and price table (FR-8, AC-10).

    Formula: cost = (input_tokens / 1e6) * price_in + (output_tokens / 1e6) * price_out
    If price is None, logs a warning and returns None.
    """
    if price is None:
        logger.warning(
            "No price entry found for model %s under system %s. cost_usd will be set to None.",
            stats.model,
            stats.system,
        )
        return None

    cost = (stats.input_tokens / 1_000_000.0) * price.input_usd_per_1m + (
        stats.output_tokens / 1_000_000.0
    ) * price.output_usd_per_1m
    return cost


class GenAiRequest(BaseModel):
    """Metadata about the generation request."""

    model: str


class GenAiOperation(BaseModel):
    """Metadata about the generation operation."""

    name: str = "chat"


class GenAiFields(BaseModel):
    """OTEL GenAI fields namespaced for the record."""

    request: GenAiRequest
    system: str
    operation: GenAiOperation = Field(default_factory=GenAiOperation)


class EvalRecord(BaseModel):
    """One record persisted per question per model (FR-1, AC-1).

    Verdict lists (per_fact, per_citation) are persisted in gold per ADR-0010.
    Only the bulky generation prompt and raw payload remain excluded (-> bronze).
    """

    question_id: str
    category: str
    run_id: str
    k: int = 10  # retrieval cut-off the run used; the report reads it (no hard-coded k)
    gen_ai: GenAiFields
    generation: CallStats
    judge: CallStats
    answer: str
    sources: list[str]
    fact_recall: float | None = None
    fact_precision: float | None = None
    faithfulness_ratio: float | None = None
    retrieval_ranked_ids: list[str] = Field(default_factory=list)
    did_abstain_retrieval: bool
    did_abstain_e2e: bool
    failure_mode: str | None = None
    per_fact: list[FactVerdict] | None = None
    per_citation: list[CitationVerdict] | None = None
