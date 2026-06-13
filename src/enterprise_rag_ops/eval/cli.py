"""Command-line interface for RAG evaluation (FR-6, FR-16).

Provides the `rag-eval` CLI tool with sub-commands:
- `run`: Runs a multi-model evaluation sweep and automatically generates reports.
- `report`: Deterministically renders HTML/Markdown reports from an existing JSONL results file.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from enterprise_rag_ops.eval.config import RunConfig
from enterprise_rag_ops.eval.report import render_report
from enterprise_rag_ops.eval.runner import run_evaluation

logger = logging.getLogger("enterprise_rag_ops.eval.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-eval",
        description="Run RAG evaluation sweeps and generate reports.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sub-command 'run'
    run_parser = subparsers.add_parser("run", help="Run evaluation sweep.")
    run_parser.add_argument(
        "--config",
        default="configs/baseline.yaml",
        help="Path to the YAML run configuration (default: configs/baseline.yaml).",
    )
    run_parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Concurrency level (default: 1).",
    )
    run_parser.add_argument(
        "--persist-bronze",
        action="store_true",
        help="Write raw request+response bronze files to data/raw_eval/.",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an interrupted run: append to the existing {run_id}.jsonl, skipping "
            "every (system, question_id) already present and (re)running only the gaps."
        ),
    )

    # Sub-command 'report'
    report_parser = subparsers.add_parser(
        "report", help="Re-render HTML/Markdown reports from JSONL results."
    )
    report_parser.add_argument(
        "--results",
        required=True,
        help="Path to the JSONL evaluation results file.",
    )
    report_parser.add_argument(
        "--output-dir",
        default="results",
        help="Directory to write rendered reports (default: results).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints errors to stderr (FR-6)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "run":
        try:
            config_path = Path(args.config)
            config = RunConfig.load_from_yaml(config_path)
            if args.persist_bronze:
                config.persist_bronze = True

            logger.info("Starting evaluation sweep with configuration: %s", config_path)
            jsonl_path = run_evaluation(config, concurrency=args.concurrency, resume=args.resume)
            logger.info("Evaluation sweep complete. Output JSONL: %s", jsonl_path)

            # Auto-render reports (Decision 3-C / AC-8)
            html_path, md_path = render_report(jsonl_path, config.output_dir)
            logger.info(
                "Reports rendered successfully:\n  HTML: %s\n  Markdown: %s", html_path, md_path
            )

        except (FileNotFoundError, RuntimeError, ValueError) as e:
            # AC-11: fail fast with clean message, no raw stack trace
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "report":
        try:
            results_path = Path(args.results)
            if not results_path.exists():
                raise FileNotFoundError(f"Results file not found: {results_path}")

            html_path, md_path = render_report(results_path, args.output_dir)
            logger.info(
                "Reports rendered successfully from existing results:\n  HTML: %s\n  Markdown: %s",
                html_path,
                md_path,
            )
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
