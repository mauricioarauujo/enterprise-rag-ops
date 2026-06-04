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
            from enterprise_rag_ops.eval.raw_call import RawCall
            from enterprise_rag_ops.eval.records import CallStats

            return (
                self.generate(chunks, question),
                CallStats(
                    input_tokens=10_000_000,  # Very high usage
                    output_tokens=1_000_000,
                    latency_s=0.5,
                    model="expensive",
                    system="openai",
                ),
                RawCall(request={"model": "expensive"}, response={}),
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


def test_runner_factory_dispatch_google():
    """AC-6: ModelConfig(system="google") resolves through _GENERATOR_FACTORY to GeminiGenerator."""
    from enterprise_rag_ops.eval.runner import _GENERATOR_FACTORY
    from enterprise_rag_ops.generation.anthropic_generator import AnthropicGenerator
    from enterprise_rag_ops.generation.gemini_generator import GeminiGenerator
    from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator

    assert _GENERATOR_FACTORY["google"] is GeminiGenerator
    assert _GENERATOR_FACTORY["openai"] is OpenAIGenerator
    assert _GENERATOR_FACTORY["anthropic"] is AnthropicGenerator


def test_runner_populates_verdicts_ac4(monkeypatch, tmp_path, run_config):
    """AC-4: run run_evaluation, read the written JSONL record, assert record['per_fact'] and record['per_citation'] are correctly populated. Assert no extra calls (exactly 1 gen, 1 judge)."""
    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question
    from enterprise_rag_ops.retrieval import config as retrieval_config
    from enterprise_rag_ops.retrieval import pipeline

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")

    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    # Instrument Generator/Judge to count calls
    gen_call_count = 0
    judge_call_count = 0

    class InstrumentedGenerator(StubGenerator):
        def generate_with_stats(self, context_chunks, question):
            nonlocal gen_call_count
            gen_call_count += 1
            return super().generate_with_stats(context_chunks, question)

    class InstrumentedJudge(StubJudge):
        def judge_with_stats(self, question, answer_with_sources, answer_facts, retrieved_docs):
            nonlocal judge_call_count
            judge_call_count += 1
            return super().judge_with_stats(
                question, answer_with_sources, answer_facts, retrieved_docs
            )

    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [
            Question(
                question_id="q_test",
                question="Test question?",
                answer_facts=["Fact A", "Fact B"],
                expected_doc_ids=["doc_1"],
                category="general",
            )
        ],
    )

    run_config.output_dir = str(tmp_path)
    run_config.models = [run_config.models[0]]  # 1 model: model-a (openai)

    output_path = run_evaluation(
        run_config,
        generator_classes={"openai": InstrumentedGenerator},
        judge_class=InstrumentedJudge,
    )

    assert output_path.exists()
    lines = output_path.read_text().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])

    # Assert counts: exactly 1 generator call and 1 judge call
    assert gen_call_count == 1
    assert judge_call_count == 1

    # Assert per_fact carries verdict labels for those facts
    assert "per_fact" in record
    assert record["per_fact"] is not None
    assert len(record["per_fact"]) == 2
    assert record["per_fact"][0]["fact"] == "Fact A"
    assert record["per_fact"][0]["verdict"] == "present"
    assert record["per_fact"][1]["fact"] == "Fact B"
    assert record["per_fact"][1]["verdict"] == "present"

    # Assert per_citation matches
    assert "per_citation" in record
    assert record["per_citation"] is not None
    assert len(record["per_citation"]) == 1
    assert record["per_citation"][0]["doc_id"] == "doc_1"
    assert record["per_citation"][0]["verdict"] == "supported"


def test_runner_persist_bronze_integration(monkeypatch, tmp_path, run_config):
    """AC-8: persist_bronze writes gen and judge bronze files, matches JSONL outputs."""
    from enterprise_rag_ops.retrieval import config as retrieval_config
    from enterprise_rag_ops.retrieval import pipeline

    (tmp_path / "bm25").mkdir()
    (tmp_path / "lancedb").mkdir()
    (tmp_path / "chunks.json").write_text('["doc_1::0"]')
    monkeypatch.setattr(retrieval_config, "BM25_INDEX_DIR", tmp_path / "bm25")
    monkeypatch.setattr(retrieval_config, "LANCEDB_DIR", tmp_path / "lancedb")
    monkeypatch.setattr(retrieval_config, "CHUNK_ORDER_PATH", tmp_path / "chunks.json")
    monkeypatch.setattr(pipeline, "load_retriever", lambda: MockRetriever())

    from enterprise_rag_ops.eval import runner
    from enterprise_rag_ops.eval.questions import Question

    # Simple loader mock
    monkeypatch.setattr(
        runner,
        "load_questions",
        lambda limit: [
            Question(
                question_id="q_test",
                question="Test question?",
                answer_facts=["Fact A"],
                expected_doc_ids=["doc_1"],
                category="general",
            )
        ],
    )

    # Instrument the stubs to count calls (AC-8: no extra gen/judge call per question).
    gen_calls = 0
    judge_calls = 0

    class CountingGenerator(StubGenerator):
        def generate_with_stats(self, context_chunks, question):
            nonlocal gen_calls
            gen_calls += 1
            return super().generate_with_stats(context_chunks, question)

    class CountingJudge(StubJudge):
        def judge_with_stats(self, question, answer_with_sources, answer_facts, retrieved_docs):
            nonlocal judge_calls
            judge_calls += 1
            return super().judge_with_stats(
                question, answer_with_sources, answer_facts, retrieved_docs
            )

    # Redirect BronzeWriter's root into tmp_path for BOTH runs, so the no-bronze
    # assertion below inspects the exact location a leaking writer would write to
    # (the writer's default root is the CWD-relative `data/raw_eval`, not tmp_path).
    from enterprise_rag_ops.eval.bronze import BronzeWriter

    orig_init = BronzeWriter.__init__

    def patched_init(self, run_id, root=tmp_path / "raw_eval"):
        orig_init(self, run_id, root=root)

    monkeypatch.setattr(BronzeWriter, "__init__", patched_init)

    # 1. Run with persist_bronze = False
    run_config.output_dir = str(tmp_path / "results_no_bronze")
    run_config.run_id = "test_run_no_bronze"
    run_config.persist_bronze = False
    run_config.models = [run_config.models[0]]  # openai only

    output_path_no_bronze = run_evaluation(
        run_config,
        generator_classes={"openai": CountingGenerator},
        judge_class=CountingJudge,
    )
    assert output_path_no_bronze.exists()
    jsonl_no_bronze = output_path_no_bronze.read_text()

    # Verify no bronze files were written — check the tmp_path root the writer is
    # redirected to (symmetric with the persist=True assertion below).
    assert not (tmp_path / "raw_eval" / "test_run_no_bronze").exists()

    # 2. Run with persist_bronze = True. Reset counters so the assertion measures
    # only this run (AC-8: exactly one gen + one judge call per question).
    gen_calls = 0
    judge_calls = 0

    run_config.output_dir = str(tmp_path / "results_with_bronze")
    run_config.run_id = "test_run_with_bronze"
    run_config.persist_bronze = True

    output_path_with_bronze = run_evaluation(
        run_config,
        generator_classes={"openai": CountingGenerator},
        judge_class=CountingJudge,
    )
    assert output_path_with_bronze.exists()
    jsonl_with_bronze = output_path_with_bronze.read_text()

    rec_no_bronze = json.loads(jsonl_no_bronze.strip())
    rec_with_bronze = json.loads(jsonl_with_bronze.strip())
    rec_no_bronze["run_id"] = "test_run"
    rec_with_bronze["run_id"] = "test_run"
    assert rec_no_bronze == rec_with_bronze

    # Assert bronze files were written
    bronze_dir_with = tmp_path / "raw_eval" / "test_run_with_bronze"
    assert bronze_dir_with.exists()
    gen_file = bronze_dir_with / "q_test__model-a__gen.json"
    judge_file = bronze_dir_with / "q_test__model-a__judge.json"

    assert gen_file.exists()
    assert judge_file.exists()

    with open(gen_file) as f:
        gen_data = json.load(f)
    assert gen_data["schema_version"] == 1
    assert gen_data["meta"]["run_id"] == "test_run_with_bronze"
    assert gen_data["meta"]["call_type"] == "gen"
    assert "request" in gen_data
    assert "response" in gen_data

    with open(judge_file) as f:
        judge_data = json.load(f)
    assert judge_data["schema_version"] == 1
    assert judge_data["meta"]["run_id"] == "test_run_with_bronze"
    assert judge_data["meta"]["call_type"] == "judge"
    assert "request" in judge_data
    assert "response" in judge_data

    # AC-8: exactly one generator + one judge call this run — bronze adds no extra call.
    assert gen_calls == 1
    assert judge_calls == 1
