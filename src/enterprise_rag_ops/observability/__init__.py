"""Observability module for enterprise-rag-ops.

This package acts as the vendor boundary and tool-swap seam (NFR-3). All Phoenix and
OpenTelemetry specifics are encapsulated within this module (specifically phoenix_client.py)
to allow easy replacement with other tools (e.g. Langfuse, Tempo/Jaeger) in the future.
"""

from enterprise_rag_ops.observability.exporter import replay_jsonl

__all__ = ["replay_jsonl"]
