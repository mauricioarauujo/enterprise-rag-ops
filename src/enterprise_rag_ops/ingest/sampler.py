"""Deterministic stratified subsetting of the corpus.

For each source type, the subset is the first `docs_per_source` documents in
ascending `id` order — no RNG, so the same revision and `docs_per_source` always
yield the same subset (NFR-1). Memory stays bounded: each per-source bucket is
trimmed back to `docs_per_source` once it grows past a small cap, so peak memory
is proportional to `docs_per_source x source_count`, not the 512K-doc corpus
(NFR-2).
"""

from __future__ import annotations

from collections.abc import Iterable

from enterprise_rag_ops.ingest.schema import Document


def _trim(bucket: list[Document], keep: int) -> None:
    """Sort `bucket` by document id in place and drop all but the first `keep`."""
    bucket.sort(key=lambda doc: doc.id)
    del bucket[keep:]


def stratified_sample(documents: Iterable[Document], docs_per_source: int) -> list[Document]:
    """Return the first `docs_per_source` documents per source type, by sorted id.

    The result is ordered by source type, then by document id — a total order, so
    serialization downstream is deterministic. A source with fewer than
    `docs_per_source` documents contributes all of them.
    """
    if docs_per_source < 1:
        raise ValueError(f"docs_per_source must be >= 1, got {docs_per_source}")

    # Trim a bucket once it reaches twice the target; keeps memory bounded while
    # amortizing the sort cost across the stream.
    cap = docs_per_source * 2
    buckets: dict[str, list[Document]] = {}

    for doc in documents:
        bucket = buckets.setdefault(doc.source_type, [])
        bucket.append(doc)
        if len(bucket) >= cap:
            _trim(bucket, docs_per_source)

    sample: list[Document] = []
    for source_type in sorted(buckets):
        bucket = buckets[source_type]
        _trim(bucket, docs_per_source)
        sample.extend(bucket)
    return sample
