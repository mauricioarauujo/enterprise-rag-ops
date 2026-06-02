"""Command-line interface for RAG failure aggregation and triage.

Provides the `rag-triage` CLI tool to load an existing JSONL evaluation results
file, aggregate the failure modes and categories into clusters, and write the
triage report to a JSON file atomically.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from enterprise_rag_ops.eval.questions import load_questions
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.triage import _report_to_dict, compute_triage
from enterprise_rag_ops.ingest import config

logger = logging.getLogger("enterprise_rag_ops.eval.triage_cli")


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for rag-triage."""
    parser = argparse.ArgumentParser(
        prog="rag-triage",
        description="Aggregate RAG evaluation failure modes into triage clusters.",
    )
    parser.add_argument(
        "--results",
        required=True,
        help="Path to the JSONL evaluation results file.",
    )
    parser.add_argument(
        "--output",
        default="results/triage.json",
        help="Path to write the triage report JSON file (default: results/triage.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute triage and print summary to stdout without writing any files.",
    )
    parser.add_argument(
        "--questions-revision",
        default=config.DATASET_REVISION,
        help=f"Dataset revision SHA to use for loading gold questions (default: {config.DATASET_REVISION}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints errors to stderr."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    results_path = Path(args.results)
    output_path = Path(args.output)

    try:
        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        logger.info("Loading gold questions with revision: %s", args.questions_revision)
        questions = list(load_questions(revision=args.questions_revision))
        gold = {q.question_id: q for q in questions}
        logger.info("Loaded %d gold questions.", len(gold))

        records: list[EvalRecord] = []
        with open(results_path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = EvalRecord.model_validate_json(stripped)
                except Exception as e:
                    logger.error("Failed to parse record on line %d: %s", line_no, e)
                    raise

                records.append(record)

        # Compute triage clusters and report
        report = compute_triage(records, gold)

        # Format and output results to stdout
        print("=" * 80)
        print(f"TRIAGE REPORT SUMMARY (Schema Version: {report.schema_version})")
        print("=" * 80)
        print(f"Total Records: {report.total_records}")
        print(f"Models Seen  : {', '.join(report.models_seen)}")
        print("-" * 80)
        if report.dominant_cluster:
            dom = report.dominant_cluster
            print(
                f"DOMINANT CLUSTER:\n"
                f"  Failure Mode: {dom.failure_mode}\n"
                f"  Category    : {dom.category}\n"
                f"  Count       : {dom.count} / {report.total_records} ({dom.rate:.2%})\n"
                f"  Rep QID     : {dom.representative_question_id}\n"
                f"  Rep Question: {dom.representative_question_text}"
            )
        else:
            print("DOMINANT CLUSTER: None (no records or no failures)")
        print("-" * 80)
        print(f"{'FAILURE MODE':<30} | {'CATEGORY':<20} | {'COUNT':<5} | {'RATE':<8}")
        print("-" * 80)
        for c in report.clusters:
            print(f"{c.failure_mode:<30} | {c.category:<20} | {c.count:<5} | {c.rate:.2%}")
        print("=" * 80)

        if args.dry_run:
            logger.info("Dry run requested. Write bypassed.")
            return 0

        # Atomic write to JSON
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=output_dir,
            delete=False,
            prefix=".rag-triage-tmp-",
            suffix=".json",
            encoding="utf-8",
        ) as tmp_file:
            temp_path = Path(tmp_file.name)
            try:
                # Deterministic JSON dump
                json.dump(_report_to_dict(report), tmp_file, indent=2)
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                raise

        try:
            os.replace(temp_path, output_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        logger.info("Successfully wrote triage report to %s", output_path)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
