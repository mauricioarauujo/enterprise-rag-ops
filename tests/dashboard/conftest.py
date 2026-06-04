"""Offline fixtures for dashboard tests (B-01: deterministic CI).

The dashboard report/summary path (`eval.report.generate_report_data`) calls
`load_questions()`, which streams the gold set from the HF Hub. That made the
"offline" dashboard tests network-dependent and flaky in CI: when the Hub was
unreachable they failed with `LocalEntryNotFoundError`. Mirror the
`tests/eval/test_report.py` pattern — monkeypatch `report.load_questions` — but
source the gold from a committed minimal fixture so the real 500-question
baseline still exercises the real category/abstention/retrieval paths,
hermetically.

Only the fields `generate_report_data` reads are vendored (`question_id`,
`category`, `expected_doc_ids`); question text and `answer_facts` are not used
on that path, so they are left empty.
"""

import json
from pathlib import Path

import pytest

from enterprise_rag_ops.eval import report
from enterprise_rag_ops.eval.questions import Question

_FIXTURE = Path(__file__).parent / "fixtures" / "gold_questions.jsonl"


def _load_gold_fixture() -> list[Question]:
    questions: list[Question] = []
    with open(_FIXTURE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            questions.append(
                Question(
                    question_id=row["question_id"],
                    question="",
                    answer_facts=[],
                    expected_doc_ids=list(row["expected_doc_ids"]),
                    category=row["category"],
                )
            )
    return questions


@pytest.fixture(autouse=True)
def offline_gold_questions(monkeypatch):
    """Serve the gold set from the committed fixture, never the live HF Hub (B-01).

    Autouse + scoped to `tests/dashboard/`, so production `load_questions` is
    untouched everywhere else. Accepts any call signature the real loader has.
    """
    gold = _load_gold_fixture()
    monkeypatch.setattr(report, "load_questions", lambda *args, **kwargs: gold)
