from __future__ import annotations

import os
from pathlib import Path

from enterprise_rag_ops.eval.failure_taxonomy import FailureMode
from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.report import generate_report_data

RESULTS_DIR = Path("results")
PHOENIX_ENDPOINT_ENV = "PHOENIX_COLLECTOR_ENDPOINT"


def discover_results_paths(results_dir: Path = RESULTS_DIR) -> list[Path]:
    """Return sorted `*.jsonl` files in `results_dir` (FR-1).

    Default selection for the Must path. Sorted for determinism (NFR-6).
    Returns [] if the directory is absent or empty — callers render an empty-state.
    """
    if not results_dir.is_dir():
        return []
    return sorted(list(results_dir.glob("*.jsonl")))


def load_run_records(paths: list[Path]) -> list[EvalRecord]:
    """Concatenate EvalRecords parsed from one or more JSONL files (FR-1, FR-10).

    Parses each line with `EvalRecord.model_validate_json`, skipping blank lines.
    Multi-file union is plain concatenation; per-model grouping downstream keys on
    `gen_ai.request.model` (matches `generate_report_data`). Order is paths-order
    then file-order (deterministic).
    """
    records = []
    for path in paths:
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(EvalRecord.model_validate_json(line))
    return records


def summary_rows(jsonl_path: Path) -> list[dict]:
    """Per-model summary rows — DELEGATES to generate_report_data (FR-2, AC-2).

    Returns `generate_report_data(jsonl_path)["summary"]` unchanged. No metric is
    recomputed here (proves reuse, not reimplementation).
    """
    return generate_report_data(jsonl_path)["summary"]


def cost_rows(jsonl_path: Path) -> list[dict]:
    """Per-model cost rollup — DELEGATES to generate_report_data (FR-4, AC-4).

    Returns `generate_report_data(jsonl_path)["costs"]` unchanged. `total_cost=None`
    is passed through untouched; the N/A formatting is the render layer's job
    (see `format_cost` below) — never coerce None to 0.
    """
    return generate_report_data(jsonl_path)["costs"]


def failure_mode_distribution(records: list[EvalRecord]) -> dict[str, dict[str, int]]:
    """NEW pivot: counts per FailureMode label, per model (FR-3, AC-3).

    Returns {model: {failure_mode_value: count}} where keys cover ALL 5 FailureMode
    labels (zero-filled), so every model maps every label even at count 0. Reads the
    `record.failure_mode` field already on each EvalRecord (populated by rag-classify);
    records with `failure_mode is None` are skipped (unclassified). Per-model totals
    over the 5 labels equal that model's classified record count.
    """
    result = {}
    for r in records:
        if r.failure_mode is None:
            continue
        model = r.gen_ai.request.model
        if model not in result:
            result[model] = {fm.value: 0 for fm in FailureMode}
        # Verify the failure mode is known/valid
        fm_val = str(r.failure_mode)
        if fm_val in result[model]:
            result[model][fm_val] += 1
    return result


def category_failure_distribution(
    records: list[EvalRecord],
) -> dict[str, dict[str, int]]:
    """NEW pivot: category by failure-mode counts (FR-9, AC-8).

    Returns {category: {failure_mode_value: count}}, FailureMode labels zero-filled
    per category. `record.category` is the question_type carried on each EvalRecord.
    Records with `failure_mode is None` are skipped. Pure; offline-testable.
    """
    result = {}
    for r in records:
        if r.failure_mode is None:
            continue
        cat = r.category
        if cat not in result:
            result[cat] = {fm.value: 0 for fm in FailureMode}
        fm_val = str(r.failure_mode)
        if fm_val in result[cat]:
            result[cat][fm_val] += 1
    return result


def phoenix_trace_url(
    question_id: str,
    *,
    project: str = "enterprise-rag-ops",
    endpoint: str | None = None,
) -> str | None:
    """Single-source Phoenix deep-link builder (FR-11, NFR-4, AC-10).

    `endpoint` defaults to `os.environ.get(PHOENIX_ENDPOINT_ENV)`. Returns None when
    the endpoint is absent/empty (Phoenix not configured) — never a broken link.
    When set, returns a project-scoped URL built in THIS one place so a Phoenix-version
    URL change is a one-line edit. No network call (NFR-6 determinism: env-presence is
    the gate, not a live health check).
    """
    if endpoint is None:
        endpoint = os.environ.get(PHOENIX_ENDPOINT_ENV)
    if not endpoint:
        return None

    stripped = endpoint.rstrip("/")
    base_url = stripped[:-10] if stripped.endswith("/v1/traces") else stripped

    return f"{base_url}/projects/{project}"


def format_cost(total_cost: float | None) -> str:
    """Render helper: USD string or 'N/A' when None (FR-4, AC-4). Never returns '0'.

    Mirrors `eval.report._fmt`/cost formatting. Pure; lives in data.py so the N/A
    contract is unit-testable without Streamlit.
    """
    if total_cost is None:
        return "N/A"
    return f"${total_cost:.4f}"
