# Pattern: Rule-Based Failure Classifier Cascade

**Confidence**: HIGH — grounded in `failure_taxonomy.py` + `classify_cli.py` (codebase).

## When to Use

Use when you need to assign a failure mode to an `EvalRecord`, extend the taxonomy with
a new label, or wire the classifier to a new output format. Also reference when
interpreting existing tagged JSONL output.

## The `classify` Function

```python
from enterprise_rag_ops.eval.failure_taxonomy import classify, FailureMode
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.questions import Question

mode: FailureMode = classify(record, question)
# Returns one of: ABSTENTION_ERROR, RETRIEVAL_MISS, HALLUCINATION, INCOMPLETE, CORRECT
```

`FailureMode` is a `StrEnum` — `.value` returns the string for JSON serialization.

## Cascade Implementation

```python
def classify(record: EvalRecord, question: Question) -> FailureMode:
    if is_abstention_error(record, question):
        return FailureMode.ABSTENTION_ERROR
    if is_retrieval_miss(record, question):
        return FailureMode.RETRIEVAL_MISS
    if is_hallucination(record, question):
        return FailureMode.HALLUCINATION
    if is_incomplete(record, question):
        return FailureMode.INCOMPLETE
    return FailureMode.CORRECT
```

## Individual Predicates (all importable)

```python
from enterprise_rag_ops.eval.failure_taxonomy import (
    is_abstention_error,
    is_retrieval_miss,
    is_hallucination,
    is_incomplete,
    HALLUCINATION_FAITHFULNESS_THRESHOLD,   # 0.5
    INCOMPLETE_RECALL_THRESHOLD,            # 0.5
)
```

Key guard in `is_hallucination`: skips when `faithfulness_ratio is None` (no sources
cited → not hallucination). Key guard in `is_incomplete`: skips when `fact_recall is None`.

## Bulk Classification via CLI

```bash
# Dry-run: print distribution, write nothing
rag-classify --results results/baseline.jsonl --dry-run

# Tag in-place (overwrites input)
rag-classify --results results/baseline.jsonl

# Tag to a new file
rag-classify --results results/baseline.jsonl --output results/baseline-tagged.jsonl
```

The CLI uses an atomic write: tempfile in the output directory, then `os.replace`.
If the write fails mid-stream, the temp file is cleaned up and the original is untouched.

## Gold Dataset Integration

`classify_cli.py` loads gold questions via `load_questions(revision=...)`. The default
revision is `config.DATASET_REVISION`. If a `question_id` in the JSONL is not found in
the gold set, the record is skipped for classification (keeps `failure_mode=None`) with
a warning log.

## Distribution Counter

The CLI tracks a `Counter[str]` over all records (including unclassified ones) and logs
the distribution on success:

```
INFO  abstention_error: 478
INFO  correct: 445
INFO  retrieval_miss: 28
INFO  hallucination: 33
INFO  incomplete: 15
INFO  None: 1          ← question_id not in gold
```

## Extending the Taxonomy

To add a new label:

1. Add the string to `FailureMode(StrEnum)`.
2. Write a predicate function following the `is_*` naming convention.
3. Insert it at the correct priority position in `classify()`.
4. Update thresholds in this file and in `_index.yaml`.
5. Run `rag-classify --dry-run` on the existing baseline to verify the distribution shift.

## Sources

- `src/enterprise_rag_ops/eval/failure_taxonomy.py`
- `src/enterprise_rag_ops/eval/classify_cli.py`
- `docs/adr/0008-failure-taxonomy.md`
- See also: [concepts/failure-taxonomy.md](../concepts/failure-taxonomy.md)
