"""Unit tests for report rendering and metric calculations (AC-9, NFR-2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise_rag_ops.eval.report import render_report


@pytest.fixture
def sample_jsonl(tmp_path) -> Path:
    """Fixture returning a path to a JSONL file with diverse metrics, including None values (NFR-2)."""
    records = [
        # Model A, Question 1
        {
            "question_id": "qst_0001",
            "category": "basic",
            "run_id": "test_run",
            "gen_ai": {"request": {"model": "model-a"}, "system": "openai"},
            "generation": {
                "input_tokens": 100,
                "output_tokens": 50,
                "latency_s": 1.5,
                "model": "model-a",
                "system": "openai",
                "cost_usd": 0.0001,
            },
            "judge": {
                "input_tokens": 200,
                "output_tokens": 20,
                "latency_s": 0.8,
                "model": "gpt-5-nano-test",
                "system": "openai",
                "cost_usd": 0.00005,
            },
            "answer": "Answer 1",
            "sources": ["doc_1"],
            "fact_recall": 1.0,
            "fact_precision": 0.8,
            "faithfulness_ratio": None,  # None to test N/A propagation (NFR-2)
            "retrieval_ranked_ids": ["doc_1"],
            "did_abstain_retrieval": False,
            "did_abstain_e2e": False,
        },
        # Model A, Question 2
        {
            "question_id": "qst_0002",
            "category": "info_not_found",
            "run_id": "test_run",
            "gen_ai": {"request": {"model": "model-a"}, "system": "openai"},
            "generation": {
                "input_tokens": 80,
                "output_tokens": 10,
                "latency_s": 1.0,
                "model": "model-a",
                "system": "openai",
                "cost_usd": 0.00008,
            },
            "judge": {
                "input_tokens": 150,
                "output_tokens": 5,
                "latency_s": 0.5,
                "model": "gpt-5-nano-test",
                "system": "openai",
                "cost_usd": 0.00003,
            },
            "answer": "I don't have enough information to answer this question.",
            "sources": [],
            "fact_recall": None,
            "fact_precision": None,
            "faithfulness_ratio": 1.0,
            "retrieval_ranked_ids": [],
            "did_abstain_retrieval": True,
            "did_abstain_e2e": True,
        },
    ]

    jsonl_file = tmp_path / "test_run.jsonl"
    with open(jsonl_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return jsonl_file


def test_report_renders_html_and_markdown(sample_jsonl, tmp_path, monkeypatch):
    """AC-9: Report aggregates data correctly, handles None as 'N/A' and writes HTML + MD files."""
    # Mock load_questions to return matching mocked questions
    from enterprise_rag_ops.eval import report
    from enterprise_rag_ops.eval.questions import Question

    mock_qs = [
        Question("qst_0001", "Q1", ["F1"], ["doc_1"], "basic"),
        Question("qst_0002", "Q2", [], [], "info_not_found"),
    ]
    monkeypatch.setattr(report, "load_questions", lambda: mock_qs)

    html_path, md_path = render_report(sample_jsonl, tmp_path)

    assert html_path.exists()
    assert md_path.exists()

    html_content = html_path.read_text(encoding="utf-8")
    md_content = md_path.read_text(encoding="utf-8")

    # Assert model name and headings presence
    assert "model-a" in html_content
    assert "model-a" in md_content
    assert "Cost & Latency" in md_content
    assert "Detailed Breakdown Per Category" in md_content

    # Assert N/A cells are rendered for None values (NFR-2)
    assert "N/A" in html_content
    assert "N/A" in md_content

    # Check Markdown formatting (contains expected cells)
    assert "basic" in md_content
    assert "info_not_found" in md_content
    assert "$0.0003" in md_content  # Total cost (0.0001 + 0.00005 + 0.00008 + 0.00003)
