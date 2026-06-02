"""Pure core logic for RAG evaluation results triage (groupby-aggregate failure mode clusters).

Provides dataclasses and computation functions to group classified EvalRecords by
failure mode and category, sorting clusters by frequency.
"""

from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag_ops.eval.questions import Question
from enterprise_rag_ops.eval.records import EvalRecord

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class TriageCluster:
    """A cluster of evaluation records sharing a failure mode and question category."""

    failure_mode: str
    category: str
    count: int
    rate: float
    representative_question_id: str
    representative_question_text: str
    models_seen: list[str]


@dataclass(frozen=True, slots=True)
class TriageReport:
    """The complete aggregated triage report containing clusters and metadata."""

    schema_version: str
    total_records: int
    models_seen: list[str]
    dominant_cluster: TriageCluster | None
    clusters: list[TriageCluster]


def compute_triage(
    records: list[EvalRecord],
    gold: dict[str, Question],
) -> TriageReport:
    """Pure analysis function grouping records by (failure_mode, category).

    Args:
        records: List of already-classified EvalRecord objects.
        gold: Dictionary mapping question_id to gold Question objects.

    Returns:
        A deterministic TriageReport containing clusters sorted by size.

    Raises:
        ValueError: If any record has `failure_mode is None`.
    """
    # 1. Fail-fast validation
    for r in records:
        if r.failure_mode is None:
            raise ValueError(
                f"Record {r.question_id!r} is unclassified (failure_mode is None); run rag-classify first."
            )

    total = len(records)

    # 2. Empty input handling
    if total == 0:
        return TriageReport(
            schema_version=SCHEMA_VERSION,
            total_records=0,
            models_seen=[],
            dominant_cluster=None,
            clusters=[],
        )

    # 3. Grouping records by (failure_mode, category) using the record's own category
    groups: dict[tuple[str, str], list[EvalRecord]] = {}
    for r in records:
        # failure_mode is guaranteed to be str due to the fail-fast check
        key = (r.failure_mode, r.category)
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    # 4. Building clusters
    clusters: list[TriageCluster] = []
    for (fm, cat), bucket in groups.items():
        count = len(bucket)
        rate = count / total
        models_seen = sorted({r.gen_ai.request.model for r in bucket})

        # Representative is lexicographically first question_id
        rep = min(bucket, key=lambda r: r.question_id)
        rep_id = rep.question_id
        rep_text = gold[rep_id].question if rep_id in gold else ""

        clusters.append(
            TriageCluster(
                failure_mode=fm,
                category=cat,
                count=count,
                rate=rate,
                representative_question_id=rep_id,
                representative_question_text=rep_text,
                models_seen=models_seen,
            )
        )

    # 5. Sorting clusters: count desc, tiebreaker (failure_mode, category) asc
    clusters.sort(key=lambda c: (-c.count, c.failure_mode, c.category))

    # 6. Metadata and report construction
    overall_models_seen = sorted({r.gen_ai.request.model for r in records})
    dominant_cluster = clusters[0] if clusters else None

    return TriageReport(
        schema_version=SCHEMA_VERSION,
        total_records=total,
        models_seen=overall_models_seen,
        dominant_cluster=dominant_cluster,
        clusters=clusters,
    )


def _cluster_to_dict(cluster: TriageCluster) -> dict:
    """Helper to convert a TriageCluster to a dictionary with fixed key order."""
    return {
        "failure_mode": cluster.failure_mode,
        "category": cluster.category,
        "count": cluster.count,
        "rate": cluster.rate,
        "representative_question_id": cluster.representative_question_id,
        "representative_question_text": cluster.representative_question_text,
        "models_seen": cluster.models_seen,
    }


def _report_to_dict(report: TriageReport) -> dict:
    """Helper to convert a TriageReport to a dictionary with fixed key order."""
    return {
        "schema_version": report.schema_version,
        "total_records": report.total_records,
        "models_seen": report.models_seen,
        "dominant_cluster": (
            _cluster_to_dict(report.dominant_cluster)
            if report.dominant_cluster is not None
            else None
        ),
        "clusters": [_cluster_to_dict(c) for c in report.clusters],
    }
