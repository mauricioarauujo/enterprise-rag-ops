"""`rag-ingest` — fetch EnterpriseRAG-Bench and write the stratified corpus.

Orchestrates loader -> adapters -> sampler -> writer and logs per-source counts.
This is the entrypoint behind `make download-data`.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from enterprise_rag_ops.ingest import config
from enterprise_rag_ops.ingest.adapters import get_adapter
from enterprise_rag_ops.ingest.loader import stream_documents
from enterprise_rag_ops.ingest.sampler import stratified_sample
from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.ingest.writer import write_corpus

logger = logging.getLogger("enterprise_rag_ops.ingest")


def adapt_records(raw_records: Iterator[dict], skipped: Counter) -> Iterator[Document]:
    """Route each raw record through its source-type adapter.

    Records that fail `Document` validation — the corpus contains some with empty
    `content` — are dropped and tallied per source type in `skipped` rather than
    aborting the run. An unknown `source_type` still raises (FR-3): a missing
    adapter is a code gap, not a data-quality issue.
    """
    for raw in raw_records:
        adapter = get_adapter(raw["source_type"])
        try:
            yield adapter(raw)
        except ValidationError:
            skipped[raw["source_type"]] += 1


def run(docs_per_source: int, output: Path, revision: str) -> int:
    """Run the full ingest pipeline; return the number of documents written."""
    logger.info(
        "Ingesting %s @ %s (config=%s, docs_per_source=%d)",
        config.DATASET_ID,
        revision,
        config.DOCUMENTS_CONFIG,
        docs_per_source,
    )
    skipped: Counter = Counter()
    documents = adapt_records(stream_documents(revision=revision), skipped)
    sample = stratified_sample(documents, docs_per_source)

    counts = Counter(doc.source_type for doc in sample)
    for source_type in sorted(counts):
        logger.info("  %-14s %d documents", source_type, counts[source_type])

    if skipped:
        logger.warning(
            "Skipped %d records that failed validation (per source: %s)",
            sum(skipped.values()),
            dict(sorted(skipped.items())),
        )

    written = write_corpus(sample, output)
    logger.info("Wrote %d documents to %s", written, output)
    return written


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for `rag-ingest` / `make download-data`."""
    parser = argparse.ArgumentParser(
        prog="rag-ingest",
        description="Fetch EnterpriseRAG-Bench and write a stratified corpus subset.",
    )
    parser.add_argument(
        "--docs-per-source",
        type=int,
        default=config.DEFAULT_DOCS_PER_SOURCE,
        help="documents to keep per source type (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=config.CORPUS_PATH,
        help="output JSONL path (default: %(default)s)",
    )
    parser.add_argument(
        "--revision",
        default=config.DATASET_REVISION,
        help="pinned HF dataset revision SHA (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(args.docs_per_source, args.output, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
