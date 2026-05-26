"""Unit tests for the evaluation runner (AC-2, AC-7, AC-11, AC-16, AC-17)."""

from __future__ import annotations

import json
import re

import pytest

from enterprise_rag_ops.eval.config import RunConfig
from enterprise_rag_ops.eval.records import Price
from enterprise_rag_ops.eval.runner import run_evaluation
from enterprise_rag_ops.eval.stub_judge import StubJudge
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


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def run_config() -> RunConfig:
    return RunConfig(
        models=[
            {"model_id": "model-a", "system": "openai"},
            {"model_id": "model-b", "system": "anthropic"},
        ],
        judge_model="gpt-5-nano-test",
        limit=2,
        k=10,
        output_dir="results_test",
        run_id="test_run",
        prices={
            "model-a": Price(input_usd_per_1m=0.1, output_usd_per_1m=0.2),
            "model-b": Price(input_usd_per_1m=0.5, output_usd_per_1m=1.0),
            "gpt-5-nano-test": Price(input_usd_per_1m=0.05, output_usd_per_1m=0.1),
        },
    )


# --- Tests ------------------------------------------------------------------


def test_runner_fail_fast_index_missing(monkeypatch, tmp_path, run_config):
    """AC-11: runner fails fast with clear message when index dirs are missing."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    # Point configuration to nonexistent temp dirs
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    with pytest.raises(
        RuntimeError,
        match=re.escape(
            "Gold-aware index artifacts are missing. Please run `make build-index-gold` first."
        ),
    ):
        run_evaluation(run_config)


def test_runner_fail_fast_index_not_gold_aware(monkeypatch, tmp_path, run_config):
    """FR-10: artifacts present but the corpus lacks the gold docs → fail fast.

    A plain (non-gold-aware) index passes the dir-existence check but contains ≈none of
    the benchmark's expected_doc_ids, yielding ~0% retrieval recall. The guard must catch
    that before the (expensive) retriever load, not silently emit junk scores.
    """
    from enterprise_rag_ops.retrieval import config as retrieval_config

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Sidecar holds a real chunk id, but for an unrelated doc — no gold doc present.
    (tmp_path / "chunks.json").write_text('["other_doc::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [Question("q1", "Q1", ["F1"], ["doc_1"], "basic")],
    )

    with pytest.raises(RuntimeError, match="not gold-aware"):
        run_evaluation(run_config)


def test_runner_loads_retriever_once(monkeypatch, tmp_path, run_config):
    """AC-7: runner loads retriever exactly once and reuses it across models."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    # Dummy mock index locations
    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Gold-aware sidecar: contains doc_1, matching the patched questions' gold doc (FR-10).
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')

    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    # Patch load_retriever
    load_count = 0

    def mock_load():
        nonlocal load_count
        load_count += 1
        return MockRetriever()

    from enterprise_rag_ops.retrieval import pipeline

    monkeypatch.setattr(pipeline, "load_retriever", mock_load)

    # Patch load_questions to return mock questions
    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [Question("q1", "What is capital of France?", ["Paris"], ["doc_1"], "basic")],
    )

    # Run
    run_config.output_dir = str(tmp_path)
    output_path = run_evaluation(
        run_config,
        generator_classes={"openai": StubGenerator, "anthropic": StubGenerator},
        judge_class=StubJudge,
    )

    assert load_count == 1
    assert output_path.exists()

    # Check that both models wrote a record
    lines = output_path.read_text().splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])
    assert rec1["gen_ai"]["request"]["model"] == "model-a"
    assert rec2["gen_ai"]["request"]["model"] == "model-b"


def test_runner_flushes_jsonl_early_stop(monkeypatch, tmp_path, run_config):
    """AC-2: runner flushes JSONL after each question processed, supporting crash-safe check-pointing."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Gold-aware sidecar: contains doc_1, matching the patched questions' gold doc (FR-10).
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    from enterprise_rag_ops.retrieval import pipeline

    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    # Mock generator that throws error on second question to simulate crash
    call_count = 0

    class CrashingGenerator(StubGenerator):
        def generate_with_stats(self, chunks, question):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RuntimeError("Generator crashed!")
            return super().generate_with_stats(chunks, question)

    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [
            Question("q1", "Q1", ["F1"], ["doc_1"], "cat"),
            Question("q2", "Q2", ["F2"], ["doc_1"], "cat"),
        ],
    )

    run_config.output_dir = str(tmp_path)
    run_config.models = [run_config.models[0]]  # Just one model

    with pytest.raises(RuntimeError, match="Generator crashed!"):
        run_evaluation(
            run_config,
            generator_classes={"openai": CrashingGenerator},
            judge_class=StubJudge,
        )

    # Check file exists and contains the first successful record
    output_path = tmp_path / f"{run_config.run_id}.jsonl"
    assert output_path.exists()
    lines = output_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["question_id"] == "q1"


def test_runner_cost_ceiling_overrun(monkeypatch, tmp_path, run_config):
    """AC-16: cost overrun guard halts runner when ceiling is exceeded."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Gold-aware sidecar: contains doc_1, matching the patched questions' gold doc (FR-10).
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    from enterprise_rag_ops.retrieval import pipeline

    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    # Stub generator that reports high token usage
    class ExpensiveGenerator(StubGenerator):
        def generate_with_stats(self, chunks, question):
            from enterprise_rag_ops.eval.records import CallStats

            return self.generate(chunks, question), CallStats(
                input_tokens=10_000_000,  # Very high usage
                output_tokens=1_000_000,
                latency_s=0.5,
                model="expensive",
                system="openai",
            )

    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [
            Question("q1", "Q1", ["F1"], ["doc_1"], "cat"),
            Question("q2", "Q2", ["F2"], ["doc_1"], "cat"),
            Question("q3", "Q3", ["F3"], ["doc_1"], "cat"),
        ],
    )

    run_config.output_dir = str(tmp_path)
    run_config.cost_ceiling_usd = 0.50  # Low ceiling
    run_config.prices = {
        "expensive": Price(input_usd_per_1m=0.10, output_usd_per_1m=0.50),
        "gpt-5-nano-test": Price(input_usd_per_1m=0.0, output_usd_per_1m=0.0),
    }
    # One call will cost: 10M*0.10/1M + 1M*0.50/1M = 1.0 + 0.5 = 1.50 USD
    # Ceiling is 0.50 USD, so it will cross it immediately and halt.

    output_path = run_evaluation(
        run_config,
        generator_classes={"openai": ExpensiveGenerator, "anthropic": ExpensiveGenerator},
        judge_class=StubJudge,
    )

    # Check file exists and contains only 1 record (the first expensive call that crossed the ceiling)
    assert output_path.exists()
    lines = output_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["question_id"] == "q1"


def test_runner_concurrency(monkeypatch, tmp_path, run_config):
    """AC-17: concurrent runner executes threads safely and outputs valid JSONL."""
    from enterprise_rag_ops.retrieval import config as retrieval_config

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Gold-aware sidecar: contains doc_1, matching the patched questions' gold doc (FR-10).
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    from enterprise_rag_ops.retrieval import pipeline

    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [Question(f"q{i}", f"Q{i}", [f"F{i}"], ["doc_1"], "cat") for i in range(10)],
    )

    run_config.output_dir = str(tmp_path)
    run_config.models = [run_config.models[0]]  # 1 model, 10 questions

    output_path = run_evaluation(
        run_config,
        generator_classes={"openai": StubGenerator},
        judge_class=StubJudge,
        concurrency=4,  # Run with 4 threads
    )

    assert output_path.exists()
    lines = output_path.read_text().splitlines()
    assert len(lines) == 10

    # Assert all JSON lines are valid and have unique question IDs
    question_ids = set()
    for line in lines:
        data = json.loads(line)
        question_ids.add(data["question_id"])
    assert len(question_ids) == 10


def test_runner_concurrency_propagates_worker_exception(monkeypatch, tmp_path, run_config):
    """A worker exception under --concurrency must propagate, not be silently swallowed.

    Guards the `for _ in executor.map(...)` consumption: a discarded map result would
    hide the crash and leave a short JSONL while the run reports success.
    """
    from enterprise_rag_ops.retrieval import config as retrieval_config

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    # Gold-aware sidecar: contains doc_1, matching the patched questions' gold doc (FR-10).
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    from enterprise_rag_ops.retrieval import pipeline

    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    class CrashingGenerator(StubGenerator):
        def generate_with_stats(self, chunks, question):
            raise RuntimeError("Generator crashed in worker!")

    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [Question(f"q{i}", f"Q{i}", [f"F{i}"], ["doc_1"], "cat") for i in range(4)],
    )

    run_config.output_dir = str(tmp_path)
    run_config.models = [run_config.models[0]]

    with pytest.raises(RuntimeError, match="Generator crashed in worker!"):
        run_evaluation(
            run_config,
            generator_classes={"openai": CrashingGenerator},
            judge_class=StubJudge,
            concurrency=2,
        )
