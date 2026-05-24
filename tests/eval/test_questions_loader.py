"""`Question` loader tests (AC-9, AC-10).

Offline by construction — `load_dataset` is monkeypatched to yield canned rows mirroring
the raw `questions` schema confirmed by the one-time inspection at `DATASET_REVISION`, so
the loader's field mapping, subsetting, and dataset coordinates are verified with **no
network** and no `OPENAI_API_KEY`.

Corpus-coverage caveat (AC-13 / Q4): the loader yields all 500 questions, but the dev
corpus subset has gold docs for only ~3 of them. That is a retrieval-coverage property of
the sampled corpus, not a loader concern — the loader faithfully yields every question
and its gold annotations regardless of whether the gold doc is in the local subset.
"""

from __future__ import annotations

import inspect

import pytest

from enterprise_rag_ops.eval import questions as questions_mod
from enterprise_rag_ops.eval.questions import Question, load_questions
from enterprise_rag_ops.ingest import config

_RAW_ROWS = [
    {
        "question_id": "qst_0001",
        "question_type": "basic",
        "source_types": ["github"],
        "question": "What are the default upload size limits?",
        "expected_doc_ids": ["dsid_aaa"],
        "gold_answer": "10 MiB per file, 50 MiB per request.",
        "answer_facts": ["Per-file limit is 10 MiB.", "Total request limit is 50 MiB."],
    },
    {
        "question_id": "qst_0002",
        "question_type": "multi_hop",
        "source_types": ["linear", "github"],
        "question": "What metric tracks streaming finalization?",
        "expected_doc_ids": ["dsid_bbb"],
        "gold_answer": "stream.timebox_finalized",
        "answer_facts": ["The metric is stream.timebox_finalized."],
    },
]


@pytest.fixture
def fake_load_dataset(monkeypatch):
    """Patch `load_dataset` to return canned rows; capture the call kwargs."""
    captured = {}

    def _fake(dataset_id, config_name, *, split, revision, streaming):
        captured["args"] = (dataset_id, config_name)
        captured["split"] = split
        captured["revision"] = revision
        captured["streaming"] = streaming
        return list(_RAW_ROWS)

    monkeypatch.setattr(questions_mod, "load_dataset", _fake)
    return captured


def test_yields_typed_questions_with_all_five_fields(fake_load_dataset):
    qs = list(load_questions())
    assert all(isinstance(q, Question) for q in qs)
    first = qs[0]
    assert first.question_id == "qst_0001"
    assert first.question == "What are the default upload size limits?"
    assert first.answer_facts == ["Per-file limit is 10 MiB.", "Total request limit is 50 MiB."]
    assert first.expected_doc_ids == ["dsid_aaa"]
    # category maps from the raw `question_type` field (confirmed by inspection).
    assert first.category == "basic"
    assert qs[1].category == "multi_hop"


def test_streams_correct_dataset_coordinates(fake_load_dataset):
    list(load_questions())
    assert fake_load_dataset["args"] == (config.DATASET_ID, "questions")
    assert fake_load_dataset["split"] == "test"
    assert fake_load_dataset["revision"] == config.DATASET_REVISION
    assert fake_load_dataset["streaming"] is True


def test_limit_restricts_yielded_count(fake_load_dataset):
    assert len(list(load_questions(limit=1))) == 1


def test_question_ids_filters(fake_load_dataset):
    qs = list(load_questions(question_ids=["qst_0002"]))
    assert [q.question_id for q in qs] == ["qst_0002"]


def test_no_category_filter_parameter():
    """Category filtering is not a loader feature (Q5) — callers use comprehensions."""
    params = set(inspect.signature(load_questions).parameters)
    assert "category" not in params
    assert params == {"limit", "question_ids", "revision"}
