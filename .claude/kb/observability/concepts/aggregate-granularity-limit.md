# Concept: Aggregate-Granularity Precision Limitation

**Confidence**: HIGH — grounded in `failure_taxonomy.py`, `records.py`, ADR-0007, ADR-0008.

## What It Is

The failure taxonomy classifier operates on **aggregate metrics only** — the three
scalar floats (`fact_recall`, `fact_precision`, `faithfulness_ratio`) and two boolean
flags (`did_abstain_e2e`, `did_abstain_retrieval`) stored in `EvalRecord`. The
per-fact and per-citation verdict arrays are intentionally excluded from the
persisted schema.

## Why Per-Fact Data Is Excluded

`EvalRecord` explicitly omits `per_fact` and `per_citation` checklists (ADR-0007
§ Storage Footprint). These are Python-derived intermediate objects that live only in
memory during a sweep run. Persisting them per record would:

- Significantly increase JSONL file size (potentially 10–50x per record).
- Slow down git clone and CI parsing.
- Provide diminishing returns — the aggregate floats already capture the signal needed
  for taxonomy classification and cost rollups.

## What the Classifier Cannot Do

Because only aggregates are available, the classifier cannot answer:

- _Which_ specific gold fact was missed in an `incomplete` record.
- _Which_ cited source was unfaithful in a `hallucination` record.
- _Which_ retrieval rank caused the miss in a `retrieval_miss` record.

The taxonomy assigns a **high-level diagnostic label**, not a fine-grained
citation audit. This is a design choice, not a bug — the label tells you _what class
of failure_ occurred; root-cause drilling requires re-running the eval with verbose
output or inspecting the raw answer text.

## Implications for Tooling

- The `rag-classify` CLI cannot be made more precise without schema changes.
- Phoenix annotations reflect the same aggregate granularity — `faithfulness_ratio`
  is a single float on the generation span, not per-doc scores.
- Future improvement path (not in scope): add an opt-in `--verbose` mode that writes
  per-fact lists to a separate sidecar file without bloating the main JSONL.

## Sources

- `src/enterprise_rag_ops/eval/records.py` — `EvalRecord` fields; per_fact excluded
- `src/enterprise_rag_ops/eval/failure_taxonomy.py` — classifier operates on aggregates
- `docs/adr/0007-eval-record-schema.md` — storage footprint rationale
- `docs/adr/0008-failure-taxonomy.md` § 6 — "Aggregate-Granularity Precision Limitation"
