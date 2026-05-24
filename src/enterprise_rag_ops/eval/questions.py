"""Thin typed reader over the EnterpriseRAG-Bench `questions` config (FR-8).

Streams the 500-question eval set at the pinned `DATASET_REVISION` (imported from
`enterprise_rag_ops.ingest.config` so the SHA stays a single SSoT) and yields typed
`Question` objects. The judge call sites and the later Phase 5/6 runners consume these.

The raw→model field mapping (confirmed by a one-time streamed inspection of the
`questions` config at `DATASET_REVISION` during `/implement`):

| Raw field          | Type      | → `Question` field |
| ------------------ | --------- | ------------------ |
| `question_id`      | str       | `question_id`      |
| `question`         | str       | `question`         |
| `answer_facts`     | list[str] | `answer_facts`     |
| `expected_doc_ids` | list[str] | `expected_doc_ids` |
| `question_type`    | str       | `category`         |

`question_type` (e.g. `"basic"`) is the question's category; it is surfaced as the
scalar `category`. The raw `source_types` (list) and `gold_answer` (str) are not part of
the Phase 4 contract and are intentionally not surfaced — callers needing them extend the
model later (an additive, non-breaking change). Category filtering is **not** a loader
feature (Q5): callers filter the yielded objects with list comprehensions.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from datasets import load_dataset

from enterprise_rag_ops.ingest import config

QUESTIONS_CONFIG = "questions"
QUESTIONS_SPLIT = "test"


@dataclass(frozen=True, slots=True)
class Question:
    """One benchmark question with its gold per-fact annotations.

    Fields:
        question_id: Stable identifier, e.g. ``"qst_0001"``.
        question: The natural-language question text.
        answer_facts: Atomic gold facts the answer must contain — the per-fact
            recall checklist the judge scores against.
        expected_doc_ids: Gold `doc_id`s for retrieval scoring (Phase 5 owns the
            metric; carried here so the loader is the single typed reader).
        category: The question's `question_type` (e.g. ``"basic"``) — surfaced for
            downstream per-category breakdowns. Callers filter with comprehensions.
    """

    question_id: str
    question: str
    answer_facts: list[str]
    expected_doc_ids: list[str]
    category: str


def load_questions(
    limit: int | None = None,
    question_ids: list[str] | None = None,
    revision: str = config.DATASET_REVISION,
) -> Iterator[Question]:
    """Stream the `questions` config at a pinned revision, yielding `Question`s.

    Args:
        limit: If set, stop after yielding this many questions (post-filter).
        question_ids: If set, yield only questions whose `question_id` is in this
            set. Combine with `limit` for dev subsetting.
        revision: Dataset commit SHA; defaults to the pinned `DATASET_REVISION`.

    Category filtering is intentionally absent (Q5) — callers use a list
    comprehension over the yielded `Question.category`.
    """
    wanted = set(question_ids) if question_ids is not None else None

    dataset = load_dataset(
        config.DATASET_ID,
        QUESTIONS_CONFIG,
        split=QUESTIONS_SPLIT,
        revision=revision,
        streaming=True,
    )

    yielded = 0
    for row in dataset:
        if wanted is not None and row["question_id"] not in wanted:
            continue
        yield Question(
            question_id=row["question_id"],
            question=row["question"],
            answer_facts=list(row["answer_facts"]),
            expected_doc_ids=list(row["expected_doc_ids"]),
            category=row["question_type"],
        )
        yielded += 1
        if limit is not None and yielded >= limit:
            break
