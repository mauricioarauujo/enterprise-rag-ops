# Concept: Failure-Mode Taxonomy

**Confidence**: HIGH — grounded in `failure_taxonomy.py` + ADR-0008 (codebase).

## What It Is

A rule-based, five-label taxonomy that classifies each `EvalRecord` into exactly one
failure mode using aggregate metrics and the gold `Question`. Classification is
deterministic (no LLM involved).

## The Five Labels

| Label              | Meaning                                                                          |
| ------------------ | -------------------------------------------------------------------------------- |
| `abstention_error` | Model abstained on an answerable question, OR answered an unanswerable one       |
| `retrieval_miss`   | Answerable question; no gold doc reached the top-k slice                         |
| `hallucination`    | Retrieval hit; generated answer is unfaithful (`faithfulness_ratio < 0.5`)       |
| `incomplete`       | Retrieval hit, faithful; answer missed too many gold facts (`fact_recall < 0.5`) |
| `correct`          | All prior checks passed                                                          |

`correct` is not a failure mode — it is the default classification when no failure
predicate fires.

## Cascade Order and Predicates

The classifier follows a **strict first-match cascade**:

```
abstention_error → retrieval_miss → hallucination → incomplete → correct
```

**Predicates** (from `failure_taxonomy.py`):

```python
_should_abstain(q)   := len(q.expected_doc_ids) == 0
_retrieval_hit(r, q) := len(q.expected_doc_ids) > 0
                        and bool(set(q.expected_doc_ids) & set(r.retrieval_ranked_ids[:r.k]))

is_abstention_error  := _should_abstain(q) != r.did_abstain_e2e
is_retrieval_miss    := len(q.expected_doc_ids) > 0 and not _retrieval_hit(r, q)
is_hallucination     := _retrieval_hit(r, q) and r.faithfulness_ratio is not None
                        and r.faithfulness_ratio < 0.5
is_incomplete        := _retrieval_hit(r, q) and not is_hallucination(r, q)
                        and not r.did_abstain_e2e
                        and r.fact_recall is not None and r.fact_recall < 0.5
```

## Why `abstention_error` Is First

A false abstention (answerable question, model refused) produces `fact_recall = 0.0`
and no sources. Without the first-position check, such records would cascade through to
`incomplete` or fall through to `correct`. The first check ensures behavioral
discrepancies are surfaced before metric thresholds are applied.

## Threshold Values and Empirical Basis (ADR-0008)

| Threshold                              | Value              | Justification                                                                                 |
| -------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------- |
| `HALLUCINATION_FAITHFULNESS_THRESHOLD` | `0.5` (strict `<`) | Bimodal distribution: 433 at 1.0, 37 at <0.5 (7.1% tail), 21 exactly at 0.5 (excluded)        |
| `INCOMPLETE_RECALL_THRESHOLD`          | `0.5`              | Zero-inflated distribution; zeros dominated by abstentions/misses stripped earlier by cascade |

Post-cascade committed baseline: **33 hallucination** tags (less than the 37 isolated-predicate
count because some low-faithfulness records are claimed earlier by `abstention_error`/`retrieval_miss`).

## Field Ownership

`failure_mode: str | None = None` is defined on `EvalRecord` (ADR-0008). Default `None`
preserves backward compatibility: records produced before Phase 8 parse cleanly.
`rag-classify` writes the tagged JSONL atomically via tempfile + `os.replace`.

## Sources

- `src/enterprise_rag_ops/eval/failure_taxonomy.py` — all predicates and constants
- `src/enterprise_rag_ops/eval/classify_cli.py` — CLI + atomic write
- `docs/adr/0008-failure-taxonomy.md` — full rationale, distribution stats
