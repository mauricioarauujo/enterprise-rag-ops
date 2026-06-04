"""Configuration schemas and loaders for evaluation runs (FR-4, FR-9).

Reads and parses a YAML configuration file defining the model matrix, prices,
retrieval cutoffs, limits, and cost bounds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from enterprise_rag_ops.eval.records import Price


class ModelConfig(BaseModel):
    """Configuration for a generator model evaluated in a sweep (FR-4)."""

    model_id: str
    system: Literal["openai", "anthropic", "google"]


class RunConfig(BaseModel):
    """Configuration parameters for a multi-model sweep execution (FR-4)."""

    models: list[ModelConfig] = Field(
        description="List of generator models to evaluate.",
    )
    judge_model: str = Field(
        description="The judge model to evaluate generator answers.",
    )
    limit: int | None = Field(
        default=None,
        description="Optional limit on number of questions to run.",
    )
    k: int = Field(
        default=10,
        description="The retrieval k-cutoff.",
    )
    output_dir: str = Field(
        default="results",
        description="Output directory to write results.",
    )
    run_id: str = Field(
        default="baseline",
        description="Unique run identifier.",
    )
    prices: dict[str, Price] = Field(
        default_factory=dict,
        description="Pricing lookup table per model ID.",
    )
    cost_ceiling_usd: float | None = Field(
        default=None,
        description="Maximum allowed sweep cost in USD (FR-13).",
    )
    persist_bronze: bool = Field(
        default=False,
        description="Opt-in: write raw request+response bronze under data/raw_eval/ (ADR-0010). Default off.",
    )

    @classmethod
    def load_from_yaml(cls, path: Path | str) -> RunConfig:
        """Load and parse RunConfig from a YAML file (FR-4, AC-6)."""
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        raw_content = yaml_path.read_text()
        parsed = yaml.safe_load(raw_content)
        if parsed is None:
            parsed = {}

        return cls.model_validate(parsed)
