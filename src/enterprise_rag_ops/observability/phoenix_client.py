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

        # Strip OTLP path suffix if present for the Phoenix client base_url
        base_url = endpoint
        if base_url.endswith("/v1/traces"):
            base_url = base_url[:-10]

        # Resolve credentials from env only (Q4)
        api_key = os.environ.get("PHOENIX_API_KEY")

        # Register the TracerProvider (FR-3)
        self.provider = register(
            project_name=project,
            endpoint=endpoint,
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
            # Catch errors in case the project doesn't exist yet or is 'default' (undeletable)
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
