"""`rag-index` — build the three persisted retrieval artifacts.

The entrypoint behind `make build-index` and `make rebuild-index`. Mirrors
`ingest/cli.py` in shape: argparse → orchestrate → stdlib logging at INFO.
"""

from __future__ import annotations

import argparse
import logging

from enterprise_rag_ops.retrieval import pipeline


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success."""
    parser = argparse.ArgumentParser(
        prog="rag-index",
        description="Build BM25 + dense + LanceDB retrieval indices from data/processed/corpus.jsonl.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete existing artifacts and rebuild (used by `make rebuild-index`)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline.build_index(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
