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

## Per-Fact Root-Cause Attribution (additive — sprint-8/phase-2)

The 5-label cascade above classifies records on **aggregate** metrics only. Sprint-8/phase-2
added an orthogonal, additive capability that attributes, at the per-fact level, _why_ a
failed fact was missed. It does not change `classify()`, the cascade order, the
`FailureMode` `StrEnum`, or any `is_*` helper — no record is reclassified.

### The signal: `supporting_doc_id` None-vs-non-None on failed facts

For a fact whose `verdict ∈ {absent, contradicted}`:

| `supporting_doc_id` | Root-cause label | Meaning                                                         |
| ------------------- | ---------------- | --------------------------------------------------------------- |
| `None`              | `retrieval_gap`  | No retrieved doc substantiated the fact; evidence never arrived |
| non-`None`          | `generation_gap` | Evidence WAS retrieved; the generator failed to use it          |

**Why None-vs-non-None is the correct signal (not a set-intersection):** phase-1's FR-5
hallucination guard collapses any `supporting_doc_id` not in the judge's retrieved set to
`None` _before_ persistence. That retrieved set equals `EvalRecord.retrieval_ranked_ids`
(same `chunk_hits` source, same doc-level dedup). Therefore every persisted
`supporting_doc_id` is either `None` or already a member of `retrieval_ranked_ids` — a
non-`None` intersection would be tautological. A defensive explicit membership check is
kept in code so the predicate survives a future guard removal.

### Public surface (two entry points)

**`root_cause.py`** — the shared leaf (pure: no I/O, no network, imports only
`eval.schema` + `eval.records`):

- `classify_fact_gap(fact_verdict, retrieval_ranked_ids) -> Literal["retrieval_gap","generation_gap"] | None`
  Returns `None` for `verdict == "present"`.
- `RootCauseRollup` — frozen dataclass: `retrieval_gap: int`, `generation_gap: int`,
  `no_failed_facts: bool`, `has_per_fact: bool`.
  `has_per_fact=False` signals degraded (pre-sprint-8 `per_fact=None`); distinct from
  "data present, zero gaps" (`has_per_fact=True`, both counts 0).
- `rollup(record: EvalRecord) -> RootCauseRollup` — applies `classify_fact_gap` across
  `record.per_fact`; graceful degradation: returns `RootCauseRollup(has_per_fact=False)`
  when `record.per_fact is None`, never raises.

**`failure_taxonomy.attribute_root_cause(record)`** — taxonomy-surface entry point;
delegates directly to `root_cause.rollup`. Use this when consuming attribution from
taxonomy-aware code.

### Null discipline at the report seam

`generate_report_data` aggregates rollups per category per model, then maps:

- No per-fact evidence in category (`any_evidence=False`) → `retrieval_gap_pct = None` → renders **N/A**.
- Evidence present, zero failed facts (`denom == 0`) → `retrieval_gap_pct = 0.0` → renders **0.0%**.

A missing signal never collapses into "zero gaps". The report re-derives "zero gaps"
from `retrieval_gap + generation_gap == 0` rather than reading `no_failed_facts` directly
(that field is reserved for a future per-record display).

## Sources

- `src/enterprise_rag_ops/eval/root_cause.py` — predicate, rollup, RootCauseRollup
- `src/enterprise_rag_ops/eval/failure_taxonomy.py` — all predicates, constants, `attribute_root_cause`
- `src/enterprise_rag_ops/eval/report.py` — root_cause key + Root-Cause Attribution render block
- `src/enterprise_rag_ops/eval/classify_cli.py` — CLI + atomic write
- `docs/adr/0008-failure-taxonomy.md` — full rationale, distribution stats
