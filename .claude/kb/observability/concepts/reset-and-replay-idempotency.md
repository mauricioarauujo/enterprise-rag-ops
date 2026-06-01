# Concept: Reset-and-Replay Idempotency

**Confidence**: HIGH — grounded in `exporter.py` + `phoenix_client.py` (codebase) +
ADR-0004 Acceptance Note.

## What It Is

The replay exporter achieves idempotency by **deleting the entire Phoenix project before
every replay**, then re-importing all records fresh. This is "reset-and-replay"
idempotency, not upsert-by-seed.

## Why Phoenix Has No Upsert-by-Seed

The original ADR-0004 phased plan assumed Langfuse's `create_score(id=...)` pattern —
passing a deterministic UUID as an idempotency key for score write-back. When the
project switched to Arize Phoenix (hardware rationale — 8 GB machine cannot run
ClickHouse+Postgres+Redis), the equivalent upsert primitive did not exist in the
Phoenix client. Phoenix's span annotations API (`log_span_annotations_dataframe`) does
not support deterministic span IDs or idempotency keys at ingest time.

## The Reset-and-Replay Sequence

```
1. sink.reset_project(project)        ← delete everything in the project
2. for record in records:
     build span tree → emit spans    ← fresh span IDs each time
     collect span_ids (in-process)
3. sink.flush()                       ← ensure spans reach Phoenix
4. sink.log_scores(all_scores)        ← annotate using freshly captured span_ids
5. sink.flush()                       ← ensure annotations are written
```

Step 1 must complete before step 2 begins. Steps 3 and 4 must be ordered: Phoenix
spans must be committed before annotations reference their IDs.

## Known Limitation

`PhoenixScoreSink.reset_project` catches **all** exceptions from
`client.projects.delete()`, not just the "project not found" case. This means
auth failures or network errors are silently swallowed with a warning log, and the
export proceeds — potentially writing duplicate traces if the project was not actually
cleared. The `make trace-reset` Docker volume wipe is the documented fallback (see
`DESIGN.md`). This is a known TODO in `phoenix_client.py`:

```
# TODO(observability): narrow this to the 404-style "project not found" error
```

## Dry-Run Path

`replay_jsonl(..., dry_run=True)` parses and validates all records but skips `reset_project`,
span emission, and score write-back entirely. The CLI uses `NoOpScoreSink` for dry runs,
which returns a dummy span with a fixed `span_id=1`. This means `build_score_rows` is
never called in dry-run mode — the summary reports `scores_logged=0`.

## Sources

- `src/enterprise_rag_ops/observability/exporter.py` — replay sequence
- `src/enterprise_rag_ops/observability/phoenix_client.py` — `reset_project`, known limitation comment
- `docs/adr/0004-observability-tool.md` § Acceptance Note — hardware rationale, no upsert primitive
- Research (pillar 3): Langfuse `create_score(id=...)` upsert pattern (alternatives considered note)
