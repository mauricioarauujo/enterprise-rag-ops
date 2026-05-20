"""Real-model `Recall@k` smoke gate — local-only, **not** part of `make verify`.

Selected during `/implement` (per RQ-2) by streaming the dataset `questions`
config at the pinned SHA and keeping only questions whose `expected_doc_ids`
appear in the local 900-doc corpus subset. Of the 500 questions, three match —
that hits the FR-12 minimum (3 to 5) and is the deterministic input here.

Run with: ``make retrieval-smoke``.
"""

from __future__ import annotations

import pytest

from enterprise_rag_ops.retrieval import config, pipeline

pytestmark = pytest.mark.smoke

# Selected 2026-05-19 via streaming `questions@<DATASET_REVISION>` and
# intersecting `expected_doc_ids` with `data/processed/corpus.jsonl` (RQ-2).
# All three are `basic` / `semantic` questions whose expected doc lives in the
# default 100-docs-per-source stratified subset.
SMOKE_QUESTIONS: list[dict] = [
    {
        "question_id": "qst_0104",
        "source_type": "confluence",
        "query": (
            "What is the standard amount of time a new hire buddy is expected to spend per day "
            "during the first two weeks when a long-term contractor is converted to a full-time employee?"
        ),
        "expected_doc_ids": ["dsid_005f7a937cad4b3cbb30d9d93199e22a"],
    },
    {
        "question_id": "qst_0252",
        "source_type": "confluence",
        "query": (
            "In our incident response process, what is the rule for when a quick time-boxed "
            "after-action review is acceptable instead of writing the full formal analysis, "
            "based on impact duration and whether the issue hit one customer versus many?"
        ),
        "expected_doc_ids": ["dsid_01eaeaf6045941beaeaf74e6170aceea"],
    },
    {
        "question_id": "qst_0258",
        "source_type": "jira",
        "query": (
            "In the us-east dedicated setup for a big retail tenant, what caused the multi-hour "
            "staircase of gateway failures during peak traffic when long-lived chat streams "
            "coincided with a large embedding batch?"
        ),
        "expected_doc_ids": ["dsid_019864ee09fa428e919e9a0de11ca467"],
    },
]


def recall_at_k(retrieved_doc_ids: list[str], expected: list[str], k: int) -> float:
    """Standard Recall@k. Caller must already have deduplicated to docs."""
    top_k = set(retrieved_doc_ids[:k])
    relevant = set(expected)
    return len(top_k & relevant) / len(relevant) if relevant else 1.0


@pytest.fixture(scope="module")
def retriever():
    """Build (or reuse) the index and return a real BGE-M3 retriever — slow path."""
    if not config.LANCEDB_DIR.exists():
        pytest.skip(
            f"No index at {config.LANCEDB_DIR} — run `make build-index` first "
            "(downloads BGE-M3 if needed)."
        )
    if not config.CORPUS_PATH.exists():
        pytest.skip(f"No corpus at {config.CORPUS_PATH} — run `make download-data` first.")
    return pipeline.load_retriever()


@pytest.mark.parametrize("question", SMOKE_QUESTIONS, ids=lambda q: q["question_id"])
def test_recall_at_10_above_zero(retriever, question):
    """AC-12 (first half): every smoke query hits at least one expected doc."""
    results = retriever.retrieve(question["query"], top_k=config.TOP_K)
    retrieved_doc_ids = [doc_id for doc_id, _ in results]
    r_at_k = recall_at_k(retrieved_doc_ids, question["expected_doc_ids"], config.TOP_K)
    assert r_at_k > 0.0, (
        f"{question['question_id']}: Recall@{config.TOP_K}=0.0; "
        f"expected={question['expected_doc_ids']} got={retrieved_doc_ids[:5]}"
    )


def test_unique_doc_ids_per_result(retriever):
    """AC-12 (second half): retriever output has no duplicate doc_id."""
    for q in SMOKE_QUESTIONS:
        results = retriever.retrieve(q["query"], top_k=config.TOP_K)
        doc_ids = [doc_id for doc_id, _ in results]
        assert len(doc_ids) == len(set(doc_ids)), f"{q['question_id']}: duplicate doc_ids in output"
