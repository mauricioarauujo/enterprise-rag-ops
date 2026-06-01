# Pattern: Eval-JSONL → Phoenix Replay

**Confidence**: HIGH — grounded in `exporter.py`, `phoenix_client.py`, `cli.py` (codebase).

## When to Use

Use this pattern to export an existing `results/*.jsonl` file into Arize Phoenix for
trace visualization and offline score inspection. Also use when wiring a new
`ScoreSink` implementation (e.g., a future Langfuse backend) — the `replay_jsonl`
function accepts any `ScoreSink` conformant object.

## The ScoreSink Protocol

All Phoenix interaction is behind `ScoreSink` (Protocol in `phoenix_client.py`) to
localize tool dependencies:

```python
class ScoreSink(Protocol):
    def reset_project(self, project: str) -> None: ...

    @contextmanager
    def start_span(
        self, name: str, openinference_span_kind: str, attributes: dict[str, Any]
    ) -> Generator[Any, None, None]: ...

    def log_scores(self, rows_by_metric: dict[str, list[dict[str, Any]]]) -> None: ...

    def flush(self) -> None: ...
```

The real implementation is `PhoenixScoreSink`; `NoOpScoreSink` is used for dry runs.

## Endpoint Normalization (Key Gotcha)

`PhoenixScoreSink.__init__` calls `split_endpoint(endpoint)` to produce two distinct
URLs: the OTLP-HTTP traces path (for `register`) and the bare base URL (for `Client`).
Passing the wrong URL to either causes `405` or `404` responses. Always use
`split_endpoint` when constructing the sink manually:

```python
from enterprise_rag_ops.observability.phoenix_client import PhoenixScoreSink

sink = PhoenixScoreSink(
    project="enterprise-rag-eval",
    endpoint="http://localhost:6006",        # or with /v1/traces — both work
)
```

## The Replay Loop

```python
from enterprise_rag_ops.observability.exporter import replay_jsonl

summary = replay_jsonl(
    path="results/baseline.jsonl",
    sink=sink,
    project="enterprise-rag-eval",
    dry_run=False,
)
# summary.records_parsed, .traces_exported, .scores_logged
```

Internal sequence in `replay_jsonl`:

1. Parse and validate all `EvalRecord` lines first (fast-fail on bad JSON).
2. `sink.reset_project(project)` — delete the project to clear stale spans.
3. For each record: open chain span → child spans → capture `span_ids` in-process.
4. `sink.flush()` — ensure OTel buffer drains before annotations reference span IDs.
5. `sink.log_scores(all_scores)` — write annotations via `log_span_annotations_dataframe`.
6. `sink.flush()` — final drain.

## Score Write-Back Shape

`build_score_rows(record, span_ids)` returns:

```python
{
    "did_abstain_e2e": [{"span_id": "...", "score": 1.0, "label": "true"}],
    "faithfulness_ratio": [{"span_id": "...", "score": 0.87, "label": "0.87"}],
    # ... other metrics if non-None
}
```

`log_scores` converts each metric's list to a `pd.DataFrame` and calls
`client.spans.log_span_annotations_dataframe(annotation_name=metric_name, annotator_kind="CODE", sync=True)`.

## CLI Usage

```bash
# Dry-run validation (no Phoenix required)
rag-export-traces --results results/baseline.jsonl --dry-run

# Full replay
rag-export-traces --results results/baseline.jsonl \
    --endpoint http://localhost:6006 \
    --project enterprise-rag-eval

# Use env var for endpoint
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006 rag-export-traces \
    --results results/baseline.jsonl
```

## Sources

- `src/enterprise_rag_ops/observability/exporter.py`
- `src/enterprise_rag_ops/observability/phoenix_client.py`
- `src/enterprise_rag_ops/observability/cli.py`
- See also: [concepts/reset-and-replay-idempotency.md](../concepts/reset-and-replay-idempotency.md)
