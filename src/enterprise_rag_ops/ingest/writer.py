"""Deterministic JSON Lines serialization of the corpus.

Output is byte-identical across runs for the same input (NFR-1): keys are sorted,
no timestamps or run-specific data are written, and the input order is fixed by
the sampler.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from enterprise_rag_ops.ingest.schema import Document


def write_corpus(documents: Iterable[Document], path: Path) -> int:
    """Write `documents` to `path` as JSON Lines; return the number written.

    Each line is one `Document` serialized with sorted keys. The parent directory
    is created if absent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for doc in documents:
            handle.write(json.dumps(doc.model_dump(), sort_keys=True, ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def read_corpus(path: Path) -> Iterator[Document]:
    """Yield `Document` objects from a JSON Lines corpus file.

    Reads from local disk only — no network — so it is safe inside the offline
    `check-data` smoke test (NFR-3).
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield Document.model_validate_json(line)
