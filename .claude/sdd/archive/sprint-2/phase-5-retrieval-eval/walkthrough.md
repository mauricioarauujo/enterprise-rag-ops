# Walkthrough - Retrieval Metrics & Gold-Aware Corpus

We have successfully implemented **Sprint 2 Phase 5: Retrieval Metrics & Gold-Aware Corpus**.

## Changes Made

### 1. Ingest & Sampling

- **Gold-Aware Sampling**: Added `gold_aware_sample` in [sampler.py](src/enterprise_rag_ops/ingest/sampler.py) to stream and include every gold document (via `expected_doc_ids`) from answerable questions, and add stratified distractors per source, sorted deterministically.
- **CLI Flags**: Updated [cli.py](src/enterprise_rag_ops/ingest/cli.py) to support `--gold-aware` and `--distractors-per-source` flags.

### 2. Retrieval Map Fix

- Rebuilt the `chunk_id -> doc_id` and `chunk_id -> source_type` maps inside `load_retriever` (in [pipeline.py](src/enterprise_rag_ops/retrieval/pipeline.py)) using the `embeddings.chunks.json` sidecar and the LanceDB store columns directly. This resolves the regression where `corpus.jsonl` was re-read and re-chunked at query time.

### 3. Evaluation Metrics & Category Aggregation

- **Pure Metrics**: Created [retrieval_metrics.py](src/enterprise_rag_ops/eval/retrieval_metrics.py) implementing document-level deduplication (chunk -> doc, first wins) and calculating `recall_at_k`, `precision_at_k`, `mrr`, and `ndcg_at_k`.
- **Per-Category Aggregation**: Created [retrieval_eval.py](src/enterprise_rag_ops/eval/retrieval_eval.py) grouping metric averages by category while correctly skipping `None`/empty-denominator values.

### 4. Abstention Scorer & Cassette Replay

- **Scorers**: Created [abstention.py](src/enterprise_rag_ops/eval/abstention.py) implementing:
  - Retrieval-level abstention checking (retriever returns `[]` because best dense hit is below threshold).
  - End-to-end abstention checking (system answers matching `ABSTAIN_ANSWER` and cites 0 sources).
- **Offline testing (VCR)**: Configured `vcrpy` cassette integration in [conftest.py](tests/eval/conftest.py) to replay OpenAI requests offline using the committed cassette [abstention_info_not_found.yaml](tests/eval/cassettes/abstention_info_not_found.yaml).

### 5. Architectural Decision Records (ADRs)

- Created [0005-llm-provider-matrix.md](docs/adr/0005-llm-provider-matrix.md) capturing our LLM provider strategy and role definitions.
- Created [0006-cassette-replay.md](docs/adr/0006-cassette-replay.md) documenting the offline cassette testing decision.
- Updated [0002-retrieval-architecture.md](docs/adr/0002-retrieval-architecture.md) index and index in [README.md](docs/adr/README.md).

### 6. Sweep Script & Makefile Targets

- Created [threshold_sweep.py](src/enterprise_rag_ops/eval/threshold_sweep.py) and added `build-index-gold` and `retrieval-eval` targets to [Makefile](Makefile).

## Verification Results

### 1. Automated Tests

All 170 pytest unit/integration tests pass offline under 3 seconds:

```bash
make lint test
```

Outputs:

```
uv run ruff format --check src tests
83 files already formatted
uv run ruff check src tests
All checks passed!
npx prettier --check "**/*.md" --ignore-path .gitignore --log-level warn
uv run pytest -m "not corpus and not smoke"
====================== 170 passed, 17 deselected in 2.54s ======================
```

### 2. Threshold Sweep Output (Manual Verification)

We ran the sweep script over the 500-question eval set:

```bash
make retrieval-eval
```

Output:

```
Threshold  | Precision  | Recall     | F1-Score   | TP/FP/FN/TN
-----------------------------------------------------------------
0.30       | None       | 0.0000     | None       | 0/0/30/470
0.35       | None       | 0.0000     | None       | 0/0/30/470
0.40       | None       | 0.0000     | None       | 0/0/30/470
0.45       | None       | 0.0000     | None       | 0/0/30/470
0.50       | 0.0000     | 0.0000     | None       | 0/2/30/468
0.55       | 0.0556     | 0.0333     | 0.0417     | 1/17/29/453
0.60       | 0.0924     | 0.3667     | 0.1477     | 11/108/19/362
0.65       | 0.0609     | 0.7333     | 0.1125     | 22/339/8/131
```

_Findings_:

- The current default threshold `0.45` is a high-precision, zero-false-positive operating point (preventing any incorrect abstentions on answerable questions, though yielding 0.0 recall on unanswerable ones).
- Raising the threshold increases recall (detecting unanswerable questions) at the cost of a high False Positive rate due to the dense model's uncalibrated score distribution.

## Answerability Inspection (AC-2)

One-time inspection of the `questions` config at `DATASET_REVISION` (500 questions),
confirming the `len(expected_doc_ids) > 0` answerability predicate (Q1) — **not** a
`category == "info_not_found"` string check.

| Category                 | Total | Empty `expected_doc_ids` |
| ------------------------ | ----: | -----------------------: |
| basic                    |   175 |                        0 |
| semantic                 |   125 |                        0 |
| intra_document_reasoning |    40 |                        0 |
| project_related          |    40 |                        0 |
| constrained              |    30 |                        0 |
| completeness             |    20 |                        0 |
| conflicting_info         |    20 |                        0 |
| miscellaneous            |    20 |                        0 |
| **info_not_found**       |    20 |                   **20** |
| **high_level**           |    10 |                   **10** |
| **Total**                |   500 |                   **30** |

**Conclusion.** 30 questions are unanswerable. The predicate is the correct filter: a
`category == "info_not_found"` check would catch only 20 and **silently mishandle the 10
empty-gold `high_level` questions** (treating them as answerable). The predicate makes all
30 fall out for free and stay legitimately unanswerable (FR-3).

**Forward note (Phase 6).** Abstention scope must be the empty-gold predicate (**30** q),
not the `info_not_found` category (20 q). The scorers in `eval/abstention.py` already key
on `len(expected_doc_ids) == 0`, so they handle all 30 correctly — the Phase-6 runner just
needs to pass the full unanswerable set, not filter by category string.
