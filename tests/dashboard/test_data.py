"""Offline unit tests for dashboard/data.py against committed results/baseline.jsonl."""

import sys
from pathlib import Path

from enterprise_rag_ops.dashboard.data import (
    category_failure_distribution,
    cost_rows,
    failure_mode_distribution,
    format_cost,
    load_run_records,
    phoenix_trace_url,
    summary_rows,
)
from enterprise_rag_ops.eval.failure_taxonomy import FailureMode
from enterprise_rag_ops.eval.report import generate_report_data

BASELINE_PATH = Path("results/baseline.jsonl")


def test_data_module_no_streamlit():
    """Verify that importing dashboard.data triggers no streamlit import (AC-6, FR-6)."""
    import subprocess

    cmd = [
        sys.executable,
        "-c",
        "import sys; import enterprise_rag_ops.dashboard.data; assert 'streamlit' not in sys.modules",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Importing dashboard.data imported streamlit: {res.stderr}"


def test_summary_rows_equal_report():
    """Assert that summary_rows is identical to generate_report_data(...)[summary] (AC-2)."""
    assert BASELINE_PATH.is_file(), "baseline.jsonl must exist for testing"
    expected = generate_report_data(BASELINE_PATH)["summary"]
    actual = summary_rows(BASELINE_PATH)
    assert actual == expected


def test_failure_mode_distribution_totals():
    """Verify failure mode distribution zero-filling and totals (AC-3)."""
    assert BASELINE_PATH.is_file()
    records = load_run_records([BASELINE_PATH])
    dist = failure_mode_distribution(records)

    # Get models in records that have at least one classified failure mode
    classified_by_model = {}
    for r in records:
        if r.failure_mode is not None:
            model = r.gen_ai.request.model
            classified_by_model[model] = classified_by_model.get(model, 0) + 1

    for model, counts in dist.items():
        # Assert covers all 5 FailureMode labels
        assert len(counts) == 5
        for fm in FailureMode:
            assert fm.value in counts

        # Assert total per model equals the record count for that model with non-None failure_mode
        total_counts = sum(counts.values())
        assert total_counts == classified_by_model[model]


def test_cost_rows_equal_report():
    """Verify cost_rows equals generate_report_data costs, and format_cost behavior (AC-4)."""
    assert BASELINE_PATH.is_file()
    expected = generate_report_data(BASELINE_PATH)["costs"]
    actual = cost_rows(BASELINE_PATH)
    assert actual == expected

    # format_cost asserts
    assert format_cost(None) == "N/A"
    assert format_cost(12.34567) == "$12.3457"
    assert format_cost(0.0) == "$0.0000"


def test_single_model_structure(tmp_path):
    """Verify that single-model records produce valid single-model structures (AC-5)."""
    assert BASELINE_PATH.is_file()
    all_records = load_run_records([BASELINE_PATH])

    # Extract all unique models
    models = {r.gen_ai.request.model for r in all_records}
    assert len(models) >= 1

    target_model = next(iter(models))
    single_model_records = [r for r in all_records if r.gen_ai.request.model == target_model]

    # Test failure_mode_distribution returns a valid one-key dict
    dist = failure_mode_distribution(single_model_records)
    # Note that it might return no keys if all failure modes are None,
    # but if there's at least one non-None failure mode, it must have only that one model key.
    assert len(dist) <= 1
    if dist:
        assert list(dist.keys()) == [target_model]
        assert len(dist[target_model]) == 5

    # Write single model records to a temp file and test summary_rows
    temp_jsonl = tmp_path / "single_model.jsonl"
    with open(temp_jsonl, "w", encoding="utf-8") as f:
        for r in single_model_records:
            f.write(r.model_dump_json() + "\n")

    summary = summary_rows(temp_jsonl)
    assert len(summary) == 1
    assert summary[0]["model"] == target_model


def test_category_failure_distribution():
    """Verify category_failure_distribution behaves as expected (AC-8)."""
    assert BASELINE_PATH.is_file()
    records = load_run_records([BASELINE_PATH])
    dist = category_failure_distribution(records)

    # All unique categories with non-None failure modes
    expected_categories = {r.category for r in records if r.failure_mode is not None}

    assert set(dist.keys()) == expected_categories
    for _cat, counts in dist.items():
        assert len(counts) == 5
        for fm in FailureMode:
            assert fm.value in counts


def test_load_run_records_union(tmp_path):
    """Verify loading and concatenating multiple files works, preserving order (AC-9)."""
    assert BASELINE_PATH.is_file()
    all_records = load_run_records([BASELINE_PATH])
    assert len(all_records) > 0

    # Split records into two parts
    mid = len(all_records) // 2
    part1 = all_records[:mid]
    part2 = all_records[mid:]

    file1 = tmp_path / "run1.jsonl"
    file2 = tmp_path / "run2.jsonl"

    with open(file1, "w", encoding="utf-8") as f:
        for r in part1:
            f.write(r.model_dump_json() + "\n")

    with open(file2, "w", encoding="utf-8") as f:
        for r in part2:
            f.write(r.model_dump_json() + "\n")

    # Double check loading single run
    loaded_1 = load_run_records([file1])
    assert len(loaded_1) == len(part1)
    assert [r.question_id for r in loaded_1] == [r.question_id for r in part1]

    # Test loading union
    union_records = load_run_records([file1, file2])
    assert len(union_records) == len(all_records)
    assert [r.question_id for r in union_records] == [r.question_id for r in all_records]


def test_phoenix_url_off(monkeypatch):
    """Verify phoenix trace url returns None when env var is unset, and valid URL when set (AC-10)."""
    # Unset
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    assert phoenix_trace_url("qst_0001") is None

    # Set bare domain
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    url = phoenix_trace_url("qst_0001", project="my-test-proj")
    assert url == "http://localhost:6006/projects/my-test-proj"

    # Set endpoint path
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://my-phoenix:8080/v1/traces")
    url2 = phoenix_trace_url("qst_0001", project="another-proj")
    assert url2 == "http://my-phoenix:8080/projects/another-proj"
