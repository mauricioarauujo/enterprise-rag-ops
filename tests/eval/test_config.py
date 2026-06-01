"""Unit tests for RunConfig configuration schemas (AC-6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.eval.config import RunConfig


def test_run_config_parses_baseline_yaml():
    """AC-6: RunConfig parses the baseline.yaml correctly."""
    baseline_path = Path(__file__).parents[2] / "configs" / "baseline.yaml"
    assert baseline_path.exists()

    config = RunConfig.load_from_yaml(baseline_path)
    assert len(config.models) == 3
    assert config.models[0].model_id == "gpt-5-nano-2025-08-07"
    assert config.models[0].system == "openai"
    assert config.models[1].model_id == "claude-haiku-4-5-20251001"
    assert config.models[1].system == "anthropic"
    assert config.models[2].model_id == "gemini-2.5-flash-lite"
    assert config.models[2].system == "google"

    assert config.judge_model == "gpt-5-nano-2025-08-07"
    assert config.limit is None
    assert config.k == 10
    assert config.output_dir == "results"
    assert config.run_id == "baseline"
    assert config.cost_ceiling_usd == 5.0

    # Check pricing maps
    assert "gpt-5-nano-2025-08-07" in config.prices
    assert config.prices["gpt-5-nano-2025-08-07"].input_usd_per_1m == 0.05
    assert config.prices["gpt-5-nano-2025-08-07"].output_usd_per_1m == 0.40

    assert "gemini-2.5-flash-lite" in config.prices
    assert config.prices["gemini-2.5-flash-lite"].input_usd_per_1m == 0.10
    assert config.prices["gemini-2.5-flash-lite"].output_usd_per_1m == 0.40


def test_run_config_validation_errors(tmp_path):
    """AC-6: Malformed YAML content raises a typed ValidationError."""
    # Invalid model system type
    bad_yaml = """
models:
  - model_id: "gpt-5"
    system: "unknown-system"
judge_model: "gpt-5"
"""
    yaml_file = tmp_path / "bad_config.yaml"
    yaml_file.write_text(bad_yaml)

    with pytest.raises(ValidationError):
        RunConfig.load_from_yaml(yaml_file)


def test_run_config_missing_file():
    """RunConfig raises FileNotFoundError for missing path."""
    with pytest.raises(FileNotFoundError):
        RunConfig.load_from_yaml("nonexistent_file.yaml")


def test_model_config_system_validation():
    """AC-7: ModelConfig(system="google", ...) validates; ModelConfig(system="gemini", ...) raises ValidationError."""
    from enterprise_rag_ops.eval.config import ModelConfig

    # Valid google system
    cfg = ModelConfig(model_id="gemini-2.5-flash-lite", system="google")
    assert cfg.system == "google"

    # Invalid "gemini" system
    with pytest.raises(ValidationError):
        ModelConfig(model_id="gemini-2.5-flash-lite", system="gemini")
