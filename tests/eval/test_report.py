"""Unit tests for report rendering and metric calculations (AC-9, NFR-2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise_rag_ops.eval.report import render_report

# The full benchmark question taxonomy — AC-9 requires the breakdown to list all 10.
ALL_CATEGORIES = [
    "basic",
    "info_not_found",
    "conditional",
    "multi_hop",
    "negation",
    "numeric",
    "temporal",
    "comparison",
    "aggregation",
    "ambiguous",
]


def _filler_record(qid: str, category: str) -> dict:
    """A minimal zero-cost record for a category, used to pad the fixture to 10 categories."""
    return {
        "question_id": qid,
        "category": category,
        "run_id": "test_run",
        "k": 10,
        "gen_ai": {"request": {"model": "model-a"}, "system": "openai"},
        "generation": {
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_s": 0.0,
            "model": "model-a",
            "system": "openai",
            "cost_usd": 0.0,
        },
        "judge": {
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_s": 0.0,
            "model": "gpt-5-nano-test",
            "system": "openai",
            "cost_usd": 0.0,
        },
        "answer": f"Answer for {qid}",
        "sources": [f"doc_{qid}"],
        "fact_recall": 0.5,
        "fact_precision": 0.5,
        "faithfulness_ratio": 0.5,
        "retrieval_ranked_ids": [f"doc_{qid}"],
        "did_abstain_retrieval": False,
        "did_abstain_e2e": False,
    }


@pytest.fixture
def sample_jsonl(tmp_path) -> Path:
    """A JSONL fixture covering all 10 categories (AC-9), with None metrics for N/A (NFR-2)."""
    records = [
        # Model A, Question 1 — full metrics; faithfulness None to exercise N/A.
        {
            "question_id": "qst_0001",
            "category": "basic",
            "run_id": "test_run",
            "k": 10,
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
        # Model A, Question 2 — abstention; None recall/precision.
        {
            "question_id": "qst_0002",
            "category": "info_not_found",
            "run_id": "test_run",
            "k": 10,
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
    # Pad to the full 10-category taxonomy (zero-cost fillers keep the cost roll-up stable).
    records += [_filler_record(f"qst_000{i + 3}", cat) for i, cat in enumerate(ALL_CATEGORIES[2:])]

    jsonl_file = tmp_path / "test_run.jsonl"
    with open(jsonl_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return jsonl_file


def test_report_renders_html_and_markdown(sample_jsonl, tmp_path, monkeypatch):
    """AC-9: Report aggregates correctly, lists all 10 categories, renders None as 'N/A'."""
    # Mock load_questions to return one matching question per category.
    from enterprise_rag_ops.eval import report
    from enterprise_rag_ops.eval.questions import Question

    mock_qs = [
        Question("qst_0001", "Q1", ["F1"], ["doc_1"], "basic"),
        Question("qst_0002", "Q2", [], [], "info_not_found"),
    ]
    mock_qs += [
        Question(f"qst_000{i + 3}", f"Q{i + 3}", ["F"], [f"doc_qst_000{i + 3}"], cat)
        for i, cat in enumerate(ALL_CATEGORIES[2:])
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

    # AC-9: every one of the 10 categories appears in both renderings.
    for cat in ALL_CATEGORIES:
        assert cat in md_content, f"missing category {cat} in Markdown"
        assert cat in html_content, f"missing category {cat} in HTML"

    # Total cost = 0.0001 + 0.00005 + 0.00008 + 0.00003 (fillers are zero-cost) → $0.0003.
    assert "$0.0003" in md_content
