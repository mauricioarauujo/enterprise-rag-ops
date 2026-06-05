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


class RouterConfig(BaseModel):
    """Cost-router configuration (sprint-7/phase-2, FR-6).

    Drives a `RouterGenerator`: answer with the cheap model by default and escalate to the
    strong model when the cheap answer is not trustworthy — confidence below threshold,
    missing confidence, or abstention (ADR-0011 §5). `threshold` defaults to the ADR-0011
    operating point (1.0). The two model ids are kept here (not derived from `ModelConfig`)
    because the router is swept as a synthetic ``"router"`` row, never as a `ModelConfig`
    (whose `system` Literal excludes ``"router"``).
    """

    cheap_model_id: str
    strong_model_id: str
    threshold: float = 1.0


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
    router: RouterConfig | None = Field(
        default=None,
        description=(
            "Optional cost-router (sprint-7/phase-2, FR-6). When set, the sweep appends a "
            "synthetic 'router' row composing the cheap + strong generators. Omitting it "
            "leaves router=None (backwards-compatible)."
        ),
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
