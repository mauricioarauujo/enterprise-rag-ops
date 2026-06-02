"""Orchestrator for replaying evaluation records into Phoenix traces (FR-2, FR-4, FR-5)."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.observability.attributes import build_score_rows, build_span_attrs
from enterprise_rag_ops.observability.phoenix_client import ScoreSink

logger = logging.getLogger("enterprise_rag_ops.observability.exporter")


@dataclass
class ReplaySummary:
    """Summary of the replay execution (FR-2)."""

    records_parsed: int
    traces_exported: int
    scores_logged: int


def replay_jsonl(
    path: str | Path,
    sink: ScoreSink,
    *,
    project: str,
    dry_run: bool = False,
    doc_lookup: Mapping[str, str] | None = None,
    question_lookup: Mapping[str, str] | None = None,
) -> ReplaySummary:
    """Read a results JSONL file and export trace span trees and scores to Phoenix (FR-2, FR-4, FR-5).

    Args:
        path: Path to the evaluation results JSONL file.
        sink: The ScoreSink implementation to write to.
        project: Target project name in Phoenix.
        dry_run: If True, parses and validates records without exporting them (FR-11).
        doc_lookup: Optional mapping of doc_id to content text (FR-3).
        question_lookup: Optional mapping of question_id to question text. When provided,
            the chain span gets input.value = question_lookup[question_id] (Phase 17 / FR-5).

    Returns:
        ReplaySummary: Counts of processed records and telemetry.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Results file not found at: {path}")

    # Parse and validate records first (for dry-run and early error detection)
    records: list[EvalRecord] = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                record = EvalRecord.model_validate_json(line_str)
                records.append(record)
            except Exception as e:
                logger.error(f"Error parsing JSONL line {line_num}: {e}")
                raise

    records_count = len(records)
    logger.info(f"Successfully parsed {records_count} records from {path}")

    if dry_run:
        logger.info(f"[DRY RUN] Would export {records_count} traces to project '{project}'")
        return ReplaySummary(
            records_parsed=records_count,
            traces_exported=0,
            scores_logged=0,
        )

    # 1. Reset the target project before ingestion for idempotency (FR-4)
    sink.reset_project(project)

    # 2. Replay traces and collect span IDs
    all_scores: dict[str, list[dict[str, Any]]] = {}
    traces_exported = 0

    for record in records:
        span_attrs = build_span_attrs(record)
        if doc_lookup is not None:
            for i, doc_id in enumerate(record.retrieval_ranked_ids):
                if doc_id in doc_lookup:
                    span_attrs["retriever"][f"retrieval.documents.{i}.document.content"] = (
                        doc_lookup[doc_id]
                    )
                else:
                    logger.warning(
                        "doc_id %r in retrieval_ranked_ids not found in corpus map; "
                        "omitting .content for retrieval.documents.%d",
                        doc_id,
                        i,
                    )
        if question_lookup is not None:
            if record.question_id in question_lookup:
                span_attrs["chain"]["input.value"] = question_lookup[record.question_id]
                span_attrs["chain"]["input.mime_type"] = "text/plain"
            else:
                logger.warning(
                    "question_id %r not found in question map; omitting input.value on chain span",
                    record.question_id,
                )
        span_ids: dict[str, str] = {}

        # Root chain span (name is the question ID)
        with sink.start_span(
            name=record.question_id,
            openinference_span_kind="chain",
            attributes=span_attrs["chain"],
        ) as chain_span:
            # Capture the in-process span ID as 16-char hex string (FR-4)
            span_ids["chain"] = f"{chain_span.get_span_context().span_id:016x}"

            # Child retriever span
            with sink.start_span(
                name="retriever",
                openinference_span_kind="retriever",
                attributes=span_attrs["retriever"],
            ) as retriever_span:
                span_ids["retriever"] = f"{retriever_span.get_span_context().span_id:016x}"

            # Child generation span
            with sink.start_span(
                name="generation",
                openinference_span_kind="llm",
                attributes=span_attrs["generation"],
            ) as gen_span:
                span_ids["generation"] = f"{gen_span.get_span_context().span_id:016x}"

            # Child judge span
            with sink.start_span(
                name="judge",
                openinference_span_kind="llm",
                attributes=span_attrs["judge"],
            ) as judge_span:
                span_ids["judge"] = f"{judge_span.get_span_context().span_id:016x}"

        traces_exported += 1

        # Build offline score rows using the captured span IDs (FR-5)
        scores = build_score_rows(record, span_ids)
        for metric, rows in scores.items():
            all_scores.setdefault(metric, []).extend(rows)

    # 3. Flush trace spans to ensure they are available in Phoenix before adding annotations
    sink.flush()

    # 4. Log the scores in bulk (FR-5)
    sink.log_scores(all_scores)

    # Final flush to ensure everything is written
    sink.flush()

    scores_count = sum(len(rows) for rows in all_scores.values())
    logger.info(f"Replay complete: {traces_exported} traces exported, {scores_count} scores logged")

    return ReplaySummary(
        records_parsed=records_count,
        traces_exported=traces_exported,
        scores_logged=scores_count,
    )
