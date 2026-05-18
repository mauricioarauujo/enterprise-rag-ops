"""Adapter subpackage: registers an adapter for every known source type.

Importing this package populates `REGISTRY`. All nine source types currently map
to `flat_adapter` (their raw schema is identical); the registry indirection lets
a future revision swap in a per-source adapter without touching call sites.
"""

from __future__ import annotations

from enterprise_rag_ops.ingest.adapters.base import (
    REGISTRY,
    Adapter,
    get_adapter,
    register,
)
from enterprise_rag_ops.ingest.adapters.flat import flat_adapter
from enterprise_rag_ops.ingest.config import SOURCE_TYPES

for _source_type in SOURCE_TYPES:
    register(_source_type, flat_adapter)

__all__ = ["REGISTRY", "Adapter", "flat_adapter", "get_adapter", "register"]
