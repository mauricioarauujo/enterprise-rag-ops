"""Phoenix client seam (NFR-3).

All imports from phoenix.* and opentelemetry.* are strictly contained in this file
to ensure that a future tool swap is localized here.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Protocol

import pandas as pd
from opentelemetry import trace
from phoenix.client import Client
from phoenix.otel import register

logger = logging.getLogger("enterprise_rag_ops.observability.phoenix_client")

_OTLP_HTTP_TRACES_PATH = "/v1/traces"


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
        self, name: str, openinference_span_kind: str, attributes: dict[str, Any]
    ) -> Generator[Any, None, None]:
        """Start a new span within the current context, capturing its span_id (FR-3, FR-4)."""
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
        self, name: str, openinference_span_kind: str, attributes: dict[str, Any]
    ) -> Generator[Any, None, None]:
        """Start a new span within the current context, capturing its span_id (FR-3, FR-4)."""
        # Pass the openinference_span_kind directly to tracer.start_as_current_span
        with self.tracer.start_as_current_span(
            name, openinference_span_kind=openinference_span_kind, attributes=attributes
        ) as span:
            yield span

    def log_scores(self, rows_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        """Write back evaluation metrics to their semantically aligned spans (FR-5)."""
        for metric_name, rows in rows_by_metric.items():
            if not rows:
                continue

            # Convert to DataFrame as required by client.spans.log_span_annotations_dataframe
            df = pd.DataFrame(rows)

            logger.info(f"Logging {len(rows)} annotations for metric '{metric_name}'")
            try:
                self.client.spans.log_span_annotations_dataframe(
                    dataframe=df,
                    annotation_name=metric_name,
                    annotator_kind="CODE",
                    sync=True,
                )
            except Exception as e:
                logger.error(f"Failed to log annotations for metric '{metric_name}': {e}")

    def flush(self) -> None:
        """Ensure all buffered spans and annotations are delivered (FR-5)."""
        logger.info("Flushing TracerProvider...")
        try:
            self.provider.force_flush()
        except Exception as e:
            logger.warning(f"Failed to force flush TracerProvider: {e}")
