# Expected Doc IDs Smoke Test

> **Purpose**: Phase 2 exit gate — assert Recall@k > 0 using `expected_doc_ids`
> from the dataset `questions` config, with correct chunk-to-doc deduplication.
> **MCP Validated**: 2026-05-17

## When to Use

- Validating the Phase 2 retriever before moving to Phase 3.
- Any time chunking or index parameters change and regression risk is high.
- Sprint 2 eval harness bootstrapping (extends this to full recall@k/MRR/nDCG).

## Implementation

```python
"""test_retrieval_smoke.py — Phase 2 exit gate.

Assumes:
- data/processed/corpus.jsonl exists (from make download-data)
- A fixed question subset with expected_doc_ids is available
- hybrid_retrieve() from hybrid_retriever.py
"""
import json
from pathlib import Path
import pytest
from enterprise_rag_ops.ingest.schema import Document
from retrieval.hybrid_retriever import Chunk, build_bm25_index, hybrid_retrieve
from sentence_transformers import SentenceTransformer


CORPUS_PATH = Path("data/processed/corpus.jsonl")
TOP_K = 10
# Smoke questions: a small fixed subset with known expected_doc_ids.
# In Sprint 2 this grows to the full 500-question eval set.
SMOKE_QUESTIONS = [
    {
        "query": "What is the company PTO policy?",
        "expected_doc_ids": ["doc_001", "doc_002"],
    },
    # Add more questions from the dataset questions config here.
]


def load_corpus_as_chunks(path: Path) -> list[Chunk]:
    """Load corpus.jsonl -> Chunk list. chunk_id = doc_id (no sub-chunking yet)."""
    chunks = []
    with path.open() as f:
        for line in f:
            doc = Document.model_validate_json(line)
            # Phase 2 may split each Document into multiple Chunks.
            # Until chunk splitting is implemented, doc == chunk (1:1 mapping).
            chunks.append(Chunk(chunk_id=doc.id, doc_id=doc.id, text=doc.text))
    return chunks


def recall_at_k(
    retrieved_doc_ids: list[str],
    expected: list[str],
    k: int,
) -> float:
    """Standard Recall@k — deduplication must have already happened upstream."""
    top_k = set(retrieved_doc_ids[:k])
    relevant = set(expected)
    if not relevant:
        return 1.0  # vacuously correct
    return len(top_k & relevant) / len(relevant)


@pytest.fixture(scope="module")
def retriever_components():
    """Build index once per module to keep smoke test fast."""
    chunks = load_corpus_as_chunks(CORPUS_PATH)
    bm25, _ = build_bm25_index(chunks)
    model = SentenceTransformer("BAAI/bge-m3")
    return chunks, bm25, model


def test_recall_above_zero(retriever_components):
    """Phase 2 exit gate: every smoke query must hit at least one expected doc."""
    chunks, bm25, model = retriever_components
    failures = []
    for q in SMOKE_QUESTIONS:
        results = hybrid_retrieve(
            query=q["query"],
            chunks=chunks,
            bm25=bm25,
            model=model,
            top_k=TOP_K,
        )
        retrieved_ids = [doc_id for doc_id, _ in results]
        r_at_k = recall_at_k(retrieved_ids, q["expected_doc_ids"], TOP_K)
        if r_at_k == 0.0:
            failures.append(
                f"query={q['query']!r} recall@{TOP_K}=0.0 "
                f"expected={q['expected_doc_ids']} got={retrieved_ids[:5]}"
            )
    assert not failures, "Smoke gate failed:\n" + "\n".join(failures)


def test_deduplication_contract(retriever_components):
    """Retriever must return unique doc IDs — no duplicate doc_id in top-k."""
    chunks, bm25, model = retriever_components
    query = SMOKE_QUESTIONS[0]["query"]
    results = hybrid_retrieve(query=query, chunks=chunks, bm25=bm25, model=model)
    doc_ids = [doc_id for doc_id, _ in results]
    assert len(doc_ids) == len(set(doc_ids)), "Duplicate doc_ids in retriever output"
```

## Configuration

| Setting            | Default                  | Description                                       |
| ------------------ | ------------------------ | ------------------------------------------------- |
| `TOP_K`            | 10                       | Evaluation depth; matches recommended eval window |
| Smoke question set | Fixed subset             | Expand to full 500 questions in Sprint 2          |
| Dedup key          | `doc_id` = `Document.id` | Must match `expected_doc_ids` in the dataset      |

## Key Invariants

- `retrieved_doc_ids` passed to `recall_at_k` must already be deduplicated — the
  retriever owns deduplication, not the test.
- The smoke test uses a fixed question subset; `expected_doc_ids` for the full eval
  set lives in the dataset `questions` config (Sprint 2 scope).
- `chunk_id == doc_id` in the 1:1 phase; after sub-chunking is added in Phase 2,
  `Chunk.doc_id` is the foreign key back to `Document.id`.

## See Also

- [patterns/hybrid-retrieve-fuse.md](hybrid-retrieve-fuse.md)
- [concepts/retrieval-eval-metrics.md](../concepts/retrieval-eval-metrics.md)
- `src/enterprise_rag_ops/ingest/schema.py` — `Document.id` definition
