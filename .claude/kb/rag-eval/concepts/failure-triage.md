# Failure Triage: Groupby-Aggregate over Classified Eval JSONL

> **Purpose**: How `rag-triage` turns a classified eval JSONL into a deterministic,
> ranked summary of failure clusters — and the cross-phase contract that ties it to
> `rag-issues` and the observability taxonomy.
> **Confidence**: HIGH (codebase — `eval/triage.py`, `eval/triage_cli.py`; ADR-0009)

## What Triage Does

`compute_triage` takes a list of `EvalRecord` objects that have already been
classified (every `failure_mode` field is non-`None`) and produces a `TriageReport`
— a ranked summary of `(failure_mode, category)` clusters.

The cluster key uses the **record's own `category` field**, not a gold question
lookup. Gold questions are only accessed to fetch `representative_question_text` for
the representative example; they are not part of the grouping key.

## The Two Frozen Dataclasses

```python
@dataclass(frozen=True, slots=True)
class TriageCluster:
    failure_mode: str
    category: str
    count: int
    rate: float                          # count / total_records (see none-empty-denominator)
    representative_question_id: str
    representative_question_text: str
    models_seen: list[str]               # sorted; across the cluster, not the whole run

@dataclass(frozen=True, slots=True)
class TriageReport:
    schema_version: str                  # SCHEMA_VERSION = "1.0"
    total_records: int
    models_seen: list[str]               # sorted; all models across every cluster
    dominant_cluster: TriageCluster | None
    clusters: list[TriageCluster]        # sorted: count desc, (failure_mode, category) asc
```

`frozen=True` prevents accidental mutation post-construction; `slots=True` saves
memory on large result sets.

## Rate Convention

`rate = count / total_records`. When `total_records == 0` the report is empty and
`dominant_cluster` is `None` — the function short-circuits before any division.
The `None` empty-denominator convention (see `[[none-empty-denominator]]`) does not
apply here because `total_records == 0` is handled by the early-return, not by
returning `None` for `rate`. A cluster by definition has `count >= 1`, so the
division is always safe.

## Deterministic Representative Selection

The representative for each cluster is the record with the **lexicographically
smallest `question_id`** — `min(bucket, key=lambda r: r.question_id)`. This
choice is deterministic across re-runs with the same input and does not require
sorting the full bucket.

## Fail-Fast on Unclassified Input

```python
for r in records:
    if r.failure_mode is None:
        raise ValueError(
            f"Record {r.question_id!r} is unclassified (failure_mode is None); "
            "run rag-classify first."
        )
```

`rag-triage` refuses to run on a mixed JSONL that contains unclassified records.
The caller must run `rag-classify` first. There is no partial-skip or silent drop.

## SCHEMA_VERSION as Cross-Phase Contract

`SCHEMA_VERSION = "1.0"` is embedded in `TriageReport.schema_version`. Every
downstream consumer (`rag-issues`, any future diff/compare tool) must gate on this
value before processing — a mismatch is a hard error, not a warning. A future schema
bump intentionally changes the version so old consumers reject new reports rather
than silently misread them.

## Deterministic Serialization

`_report_to_dict` / `_cluster_to_dict` serialize with a **fixed key order** (not
`sort_keys=True`). The CLI uses `json.dump(..., indent=2, sort_keys=False)`. This
produces a stable diff-friendly JSON where key order reflects the logical field order
of the dataclass, not alphabetical sort.

## Cluster Sort Order

Clusters are ranked `count desc`, tiebreaker `(failure_mode, category) asc`. The
first cluster after sort is `dominant_cluster`. A `dominant_cluster` pointer is
included at the top level of `TriageReport` so consumers do not need to index into
`clusters[0]`.

## Related

- [eval-record-schema.md](eval-record-schema.md) — `EvalRecord.failure_mode` field
- [none-empty-denominator.md](none-empty-denominator.md) — rate denominator convention
- [../../observability/concepts/failure-taxonomy.md](../../observability/concepts/failure-taxonomy.md) — the taxonomy that assigns `failure_mode`
- `eval/triage.py` — `compute_triage`, `TriageReport`, `TriageCluster`, `_report_to_dict`
- `eval/triage_cli.py` — pure-core + thin-CLI split, atomic JSON write
- `docs/adr/0009-triage-to-issues.md`
- [../patterns/triage-to-issues.md](../patterns/triage-to-issues.md)
