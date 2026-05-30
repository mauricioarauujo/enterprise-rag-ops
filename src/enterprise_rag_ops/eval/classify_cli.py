"""Command-line interface for RAG failure-mode classification (FR-7, FR-9, FR-10).

Provides the `rag-classify` CLI tool to load an existing JSONL evaluation results
file, join each record with the gold dataset question, classify its failure mode,
and update the file atomically in-place or write to a new destination.
"""

from __future__ import annotations

import argparse
import collections
import logging
import os
import sys
import tempfile
from pathlib import Path

from enterprise_rag_ops.eval.failure_taxonomy import classify
from enterprise_rag_ops.eval.questions import load_questions
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.ingest import config

logger = logging.getLogger("enterprise_rag_ops.eval.classify_cli")


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for rag-classify."""
    parser = argparse.ArgumentParser(
        prog="rag-classify",
        description="Classify RAG evaluation records into failure modes.",
    )
    parser.add_argument(
        "--results",
        required=True,
        help="Path to the JSONL evaluation results file.",
    )
    parser.add_argument(
        "--output",
        help="Path to write the tagged results. Defaults to overwriting the input results file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run classification and print the failure mode distribution without writing any files.",
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

    # Default output to results (overwrite) if not specified
    output_path_str = args.output if args.output is not None else args.results
    results_path = Path(args.results)
    output_path = Path(output_path_str)

    try:
        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        logger.info("Loading gold questions with revision: %s", args.questions_revision)
        questions = list(load_questions(revision=args.questions_revision))
        gold = {q.question_id: q for q in questions}
        logger.info("Loaded %d gold questions.", len(gold))

        records: list[EvalRecord] = []
        counter: collections.Counter[str] = collections.Counter()

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

                question = gold.get(record.question_id)
                if question is None:
                    logger.warning(
                        "question_id %s not in gold set; skipping classification",
                        record.question_id,
                    )
                else:
                    mode = classify(record, question)
                    record.failure_mode = mode.value

                counter[str(record.failure_mode)] += 1
                records.append(record)

        # Print the distribution
        print("Failure mode distribution:")
        for mode_str, count in counter.most_common():
            print(f"  {mode_str}: {count}")

        if args.dry_run:
            logger.info("Dry run requested. Write bypassed.")
            return 0

        # Atomic write: write to temp file, then rename/replace
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=output_dir,
            delete=False,
            prefix=".rag-classify-tmp-",
            suffix=".jsonl",
            encoding="utf-8",
        ) as tmp_file:
            temp_path = Path(tmp_file.name)
            try:
                for rec in records:
                    tmp_file.write(rec.model_dump_json() + "\n")
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                raise

        os.replace(temp_path, output_path)
        logger.info("Successfully wrote classified records to %s", output_path)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
