"""Tests for the ingest CLI's record-adaptation step."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.ingest.cli import adapt_records, main, run
from enterprise_rag_ops.ingest.schema import Document, UnknownSourceTypeError


def _raw(doc_id: str, source_type: str = "slack", content: str = "body") -> dict:
    return {"doc_id": doc_id, "source_type": source_type, "title": "T", "content": content}


def test_adapt_records_yields_documents_for_valid_input():
    skipped: Counter = Counter()
    docs = list(adapt_records(iter([_raw("d1"), _raw("d2")]), skipped))
    assert [d.id for d in docs] == ["d1", "d2"]
    assert all(isinstance(d, Document) for d in docs)
    assert skipped == Counter()


def test_adapt_records_skips_and_counts_invalid_records():
    raw = [_raw("d1"), _raw("d2", content=""), _raw("d3", content="   ")]
    skipped: Counter = Counter()
    docs = list(adapt_records(iter(raw), skipped))
    assert [d.id for d in docs] == ["d1"]
    assert skipped == Counter({"slack": 2})


def test_adapt_records_propagates_unknown_source_type():
    skipped: Counter = Counter()
    with pytest.raises(UnknownSourceTypeError):
        list(adapt_records(iter([_raw("d1", source_type="notion")]), skipped))


def test_main_parses_gold_aware_flags():
    with patch("enterprise_rag_ops.ingest.cli.run") as mock_run:
        main(["--gold-aware", "--distractors-per-source", "25"])
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["gold_aware"] is True
        assert kwargs["distractors_per_source"] == 25


def test_run_gold_aware_mode():
    with (
        patch("enterprise_rag_ops.ingest.cli.stream_documents") as mock_stream_docs,
        patch("enterprise_rag_ops.ingest.cli.load_questions") as mock_load_qs,
        patch("enterprise_rag_ops.ingest.cli.gold_aware_sample") as mock_sampler,
        patch("enterprise_rag_ops.ingest.cli.write_corpus") as mock_writer,
    ):
        mock_stream_docs.return_value = iter(
            [{"doc_id": "doc1", "source_type": "slack", "title": "T", "content": "body"}]
        )
        mock_load_qs.return_value = iter(
            [
                Question(
                    question_id="q1",
                    question="Q",
                    answer_facts=[],
                    expected_doc_ids=["doc1"],
                    category="basic",
                ),
                # Empty gold question is excluded from gold_ids predicate
                Question(
                    question_id="q2",
                    question="Q2",
                    answer_facts=[],
                    expected_doc_ids=[],
                    category="info_not_found",
                ),
            ]
        )
        mock_sampler.return_value = []
        mock_writer.return_value = 0

        run(
            docs_per_source=100,
            output=Path("dummy"),
            revision="rev",
            gold_aware=True,
            distractors_per_source=10,
        )

        mock_load_qs.assert_called_once_with(revision="rev")
        mock_sampler.assert_called_once()
        args, _ = mock_sampler.call_args
        # args[1] is the gold_ids set
        assert args[1] == {"doc1"}
        assert args[2] == 10
