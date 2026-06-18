"""Phoenix client seam (NFR-3).

All imports from phoenix.* and opentelemetry.* are strictly contained in this file
to ensure that a future tool swap is localized here.
"""

import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Protocol

import pandas as pd
from opentelemetry import trace
from phoenix.client import Client
from phoenix.otel import register

logger = logging.getLogger("enterprise_rag_ops.observability.phoenix_client")

_OTLP_HTTP_TRACES_PATH = "/v1/traces"

# Annotation ingestion-race retry budget. `provider.force_flush()` guarantees spans are
# *sent* over OTLP, not yet *persisted*/queryable by Phoenix — annotations posted with
# sync=True validate span existence server-side and 404 ("span not found") in that window.
# Measured lag is sub-second; a short bounded linear backoff clears it. Only the first
# metric pays the wait — once spans are queryable the rest succeed on attempt 1.
_ANNOTATION_INGEST_RETRIES = 6
_ANNOTATION_INGEST_BACKOFF_S = 0.5


def split_endpoint(endpoint: str) -> tuple[str, str]:
    """Split a user-supplied endpoint into (OTLP-HTTP traces URL, Phoenix client base URL).

    `phoenix.otel.register(endpoint=...)` configures the OTLP-HTTP span exporter; it
    expects the full traces path (`.../v1/traces`). `phoenix.client.Client(base_url=...)`
    expects the bare server root (no `/v1/traces`). Users typing
    `PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006` or passing
    `--endpoint http://localhost:6006/v1/traces` must both work — so normalize here.
    """
    stripped = endpoint.rstrip("/")
    if stripped.endswith(_OTLP_HTTP_TRACES_PATH):
        base_url = stripped[: -len(_OTLP_HTTP_TRACES_PATH)]
        otlp_endpoint = stripped
    else:
        base_url = stripped
        otlp_endpoint = stripped + _OTLP_HTTP_TRACES_PATH
    return otlp_endpoint, base_url


class ScoreSink(Protocol):
    """Protocol defining the operations required for trace and score replay (NFR-3)."""

    def reset_project(self, project: str) -> None:
        """Clear all existing records/spans for the target project (FR-4)."""
        ...

    @contextmanager
    def start_span(
        self,
        name: str,
        openinference_span_kind: str,
        attributes: dict[str, Any],
        *,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> Generator[Any, None, None]:
        """Start a new span within the current context, capturing its span_id (FR-3, FR-4).

        Optional `start_time`/`end_time` (epoch ns) override the span's wall-clock so the
        native latency widget reflects the real per-call duration on replay (B-05).
        """
        ...

    def log_scores(self, rows_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        """Write back evaluation metrics to their semantically aligned spans (FR-5)."""
        ...

    def flush(self) -> None:
        """Ensure all buffered spans and annotations are delivered (FR-5)."""
        ...


class PhoenixScoreSink(ScoreSink):
    """Real implementation of ScoreSink communicating with a running Phoenix instance."""

    def __init__(self, project: str, endpoint: str):
        self.project = project
        self.endpoint = endpoint

        # Normalize the user-supplied endpoint into the two distinct URLs Phoenix needs:
        # the OTLP-HTTP traces path (for `register`) and the bare server root (for
        # `Client`). Mismatching either causes 405 (root POST) or 404 (wrong path).
        otlp_endpoint, base_url = split_endpoint(endpoint)

        # Resolve credentials from env only (Q4)
        api_key = os.environ.get("PHOENIX_API_KEY")

        # Register the TracerProvider (FR-3)
        self.provider = register(
            project_name=project,
            endpoint=otlp_endpoint,
            api_key=api_key,
            set_global_tracer_provider=True,
            verbose=False,
        )
        self.tracer = trace.get_tracer("replay-exporter", tracer_provider=self.provider)

        # Initialize the Phoenix client for metadata & score upload (FR-5)
        self.client = Client(base_url=base_url, api_key=api_key)

    def reset_project(self, project: str) -> None:
        """Clear all existing records/spans for the target project (FR-4)."""
        logger.info(f"Resetting project '{project}' via deletion API...")
        try:
            self.client.projects.delete(project_name=project)
        except Exception as e:
            # TODO(observability): narrow this to the 404-style "project not found" error
            # the Phoenix client raises. Today this also swallows auth/network failures,
            # which would let the export proceed and produce duplicate traces — defeating
            # FR-4 idempotency. The `make trace-reset` volume-wipe is the documented
            # fallback (DESIGN § Reset-and-replay) until the narrow exception is wired.
            logger.warning(f"Could not delete project '{project}': {e}")

    @contextmanager
    def start_span(
        self,
        name: str,
        openinference_span_kind: str,
        attributes: dict[str, Any],
        *,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> Generator[Any, None, None]:
        """Start a new span within the current context, capturing its span_id (FR-3, FR-4).

        Optional `start_time`/`end_time` (epoch ns) override the span's wall-clock so the
        native latency widget reflects the real per-call duration on replay (B-05).
        """
        # Default path: auto-timestamped span (no latency override).
        if start_time is None:
            with self.tracer.start_as_current_span(
                name, openinference_span_kind=openinference_span_kind, attributes=attributes
            ) as span:
                yield span
            return

        # Latency-faithful path (B-05): create the span with an explicit start_time, make it
        # the current span for child nesting WITHOUT auto-ending it, then end at end_time so
        # the span's duration is the real latency_s, not the millisecond replay duration.
        span = self.tracer.start_span(
            name,
            openinference_span_kind=openinference_span_kind,
            attributes=attributes,
            start_time=start_time,
        )
        try:
            with trace.use_span(span, end_on_exit=False):
                yield span
        finally:
            span.end(end_time=end_time)

    def log_scores(self, rows_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        """Write back evaluation metrics to their semantically aligned spans (FR-5)."""
        for metric_name, rows in rows_by_metric.items():
            if not rows:
                continue

            # Convert to DataFrame as required by client.spans.log_span_annotations_dataframe
            df = pd.DataFrame(rows)

            logger.info(f"Logging {len(rows)} annotations for metric '{metric_name}'")
            self._log_metric_with_ingest_retry(metric_name, df)

    def _log_metric_with_ingest_retry(self, metric_name: str, df: pd.DataFrame) -> None:
        """POST one metric's annotations, retrying the transient 404 raised while Phoenix
        is still ingesting the just-flushed spans (see _ANNOTATION_INGEST_* above)."""
        for attempt in range(1, _ANNOTATION_INGEST_RETRIES + 1):
            try:
                self.client.spans.log_span_annotations_dataframe(
                    dataframe=df,
                    annotation_name=metric_name,
                    annotator_kind="CODE",
                    sync=True,
                )
                return
            except Exception as e:
                # A 404 here is "span not found" — the spans are still being ingested, not
                # a missing endpoint. Retry that case only; surface everything else at once.
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status == 404 and attempt < _ANNOTATION_INGEST_RETRIES:
                    wait = _ANNOTATION_INGEST_BACKOFF_S * attempt
                    logger.debug(
                        "Annotations for '%s' 404'd (spans not yet queryable); "
                        "retry %d/%d after %.1fs",
                        metric_name,
                        attempt,
                        _ANNOTATION_INGEST_RETRIES - 1,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"Failed to log annotations for metric '{metric_name}': {e}")
                return

    def flush(self) -> None:
        """Ensure all buffered spans and annotations are delivered (FR-5)."""
        logger.info("Flushing TracerProvider...")
        try:
            self.provider.force_flush()
        except Exception as e:
            logger.warning(f"Failed to force flush TracerProvider: {e}")
