"""Unit tests for the rag-eval command-line interface (AC-8, AC-11, AC-18)."""

from __future__ import annotations

import json

from enterprise_rag_ops.eval.cli import main
from enterprise_rag_ops.generation.stub_generator import StubGenerator
from enterprise_rag_ops.retrieval.schema import Chunk

# --- Mock Retriever ---------------------------------------------------------


class MockRetriever:
    def __init__(self, chunk_hits=None) -> None:
        self.chunk_hits = chunk_hits or [("doc_1::0", "doc_1", 0.9)]
        self._vector_store = FakeStore()

    def retrieve_chunks(self, query: str, top_k: int = 10) -> list[tuple[str, str, float]]:
        return self.chunk_hits


class FakeStore:
    def fetch_chunks_by_chunk_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        return [
            Chunk(chunk_id=cid, doc_id=cid.split("::")[0], text="mock body") for cid in chunk_ids
        ]


# --- Tests ------------------------------------------------------------------


def test_cli_run_fail_fast_missing_index(monkeypatch, tmp_path):
    """AC-11: CLI run prints guarded error message to stderr and returns code 1 when index is missing."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    # Point index to nonexistent temp dirs
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    # Create a valid config file
    config_yaml = """
models:
  - model_id: "model-test"
    system: "openai"
judge_model: "gpt-5-nano-test"
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_yaml)

    # Capture stderr
    import sys
    from io import StringIO

    stderr_buf = StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    code = main(["run", "--config", str(config_file)])
    assert code == 1
    assert (
        "Gold-aware index artifacts are missing. Please run `make build-index-gold` first."
        in stderr_buf.getvalue()
    )


def test_cli_run_with_stubs(monkeypatch, tmp_path):
    """AC-8: Running the CLI run command with stub generators/judge produces JSONL, HTML, and MD reports."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Gold-aware sidecar: contains doc_1, matching the patched question's gold doc (FR-10).
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    from enterprise_rag_ops.retrieval import pipeline

    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    # Mock factories inside runner
    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.stub_judge import StubJudge

    monkeypatch.setattr(runner, "_GENERATOR_FACTORY", {"openai": StubGenerator})
    monkeypatch.setattr(runner, "OpenAIJudge", StubJudge)

    # Mock questions
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [
            Question("qst_0001", "What is capital of France?", ["Paris"], ["doc_1"], "basic")
        ],
    )

    # Mock load_questions in report module as well
    from enterprise_rag_ops.eval import report

    monkeypatch.setattr(
        report,
        "load_questions",
        lambda: [Question("qst_0001", "What is capital of France?", ["Paris"], ["doc_1"], "basic")],
    )

    # Write a test config file
    config_yaml = f"""
models:
  - model_id: "model-test"
    system: "openai"
judge_model: "gpt-5-nano-test"
output_dir: "{tmp_path}"
run_id: "cli_test"
prices:
  model-test:
    input_usd_per_1m: 0.1
    output_usd_per_1m: 0.2
  gpt-5-nano-test:
    input_usd_per_1m: 0.05
    output_usd_per_1m: 0.1
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_yaml)

    # Run CLI
    code = main(["run", "--config", str(config_file)])
    assert code == 0

    # Verify files created
    jsonl_path = tmp_path / "cli_test.jsonl"
    html_path = tmp_path / "cli_test.html"
    md_path = tmp_path / "cli_test.md"

    assert jsonl_path.exists()
    assert html_path.exists()
    assert md_path.exists()

    # Assert content of reports
    assert "model-test" in html_path.read_text()
    assert "model-test" in md_path.read_text()


def test_cli_report_re_render(monkeypatch, tmp_path):
    """AC-18: CLI report command correctly re-renders reports from an existing JSONL results file."""
    # Write a dummy results file
    r = {
        "question_id": "qst_0001",
        "category": "basic",
        "run_id": "rerender_test",
        "gen_ai": {"request": {"model": "model-test"}, "system": "openai"},
        "generation": {
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_s": 0.5,
            "model": "model-test",
            "system": "openai",
            "cost_usd": 0.0001,
        },
        "judge": {
            "input_tokens": 20,
            "output_tokens": 2,
            "latency_s": 0.2,
            "model": "gpt-5-nano-test",
            "system": "openai",
            "cost_usd": 0.00005,
        },
        "answer": "France's capital is Paris.",
        "sources": ["doc_1"],
        "fact_recall": 1.0,
        "fact_precision": 1.0,
        "faithfulness_ratio": 1.0,
        "retrieval_ranked_ids": ["doc_1"],
        "did_abstain_retrieval": False,
        "did_abstain_e2e": False,
    }

    results_file = tmp_path / "existing_results.jsonl"
    with open(results_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(r) + "\n")

    # Mock load_questions in report
    from enterprise_rag_ops.eval import report
    from enterprise_rag_ops.eval.questions import Question

    mock_qs = [Question("qst_0001", "Q1", ["F1"], ["doc_1"], "basic")]
    monkeypatch.setattr(report, "load_questions", lambda: mock_qs)

    # Run CLI report
    code = main(["report", "--results", str(results_file), "--output-dir", str(tmp_path)])
    assert code == 0

    # Check that reports were generated
    html_path = tmp_path / "existing_results.html"
    md_path = tmp_path / "existing_results.md"
    assert html_path.exists()
    assert md_path.exists()
    assert "model-test" in html_path.read_text()
