"""Command-line interface for replaying and exporting evaluation traces (FR-6, FR-11).

Provides the `rag-export-traces` CLI tool.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from enterprise_rag_ops.eval.questions import load_questions
from enterprise_rag_ops.ingest import config
from enterprise_rag_ops.ingest.writer import read_corpus
from enterprise_rag_ops.observability.exporter import replay_jsonl
from enterprise_rag_ops.observability.phoenix_client import PhoenixScoreSink, ScoreSink
from enterprise_rag_ops.retrieval.config import CORPUS_PATH

logger = logging.getLogger("enterprise_rag_ops.observability.cli")


class NoOpScoreSink(ScoreSink):
    """A no-op ScoreSink implementation for dry-runs (FR-11)."""

    def reset_project(self, project: str) -> None:
        pass

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
        class DummySpanContext:
            @property
            def span_id(self) -> int:
                return 1

        class DummySpan:
            def get_span_context(self) -> DummySpanContext:
                return DummySpanContext()

        yield DummySpan()

    def log_scores(self, rows_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        pass

    def flush(self) -> None:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-export-traces",
        description="Replay and export evaluation records as OpenTelemetry traces to Arize Phoenix.",
    )
    parser.add_argument(
        "--results",
        default="results/baseline.jsonl",
        help="Path to the JSONL evaluation results file (default: results/baseline.jsonl).",
    )
    parser.add_argument(
        "--endpoint",
        help="Phoenix collector endpoint. Precedence: flag > PHOENIX_COLLECTOR_ENDPOINT > http://localhost:6006.",
    )
    parser.add_argument(
        "--project",
        default="enterprise-rag-eval",
        help="Name of the target Phoenix project (default: enterprise-rag-eval).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the JSONL file without exporting to Phoenix.",
    )
    parser.add_argument(
        "--enrich-from-index",
        action="store_true",
        help="Hydrate retrieval.documents.{i}.document.content on retriever spans from corpus.jsonl (opt-in; default off).",
    )
    parser.add_argument(
        "--corpus",
        default=str(CORPUS_PATH),
        help="Path to corpus.jsonl for --enrich-from-index (default: CORPUS_PATH).",
    )
    parser.add_argument(
        "--enrich-from-questions",
        action="store_true",
        help="Hydrate input.value on chain spans with the gold question text from load_questions (opt-in; default off).",
    )
    parser.add_argument(
        "--questions-revision",
        default=config.DATASET_REVISION,
        help=f"Dataset revision SHA for the gold question map (default: {config.DATASET_REVISION}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints errors to stderr (FR-6, FR-11)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Resolve endpoint precedence (Q4 / FR-6)
    endpoint = args.endpoint
    if not endpoint:
        endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")

    results_path = Path(args.results)

    logger.info(f"Replaying results from: {results_path}")
    logger.info(f"Target Phoenix Project: {args.project}")
    if not args.dry_run:
        logger.info(f"Phoenix Endpoint: {endpoint}")

    try:
        if args.dry_run:
            sink: ScoreSink = NoOpScoreSink()
        else:
            sink = PhoenixScoreSink(project=args.project, endpoint=endpoint)

        doc_lookup = None
        if args.enrich_from_index and not args.dry_run:
            doc_lookup = {doc.id: doc.text for doc in read_corpus(Path(args.corpus))}

        question_lookup = None
        if args.enrich_from_questions and not args.dry_run:
            question_lookup = {
                q.question_id: q.question for q in load_questions(revision=args.questions_revision)
            }

        summary = replay_jsonl(
            path=results_path,
            sink=sink,
            project=args.project,
            dry_run=args.dry_run,
            doc_lookup=doc_lookup,
            question_lookup=question_lookup,
        )

        if args.dry_run:
            print(f"Dry run complete. Validated {summary.records_parsed} records successfully.")
        else:
            print(
                f"Export complete. Parsed {summary.records_parsed} records, "
                f"exported {summary.traces_exported} traces, logged {summary.scores_logged} scores."
            )

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Export failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
