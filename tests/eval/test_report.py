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


def _mock_questions() -> list:
    """The gold question set matching `sample_jsonl`, one question per category."""
    from enterprise_rag_ops.eval.questions import Question

    mock_qs = [
        Question("qst_0001", "Q1", ["F1"], ["doc_1"], "basic"),
        Question("qst_0002", "Q2", [], [], "info_not_found"),
    ]
    mock_qs += [
        Question(f"qst_000{i + 3}", f"Q{i + 3}", ["F"], [f"doc_qst_000{i + 3}"], cat)
        for i, cat in enumerate(ALL_CATEGORIES[2:])
    ]
    return mock_qs


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
            # Per-fact evidence with one failed fact per gap type (AC-8/AC-10 50% path):
            # absent + no supporting doc -> retrieval_gap; contradicted + retrieved
            # supporting doc ("doc_1" is in retrieval_ranked_ids) -> generation_gap.
            "per_fact": [
                {"fact": "F1", "verdict": "absent", "supporting_doc_id": None},
                {"fact": "F2", "verdict": "contradicted", "supporting_doc_id": "doc_1"},
            ],
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

    # Give the `conditional` filler per-fact evidence with ZERO failed facts (all present)
    # so its root-cause cell renders 0.0% (AC-10), distinct from the per_fact=None fillers
    # (negation/multi_hop/...) which render N/A.
    for r in records:
        if r["category"] == "conditional":
            r["per_fact"] = [
                {
                    "fact": "C1",
                    "verdict": "present",
                    "supporting_doc_id": r["retrieval_ranked_ids"][0],
                },
            ]

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


def test_root_cause_key_in_report_data(sample_jsonl, monkeypatch):
    """AC-8/SC-2: generate_report_data has a top-level 'root_cause' key whose 'basic'
    category distinguishes retrieval-gap from generation-gap counts among failed facts."""
    from enterprise_rag_ops.eval import report
    from enterprise_rag_ops.eval.report import generate_report_data

    monkeypatch.setattr(report, "load_questions", _mock_questions)

    data = generate_report_data(sample_jsonl)

    assert "root_cause" in data
    basic = next(row for row in data["root_cause"] if row["category"] == "basic")
    metrics = basic["metrics"]["model-a"]
    # F1 (absent, no supporting doc) -> retrieval_gap; F2 (contradicted, doc_1 retrieved)
    # -> generation_gap. Split is 1/1 -> 50.0%.
    assert metrics["retrieval_gap"] == 1
    assert metrics["generation_gap"] == 1
    assert metrics["has_evidence"] is True
    assert metrics["retrieval_gap_pct"] == 0.5


def test_root_cause_section_rendered_md_and_html(sample_jsonl, tmp_path, monkeypatch):
    """AC-9/SC-2: both renderers emit a dedicated Root-Cause Attribution block; the
    existing 7-column per-category table is unchanged in column structure (NFR-4)."""
    from enterprise_rag_ops.eval import report

    monkeypatch.setattr(report, "load_questions", _mock_questions)

    html_path, md_path = render_report(sample_jsonl, tmp_path)
    md_content = md_path.read_text(encoding="utf-8")
    html_content = html_path.read_text(encoding="utf-8")

    # The dedicated section/block exists in both renderings.
    assert "## Root-Cause Attribution" in md_content
    assert "Root-Cause Attribution" in html_content

    # NFR-4: the existing 7-column category table header is byte-for-byte unchanged.
    assert (
        "| Category | Model | Retrieval Recall@10 | Retrieval nDCG@10 "
        "| Fact Recall | Fact Precision | Faithfulness |"
    ) in md_content
    # The distinctive category-table <th> columns are still present (not moved/renamed).
    assert "<th>Retrieval Recall@10</th>" in html_content
    assert "<th>Retrieval nDCG@10</th>" in html_content


def test_root_cause_na_vs_zero_pct(sample_jsonl, tmp_path, monkeypatch):
    """AC-10/Decision D: a category with no per-fact evidence renders N/A; a category
    with per-fact evidence and zero failed facts renders 0.0% — asserted distinctly."""
    from enterprise_rag_ops.eval import report

    monkeypatch.setattr(report, "load_questions", _mock_questions)

    _html_path, md_path = render_report(sample_jsonl, tmp_path)
    md_content = md_path.read_text(encoding="utf-8")

    # Isolate the Root-Cause Attribution section and index rows by category.
    rc_section = md_content.split("## Root-Cause Attribution", 1)[1]
    rc_rows = {}
    for line in rc_section.splitlines():
        if line.startswith("| **"):
            rc_rows[line.split("**")[1]] = line

    # `conditional` has per-fact evidence with zero failed facts -> 0.0% (not N/A).
    assert "0.0%" in rc_rows["conditional"]
    assert "N/A" not in rc_rows["conditional"]
    # `negation` (a per_fact=None filler) has no per-fact evidence -> N/A (not 0.0%).
    assert "N/A" in rc_rows["negation"]
    assert "0.0%" not in rc_rows["negation"]
