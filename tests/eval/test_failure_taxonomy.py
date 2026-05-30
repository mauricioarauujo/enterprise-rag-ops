"""Unit and offline CLI tests for failure taxonomy and classification (FR-12, AC-10)."""

from __future__ import annotations

from unittest.mock import patch

from enterprise_rag_ops.eval.failure_taxonomy import (
    FailureMode,
    classify,
    is_abstention_error,
    is_hallucination,
    is_incomplete,
    is_retrieval_miss,
)
from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.eval.records import (
    CallStats,
    EvalRecord,
    GenAiFields,
    GenAiOperation,
    GenAiRequest,
)
from enterprise_rag_ops.ingest import config


def make_eval_record(
    question_id: str = "q1",
    fact_recall: float | None = 1.0,
    faithfulness_ratio: float | None = 1.0,
    retrieval_ranked_ids: list[str] | None = None,
    did_abstain_retrieval: bool = False,
    did_abstain_e2e: bool = False,
    k: int = 10,
    failure_mode: str | None = None,
) -> EvalRecord:
    """Helper to build a dummy EvalRecord with defaults."""
    return EvalRecord(
        question_id=question_id,
        category="test-category",
        run_id="test-run",
        k=k,
        gen_ai=GenAiFields(
            request=GenAiRequest(model="test-model"),
            system="test-system",
            operation=GenAiOperation(name="chat"),
        ),
        generation=CallStats(
            input_tokens=10,
            output_tokens=10,
            latency_s=0.5,
            model="test-model",
            system="test-system",
            cost_usd=0.0001,
        ),
        judge=CallStats(
            input_tokens=10,
            output_tokens=10,
            latency_s=0.5,
            model="test-model",
            system="test-system",
            cost_usd=0.0001,
        ),
        answer="test answer",
        sources=["doc1"] if retrieval_ranked_ids else [],
        fact_recall=fact_recall,
        fact_precision=1.0,
        faithfulness_ratio=faithfulness_ratio,
        retrieval_ranked_ids=retrieval_ranked_ids or [],
        did_abstain_retrieval=did_abstain_retrieval,
        did_abstain_e2e=did_abstain_e2e,
        failure_mode=failure_mode,
    )


def make_question(
    question_id: str = "q1",
    expected_doc_ids: list[str] | None = None,
) -> Question:
    """Helper to build a dummy Question with defaults."""
    return Question(
        question_id=question_id,
        question="test question?",
        answer_facts=["fact1"],
        expected_doc_ids=expected_doc_ids or [],
        category="test-category",
    )


def test_enum_membership():
    """AC-1: FailureMode has exactly five members and serializes to string."""
    expected_members = {
        "abstention_error",
        "retrieval_miss",
        "hallucination",
        "incomplete",
        "correct",
    }
    actual_members = {member.value for member in FailureMode}
    assert actual_members == expected_members
    assert len(FailureMode) == 5

    # Check Pydantic round-trip with string values
    assert FailureMode.ABSTENTION_ERROR.value == "abstention_error"


def test_pydantic_roundtrip():
    """AC-6: Untagged line parses failure_mode to None; tagged line round-trips correctly."""
    # Pre-Phase 8 JSON record representation (no failure_mode key)
    untagged_json = (
        '{"question_id": "q1", "category": "test", "run_id": "r1", "k": 10, '
        '"gen_ai": {"request": {"model": "m"}, "system": "s", "operation": {"name": "c"}}, '
        '"generation": {"input_tokens": 1, "output_tokens": 1, "latency_s": 0.1, "model": "m", "system": "s"}, '
        '"judge": {"input_tokens": 1, "output_tokens": 1, "latency_s": 0.1, "model": "m", "system": "s"}, '
        '"answer": "a", "sources": [], "fact_recall": null, "fact_precision": null, "faithfulness_ratio": null, '
        '"retrieval_ranked_ids": [], "did_abstain_retrieval": false, "did_abstain_e2e": false}'
    )

    record = EvalRecord.model_validate_json(untagged_json)
    assert record.failure_mode is None

    # Tagged JSON record representation
    record.failure_mode = "hallucination"
    dumped = record.model_dump_json()
    assert '"failure_mode":"hallucination"' in dumped

    parsed = EvalRecord.model_validate_json(dumped)
    assert parsed.failure_mode == "hallucination"


def test_one_fixture_per_label():
    """Assert one fixture per label maps to the expected FailureMode classification."""
    # 1. ABSTENTION_ERROR
    # False abstention: Answerable question, but model abstained.
    q_abstain = make_question(expected_doc_ids=["doc1"])
    rec_abstain = make_eval_record(did_abstain_e2e=True)
    assert classify(rec_abstain, q_abstain) == FailureMode.ABSTENTION_ERROR

    # 2. RETRIEVAL_MISS
    # Answerable, did not abstain, but retrieval ranked IDs do not intersect gold docs
    q_miss = make_question(expected_doc_ids=["doc1"])
    rec_miss = make_eval_record(retrieval_ranked_ids=["doc2"])
    assert classify(rec_miss, q_miss) == FailureMode.RETRIEVAL_MISS

    # 3. HALLUCINATION
    # Retrieval hit, faithfulness < 0.5
    q_hallucination = make_question(expected_doc_ids=["doc1"])
    rec_hallucination = make_eval_record(
        retrieval_ranked_ids=["doc1"], faithfulness_ratio=0.4, fact_recall=1.0
    )
    assert classify(rec_hallucination, q_hallucination) == FailureMode.HALLUCINATION

    # 4. INCOMPLETE
    # Retrieval hit, faithfulness >= 0.5 (or None), recall < 0.5
    q_incomplete = make_question(expected_doc_ids=["doc1"])
    rec_incomplete = make_eval_record(
        retrieval_ranked_ids=["doc1"], faithfulness_ratio=1.0, fact_recall=0.4
    )
    assert classify(rec_incomplete, q_incomplete) == FailureMode.INCOMPLETE

    # 5. CORRECT
    # No issues, above thresholds
    q_correct = make_question(expected_doc_ids=["doc1"])
    rec_correct = make_eval_record(
        retrieval_ranked_ids=["doc1"], faithfulness_ratio=1.0, fact_recall=1.0
    )
    assert classify(rec_correct, q_correct) == FailureMode.CORRECT


def test_cascade_priority_wins():
    """AC-2: when multiple predicates fire, the higher-priority label wins.

    The canonical "false abstention + low recall" example is degenerate here because
    is_incomplete guards on `not did_abstain_e2e`. The genuine multi-fire case is a
    false abstention that is *also* a retrieval miss: is_abstention_error and
    is_retrieval_miss both evaluate True independently, and the cascade must return the
    higher-priority abstention_error.
    """
    q = make_question(expected_doc_ids=["doc1"])  # answerable
    rec = make_eval_record(
        did_abstain_e2e=True,  # false abstention -> is_abstention_error True
        retrieval_ranked_ids=["doc2"],  # gold not in top-k -> is_retrieval_miss True
    )
    # Both predicates fire on independent evaluation.
    assert is_abstention_error(rec, q)
    assert is_retrieval_miss(rec, q)
    # First-match-wins: the higher-priority label is returned.
    assert classify(rec, q) == FailureMode.ABSTENTION_ERROR


def test_edge_cases_fr12_ac10():
    """AC-10: Test specific edge cases from the contract requirements.

    Edge cases:
      (i) None faithfulness on a correct abstention -> correct, never hallucination
      (ii) retrieval miss with None fact_recall -> retrieval_miss, not incomplete
      (iii) a full-hit correct record -> correct
      (iv) a false abstention (answerable, model abstained, 0/None recall) -> abstention_error, not hallucination/incomplete
      (v) None fact_recall on a retrieval-hit non-abstaining record does not mis-fire incomplete
    """
    # Case (i): None faithfulness on a correct abstention -> correct, never hallucination
    # Correct abstention: unanswerable question (expected_doc_ids is empty) and did_abstain_e2e is True.
    q_i = make_question(expected_doc_ids=[])
    rec_i = make_eval_record(did_abstain_e2e=True, faithfulness_ratio=None, retrieval_ranked_ids=[])
    assert not is_abstention_error(rec_i, q_i)
    assert not is_retrieval_miss(rec_i, q_i)
    assert not is_hallucination(rec_i, q_i)
    assert not is_incomplete(rec_i, q_i)
    assert classify(rec_i, q_i) == FailureMode.CORRECT

    # Case (ii): retrieval miss with None fact_recall -> retrieval_miss, not incomplete
    q_ii = make_question(expected_doc_ids=["doc1"])
    rec_ii = make_eval_record(
        did_abstain_e2e=False, retrieval_ranked_ids=["doc2"], fact_recall=None
    )
    assert is_retrieval_miss(rec_ii, q_ii)
    assert classify(rec_ii, q_ii) == FailureMode.RETRIEVAL_MISS

    # Case (iii): a full-hit correct record -> correct
    q_iii = make_question(expected_doc_ids=["doc1"])
    rec_iii = make_eval_record(
        did_abstain_e2e=False,
        retrieval_ranked_ids=["doc1"],
        faithfulness_ratio=1.0,
        fact_recall=1.0,
    )
    assert classify(rec_iii, q_iii) == FailureMode.CORRECT

    # Case (iv): a false abstention (answerable, model abstained, 0/None recall) -> abstention_error, not hallucination/incomplete
    q_iv = make_question(expected_doc_ids=["doc1"])
    rec_iv = make_eval_record(
        did_abstain_e2e=True,
        retrieval_ranked_ids=["doc1"],
        faithfulness_ratio=None,
        fact_recall=None,
    )
    assert is_abstention_error(rec_iv, q_iv)
    assert classify(rec_iv, q_iv) == FailureMode.ABSTENTION_ERROR

    # Case (v): None fact_recall on a retrieval-hit non-abstaining record does not mis-fire incomplete
    q_v = make_question(expected_doc_ids=["doc1"])
    rec_v = make_eval_record(
        did_abstain_e2e=False,
        retrieval_ranked_ids=["doc1"],
        faithfulness_ratio=1.0,
        fact_recall=None,
    )
    assert not is_incomplete(rec_v, q_v)
    assert classify(rec_v, q_v) == FailureMode.CORRECT


def test_classify_cli_offline(tmp_path):
    """AC-7: Test the CLI offline over a 2-record JSONL using an injected gold map."""
    results_file = tmp_path / "results.jsonl"

    # Create two records to write
    rec1 = make_eval_record(
        question_id="q1",
        fact_recall=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["doc1"],
    )
    rec2 = make_eval_record(
        question_id="q2",
        fact_recall=1.0,
        faithfulness_ratio=0.3,
        retrieval_ranked_ids=["doc2"],
    )

    with open(results_file, "w", encoding="utf-8") as f:
        f.write(rec1.model_dump_json() + "\n")
        f.write(rec2.model_dump_json() + "\n")

    # Injected gold questions
    q1 = make_question(question_id="q1", expected_doc_ids=["doc1"])
    q2 = make_question(question_id="q2", expected_doc_ids=["doc2"])
    mock_questions = [q1, q2]

    # Patch load_questions to avoid network calls
    with patch("enterprise_rag_ops.eval.classify_cli.load_questions") as mock_load:
        mock_load.return_value = mock_questions

        from enterprise_rag_ops.eval.classify_cli import main

        retval = main(["--results", str(results_file)])
        assert retval == 0
        mock_load.assert_called_once_with(revision=config.DATASET_REVISION)

    # Read back and verify output
    with open(results_file, encoding="utf-8") as f:
        lines = f.readlines()

    out_rec1 = EvalRecord.model_validate_json(lines[0])
    out_rec2 = EvalRecord.model_validate_json(lines[1])

    assert out_rec1.failure_mode == "correct"
    assert out_rec2.failure_mode == "hallucination"


def test_classify_cli_dry_run(tmp_path, capsys):
    """AC-14: Test --dry-run prints Counter distribution and writes nothing."""
    results_file = tmp_path / "results_dry.jsonl"
    rec = make_eval_record(
        question_id="q1",
        fact_recall=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["doc1"],
    )

    with open(results_file, "w", encoding="utf-8") as f:
        f.write(rec.model_dump_json() + "\n")

    q1 = make_question(question_id="q1", expected_doc_ids=["doc1"])

    with patch("enterprise_rag_ops.eval.classify_cli.load_questions") as mock_load:
        mock_load.return_value = [q1]

        from enterprise_rag_ops.eval.classify_cli import main

        retval = main(["--results", str(results_file), "--dry-run"])
        assert retval == 0

    # The distribution is printed to stdout under --dry-run.
    out = capsys.readouterr().out
    assert "Failure mode distribution:" in out
    assert "correct: 1" in out

    # Ensure the file's failure_mode field remains None (no write)
    with open(results_file, encoding="utf-8") as f:
        line = f.read()

    loaded_rec = EvalRecord.model_validate_json(line)
    assert loaded_rec.failure_mode is None


def test_classify_cli_revision_forwarding(tmp_path):
    """AC-14: Test --questions-revision overrides the pinned SHA and forwards to loader."""
    results_file = tmp_path / "results_rev.jsonl"
    rec = make_eval_record(
        question_id="q1",
        fact_recall=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["doc1"],
    )

    with open(results_file, "w", encoding="utf-8") as f:
        f.write(rec.model_dump_json() + "\n")

    q1 = make_question(question_id="q1", expected_doc_ids=["doc1"])

    with patch("enterprise_rag_ops.eval.classify_cli.load_questions") as mock_load:
        mock_load.return_value = [q1]

        from enterprise_rag_ops.eval.classify_cli import main

        retval = main(["--results", str(results_file), "--questions-revision", "custom-rev-sha"])
        assert retval == 0
        mock_load.assert_called_once_with(revision="custom-rev-sha")


def test_classify_cli_skips_missing_question_id(tmp_path, caplog):
    """DESIGN: a record whose question_id is absent from the gold map is skipped.

    It passes through untagged (failure_mode stays None), a warning is logged, and the
    run still returns 0 — robustness over fail-fast for a one-time idempotent classifier.
    """
    import logging

    results_file = tmp_path / "results_missing.jsonl"
    # q1 is in the gold map; q_unknown is not.
    rec_known = make_eval_record(
        question_id="q1",
        fact_recall=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["doc1"],
    )
    rec_unknown = make_eval_record(
        question_id="q_unknown",
        fact_recall=1.0,
        faithfulness_ratio=1.0,
        retrieval_ranked_ids=["doc1"],
    )

    with open(results_file, "w", encoding="utf-8") as f:
        f.write(rec_known.model_dump_json() + "\n")
        f.write(rec_unknown.model_dump_json() + "\n")

    q1 = make_question(question_id="q1", expected_doc_ids=["doc1"])

    with patch("enterprise_rag_ops.eval.classify_cli.load_questions") as mock_load:
        mock_load.return_value = [q1]

        from enterprise_rag_ops.eval.classify_cli import main

        with caplog.at_level(logging.WARNING):
            retval = main(["--results", str(results_file)])
        assert retval == 0
        assert "q_unknown" in caplog.text

    with open(results_file, encoding="utf-8") as f:
        lines = f.readlines()

    out_known = EvalRecord.model_validate_json(lines[0])
    out_unknown = EvalRecord.model_validate_json(lines[1])

    assert out_known.failure_mode == "correct"
    assert out_unknown.failure_mode is None
