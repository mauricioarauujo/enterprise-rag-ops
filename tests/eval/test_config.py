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


# --- sprint-7/phase-2: RouterConfig + RunConfig.router ----------------------


def test_router_config_threshold_defaults_to_one():
    """AC-8: RouterConfig validates {cheap,strong,threshold}; threshold defaults to 1.0."""
    from enterprise_rag_ops.eval.config import RouterConfig

    cfg = RouterConfig(cheap_model_id="cheap", strong_model_id="strong")
    assert cfg.cheap_model_id == "cheap"
    assert cfg.strong_model_id == "strong"
    assert cfg.threshold == 1.0

    explicit = RouterConfig(cheap_model_id="c", strong_model_id="s", threshold=0.5)
    assert explicit.threshold == 0.5


def test_run_config_without_router_block_is_none():
    """AC-8: a YAML without a top-level `router:` leaves RunConfig.router is None (backwards-compat)."""
    baseline_path = Path(__file__).parents[2] / "configs" / "baseline.yaml"
    config = RunConfig.load_from_yaml(baseline_path)
    assert config.router is None


def test_run_config_parses_router_yaml():
    """AC-12: configs/router.yaml parses; router knobs, ceiling, limit, and prices are right."""
    router_path = Path(__file__).parents[2] / "configs" / "router.yaml"
    assert router_path.exists()

    config = RunConfig.load_from_yaml(router_path)
    assert config.router is not None
    assert config.router.cheap_model_id == "gemini-2.5-flash-lite"
    assert config.router.strong_model_id == "claude-haiku-4-5-20251001"
    assert config.router.threshold == 1.0
    assert config.cost_ceiling_usd == 5.0
    assert config.limit == 20
    # Price table carries cheap, strong, and judge entries — all needed for cost accounting.
    assert "gemini-2.5-flash-lite" in config.prices
    assert "claude-haiku-4-5-20251001" in config.prices
    assert "gpt-5-nano-2025-08-07" in config.prices


def test_run_config_parses_router_dev_yaml():
    """AC-12 (Should): configs/router.dev.yaml parses for rapid iteration (5 q, no ceiling)."""
    dev_path = Path(__file__).parents[2] / "configs" / "router.dev.yaml"
    assert dev_path.exists()

    config = RunConfig.load_from_yaml(dev_path)
    assert config.router is not None
    assert config.router.threshold == 1.0
    assert config.limit == 5
    assert config.cost_ceiling_usd is None
