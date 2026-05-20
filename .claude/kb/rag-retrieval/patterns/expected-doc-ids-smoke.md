# Expected Doc IDs Smoke Test

> **Purpose**: Phase 2 exit gate — assert Recall@k > 0 using `expected_doc_ids`
> from the dataset `questions` config, via `HybridRetriever` loaded from persisted
> artifacts. Run with `make retrieval-smoke` (local-only, not part of `make verify`).
> **Codebase Grounded**: 2026-05-20 (Sprint 1 Phase 2 merged)

## When to Use

- Validating the Phase 2 retriever before moving to Phase 3.
- Any time chunking or index parameters change and regression risk is high.
- Sprint 2 eval harness bootstrapping (extends this to full recall@k/MRR/nDCG).

## Implementation

```python
"""test_retrieval_smoke.py — Phase 2 exit gate.

Marked `smoke`; excluded from `make verify`. Run with `make retrieval-smoke`.

Prerequisites:
- `make build-index` has run (creates BM25 + LanceDB artifacts).
- `data/processed/corpus.jsonl` exists (from `make download-data`).
"""
from __future__ import annotations

import pytest
from enterprise_rag_ops.retrieval import config, pipeline

pytestmark = pytest.mark.smoke

# Three questions selected via streaming the dataset `questions` config and
# intersecting `expected_doc_ids` with the local 900-doc corpus subset (RQ-2).
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
            "after-action review is acceptable instead of writing the full formal analysis?"
        ),
        "expected_doc_ids": ["dsid_01eaeaf6045941beaeaf74e6170aceea"],
    },
    {
        "question_id": "qst_0258",
        "source_type": "jira",
        "query": (
            "In the us-east dedicated setup for a big retail tenant, what caused the multi-hour "
            "staircase of gateway failures during peak traffic?"
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
    """Load the persisted BGE-M3 retriever — slow path, requires build-index."""
    if not config.LANCEDB_DIR.exists():
        pytest.skip(
            f"No index at {config.LANCEDB_DIR} — run `make build-index` first."
        )
    if not config.CORPUS_PATH.exists():
        pytest.skip(f"No corpus at {config.CORPUS_PATH} — run `make download-data` first.")
    return pipeline.load_retriever()   # opens BM25 + LanceDB; no re-encoding


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
        assert len(doc_ids) == len(set(doc_ids)), (
            f"{q['question_id']}: duplicate doc_ids in output"
        )
```

## Configuration

| Setting            | Default                  | Description                                       |
| ------------------ | ------------------------ | ------------------------------------------------- |
| `TOP_K`            | 10 (`config.TOP_K`)      | Evaluation depth; matches recommended eval window |
| Smoke question set | 3 fixed questions (RQ-2) | Expand to full 500 questions in Sprint 2          |
| Dedup key          | `doc_id` = `Document.id` | Must match `expected_doc_ids` in the dataset      |

## Key Invariants

- `retriever.retrieve()` returns `(doc_id, score)` pairs already deduplicated — the
  retriever owns deduplication (`deduplicate_to_docs`), not the test.
- The smoke test uses `pipeline.load_retriever()` — opens the persisted BM25 and
  LanceDB artifacts, no corpus re-encoding at query time (NFR-1).
- `chunk_id = f"{doc_id}::{offset}"` is the deterministic anchor; `Chunk.doc_id` is
  always the foreign key back to `Document.id`, even when a document produces many chunks.
- The 3 questions were selected 2026-05-19 by streaming `questions@<DATASET_REVISION>`
  and intersecting `expected_doc_ids` with the 900-doc corpus subset (RQ-2).

## See Also

- [patterns/hybrid-retrieve-fuse.md](hybrid-retrieve-fuse.md)
- [concepts/retrieval-eval-metrics.md](../concepts/retrieval-eval-metrics.md)
- `tests/retrieval/test_retrieval_smoke.py` — the canonical source
- `docs/adr/0002-retrieval-architecture.md` — build-time invariants
