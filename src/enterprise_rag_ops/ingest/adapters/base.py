"""Adapter registry: maps a raw dataset record to a canonical `Document`.

An adapter is a callable ``(raw: dict) -> Document``. Adapters are looked up by
`source_type`; an unregistered source type raises `UnknownSourceTypeError` so a
new source in a future dataset revision fails ingest loudly (FR-3).
"""

from __future__ import annotations

from collections.abc import Callable

from enterprise_rag_ops.ingest.schema import Document, UnknownSourceTypeError

Adapter = Callable[[dict], Document]

REGISTRY: dict[str, Adapter] = {}


def register(source_type: str, adapter: Adapter) -> None:
    """Register `adapter` as the handler for `source_type`."""
    REGISTRY[source_type] = adapter


def get_adapter(source_type: str) -> Adapter:
    """Return the adapter for `source_type`, or raise `UnknownSourceTypeError`."""
    try:
        return REGISTRY[source_type]
    except KeyError:
        raise UnknownSourceTypeError(source_type) from None
