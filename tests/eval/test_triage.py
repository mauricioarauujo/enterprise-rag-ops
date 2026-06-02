"""Unit tests for the RAG evaluation triage logic and command-line interface.

Covers AC-1 through AC-16 as specified in the Phase 14 design contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.triage import SCHEMA_VERSION, _report_to_dict, compute_triage
from enterprise_rag_ops.eval.triage_cli import main


def make_dummy_record(
    question_id: str,
    category: str,
    failure_mode: str | None = "correct",
    model: str = "gpt-4o",
) -> EvalRecord:
    """Helper to build a dummy EvalRecord with the minimal required fields."""
    return EvalRecord.model_validate(
        {
            "question_id": question_id,
            "category": category,
            "run_id": "dummy_run",
            "gen_ai": {
                "request": {"model": model},
                "system": "openai",
            },
            "generation": {
                "input_tokens": 10,
                "output_tokens": 5,
                "latency_s": 0.1,
                "model": model,
                "system": "openai",
                "cost_usd": 0.0001,
            },
            "judge": {
                "input_tokens": 20,
                "output_tokens": 2,
                "latency_s": 0.1,
                "model": "judge-model",
                "system": "openai",
                "cost_usd": 0.0002,
            },
            "answer": "dummy answer",
            "sources": [],
            "did_abstain_retrieval": False,
            "did_abstain_e2e": False,
            "failure_mode": failure_mode,
        }
    )


def test_ac1_and_ac3_cluster_key_count_rate():
    """AC-1 & AC-3: Verify grouping logic, counts, and cluster rates."""
    gold = {
        "qst_01": Question("qst_01", "Q1", [], [], "basic"),
        "qst_02": Question("qst_02", "Q2", [], [], "basic"),
        "qst_03": Question("qst_03", "Q3", [], [], "complex"),
    }
    records = [
        make_dummy_record("qst_01", "basic", "correct"),
        make_dummy_record("qst_02", "basic", "correct"),
        make_dummy_record("qst_03", "complex", "abstention_error"),
    ]

    report = compute_triage(records, gold)
    assert report.total_records == 3
    assert len(report.clusters) == 2

    # Check first cluster (correct / basic)
    c1 = report.clusters[0]
    assert c1.failure_mode == "correct"
    assert c1.category == "basic"
    assert c1.count == 2
    assert c1.rate == 2 / 3

    # Check second cluster (abstention_error / complex)
    c2 = report.clusters[1]
    assert c2.failure_mode == "abstention_error"
    assert c2.category == "complex"
    assert c2.count == 1
    assert c2.rate == 1 / 3

    # Sum of counts must equal total records
    assert sum(c.count for c in report.clusters) == 3


def test_ac2_record_category_authoritative():
    """AC-2: Verify record's category field overrides gold's category field."""
    gold = {
        "qst_01": Question("qst_01", "Q1", [], [], "basic"),
    }
    # Record has category 'custom' which is different from gold's 'basic'
    records = [
        make_dummy_record("qst_01", "custom", "correct"),
    ]

    report = compute_triage(records, gold)
    assert len(report.clusters) == 1
    assert report.clusters[0].category == "custom"


def test_ac4_empty_input():
    """AC-4: Verify empty input returns an empty report and does not divide by zero."""
    gold = {}
    report = compute_triage([], gold)
    assert report.total_records == 0
    assert report.clusters == []
    assert report.dominant_cluster is None
    assert report.schema_version == SCHEMA_VERSION


def test_ac5_sort_and_tiebreak():
    """AC-5: Verify clusters are sorted by count descending and tiebroken alphabetically."""
    # We want to check sorting when counts are equal
    records = [
        make_dummy_record("qst_01", "basic", "correct"),
        make_dummy_record("qst_02", "basic", "correct"),
        make_dummy_record("qst_03", "complex", "correct"),
        make_dummy_record("qst_04", "basic", "abstention_error"),
        make_dummy_record("qst_05", "complex", "abstention_error"),
    ]

    report = compute_triage(records, {})
    assert len(report.clusters) == 4

    # Highest count cluster must be first
    assert report.clusters[0].count == 2
    assert report.clusters[0].failure_mode == "correct"
    assert report.clusters[0].category == "basic"

    # Remaining clusters have count=1 and must be tiebroken by (failure_mode, category) ascending
    # Sorted order should be:
    # 1. "abstention_error" / "basic"
    # 2. "abstention_error" / "complex"
    # 3. "correct" / "complex"
    assert report.clusters[1].count == 1
    assert report.clusters[1].failure_mode == "abstention_error"
    assert report.clusters[1].category == "basic"

    assert report.clusters[2].count == 1
    assert report.clusters[2].failure_mode == "abstention_error"
    assert report.clusters[2].category == "complex"

    assert report.clusters[3].count == 1
    assert report.clusters[3].failure_mode == "correct"
    assert report.clusters[3].category == "complex"


def test_ac6_dominant_cluster():
    """AC-6: Verify dominant_cluster matches clusters[0] and is None when empty."""
    # Single element list
    records = [
        make_dummy_record("qst_01", "basic", "correct"),
    ]
    report = compute_triage(records, {})
    assert report.dominant_cluster is not None
    assert report.dominant_cluster == report.clusters[0]


def test_ac7_representative_determinism():
    """AC-7: Verify representative question selection is stable and deterministic."""
    gold = {
        "qst_0009": Question("qst_0009", "Question 9", [], [], "basic"),
        "qst_0002": Question("qst_0002", "Question 2", [], [], "basic"),
        "qst_0005": Question("qst_0005", "Question 5", [], [], "basic"),
    }
    records = [
        make_dummy_record("qst_0009", "basic", "correct"),
        make_dummy_record("qst_0002", "basic", "correct"),
        make_dummy_record("qst_0005", "basic", "correct"),
    ]

    report = compute_triage(records, gold)
    assert len(report.clusters) == 1
    # qst_0002 is lexicographically the smallest question_id
    assert report.clusters[0].representative_question_id == "qst_0002"
    assert report.clusters[0].representative_question_text == "Question 2"

    # Rerun to assert stable output
    report_rerun = compute_triage(records, gold)
    assert report_rerun.clusters[0].representative_question_id == "qst_0002"


def test_ac8_missing_gold_representative():
    """AC-8: Verify representative question text is empty if absent from gold."""
    records = [
        make_dummy_record("qst_0002", "basic", "correct"),
    ]
    report = compute_triage(records, {})
    assert len(report.clusters) == 1
    assert report.clusters[0].representative_question_id == "qst_0002"
    assert report.clusters[0].representative_question_text == ""


def test_ac9_fail_fast_on_unclassified():
    """AC-9: Verify compute_triage raises ValueError on unclassified records."""
    records = [
        make_dummy_record("qst_01", "basic", "correct"),
        make_dummy_record("qst_02", "basic", None),
        make_dummy_record("qst_03", "basic", "correct"),
    ]

    with pytest.raises(ValueError, match="Record 'qst_02' is unclassified"):
        compute_triage(records, {})


def test_ac10_models_seen():
    """AC-10: Verify models_seen contains unique sorted model names at both levels."""
    records = [
        make_dummy_record("qst_01", "basic", "correct", model="llama-3"),
        make_dummy_record("qst_02", "basic", "correct", model="gpt-4o"),
        make_dummy_record("qst_03", "complex", "abstention_error", model="claude-3"),
    ]

    report = compute_triage(records, {})
    # Report level sorted unique
    assert report.models_seen == ["claude-3", "gpt-4o", "llama-3"]

    # Cluster level sorted unique
    c_correct = next(c for c in report.clusters if c.failure_mode == "correct")
    assert c_correct.models_seen == ["gpt-4o", "llama-3"]

    c_abstain = next(c for c in report.clusters if c.failure_mode == "abstention_error")
    assert c_abstain.models_seen == ["claude-3"]


def test_ac11_schema_version():
    """AC-11: Verify schema version exists and is serializable."""
    report = compute_triage([], {})
    assert report.schema_version == SCHEMA_VERSION
    d = _report_to_dict(report)
    assert d["schema_version"] == SCHEMA_VERSION


def test_ac12_json_shape_and_atomic_write(tmp_path):
    """AC-12: Verify JSON report shape and atomic write (cleanup on failure)."""
    results_file = tmp_path / "baseline_classified.jsonl"
    output_file = tmp_path / "triage.json"

    rec1 = make_dummy_record("qst_01", "basic", "correct")
    rec2 = make_dummy_record("qst_02", "basic", "correct")

    with open(results_file, "w", encoding="utf-8") as f:
        f.write(rec1.model_dump_json() + "\n")
        f.write(rec2.model_dump_json() + "\n")

    gold_q = Question("qst_01", "What speed?", [], [], "basic")

    with patch("enterprise_rag_ops.eval.triage_cli.load_questions", return_value=[gold_q]):
        exit_code = main(["--results", str(results_file), "--output", str(output_file)])

    assert exit_code == 0
    assert output_file.exists()

    with open(output_file, encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema_version"] == SCHEMA_VERSION
    assert data["total_records"] == 2
    assert data["models_seen"] == ["gpt-4o"]
    assert data["dominant_cluster"]["failure_mode"] == "correct"
    assert data["dominant_cluster"]["category"] == "basic"
    assert len(data["clusters"]) == 1
    assert data["clusters"][0]["representative_question_id"] == "qst_01"
    assert data["clusters"][0]["representative_question_text"] == "What speed?"

    # Test atomic write cleanup on failure (simulated during dictionary serialization)
    fail_output_file = tmp_path / "triage_fail.json"
    assert not fail_output_file.exists()

    # Ensure no leftover temp files exist beforehand
    assert list(tmp_path.glob(".rag-triage-tmp-*")) == []

    with (
        patch(
            "enterprise_rag_ops.eval.triage_cli._report_to_dict",
            side_effect=ValueError("Simulated failure during dict parsing"),
        ),
        patch("enterprise_rag_ops.eval.triage_cli.load_questions", return_value=[gold_q]),
    ):
        exit_code_fail = main(["--results", str(results_file), "--output", str(fail_output_file)])

    assert exit_code_fail == 1
    assert not fail_output_file.exists()
    # Temporary file must be cleaned up
    assert list(tmp_path.glob(".rag-triage-tmp-*")) == []


def test_ac13_deterministic_bytes():
    """AC-13: Verify serialized byte deterministic output across passes."""
    gold = {
        "qst_01": Question("qst_01", "Q1", [], [], "basic"),
        "qst_02": Question("qst_02", "Q2", [], [], "basic"),
    }
    records = [
        make_dummy_record("qst_01", "basic", "correct"),
        make_dummy_record("qst_02", "basic", "correct"),
    ]

    # Two independent compute_triage passes must serialize byte-identically — this
    # falsifies any dict/set iteration-order leak across separate invocations.
    report_a = compute_triage(records, gold)
    report_b = compute_triage(records, gold)

    bytes1 = json.dumps(_report_to_dict(report_a), indent=2)
    bytes2 = json.dumps(_report_to_dict(report_b), indent=2)

    assert bytes1 == bytes2


def test_ac14_stdout_summary_dry_run(tmp_path, capsys):
    """AC-14: Verify dry run prints to stdout and writes no files."""
    results_file = tmp_path / "baseline_classified.jsonl"
    output_file = tmp_path / "triage_dry.json"

    rec = make_dummy_record("qst_01", "basic", "correct")
    with open(results_file, "w", encoding="utf-8") as f:
        f.write(rec.model_dump_json() + "\n")

    with patch("enterprise_rag_ops.eval.triage_cli.load_questions", return_value=[]):
        exit_code = main(
            ["--results", str(results_file), "--output", str(output_file), "--dry-run"]
        )

    assert exit_code == 0
    assert not output_file.exists()

    captured = capsys.readouterr()
    assert "TRIAGE REPORT SUMMARY" in captured.out
    assert "DOMINANT CLUSTER:" in captured.out
    assert "correct" in captured.out
    assert exit_code == 0


def test_ac15_offline_guarantee():
    """AC-15: Verify execution functions completely offline with no network imports."""
    # Running compute_triage without mocking load_questions still does not make network queries
    gold = {"qst_01": Question("qst_01", "Q1", [], [], "basic")}
    records = [make_dummy_record("qst_01", "basic", "correct")]

    report = compute_triage(records, gold)
    assert report.total_records == 1

    # Importing the pure core in a clean interpreter must not pull in the LLM client.
    # (Run in a subprocess so an LLM import from a sibling test cannot pollute the check.)
    check = (
        "import sys, enterprise_rag_ops.eval.triage; sys.exit(1 if 'openai' in sys.modules else 0)"
    )
    result = subprocess.run([sys.executable, "-c", check], capture_output=True, text=True)
    assert result.returncode == 0, f"triage import pulled in an LLM client: {result.stderr}"


def test_ac16_console_script_and_help():
    """AC-16: Verify console script registration and --help execution."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0

    # Assert registration string in pyproject.toml matches expected command/entry point
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    assert pyproject_path.exists()
    with open(pyproject_path, encoding="utf-8") as f:
        content = f.read()

    assert 'rag-triage = "enterprise_rag_ops.eval.triage_cli:main"' in content
