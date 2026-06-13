"""Routing evaluation head-to-head — sprint-7/phase-3 (FR-4, FR-5, FR-9).

Reads the classified combined-sweep JSONL (the router + the three single-model baselines,
all on the same questions) and prints the cost-per-correct head-to-head table that the
routing verdict rests on. Pure pandas/json — NO live API (NFR-3); deterministic given a
fixed JSONL.

Fairness guard (FR-5): the cost-per-correct comparison is only fair if every system saw the
SAME questions. This asserts that (raises, does not warn) before computing anything.

Inputs : results/routing-eval.jsonl (classified — run `make classify RESULTS_FILE=...` first)
Outputs: stdout head-to-head table; docs/analysis/routing-cost-quality.png (FR-9 scatter)

Run (after the sweep + classify):
    uv run python scripts/routing_evaluation.py
    uv run python scripts/routing_evaluation.py results/routing-eval-dev.jsonl   # dev (FR-10/AC-10)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — write a PNG, no display
import matplotlib.pyplot as plt

from enterprise_rag_ops.eval.metrics import CORRECT, compute_cost_per_correct
from enterprise_rag_ops.eval.records import EvalRecord

RESULTS_PATH = Path("results/routing-eval.jsonl")
PLOT_PATH = Path("docs/analysis/routing-cost-quality.png")


def _load(path: Path) -> list[EvalRecord]:
    """Load every JSONL row as an EvalRecord; fail clearly if classify has not run."""
    records = [EvalRecord.model_validate_json(line) for line in path.open() if line.strip()]
    missing = sum(1 for r in records if r.failure_mode is None)
    if missing:
        raise SystemExit(
            f"{missing} rows have failure_mode=None — run "
            f"`make classify RESULTS_FILE={path}` first."
        )
    return records


def _assert_same_questions(by_system: dict[str, list[EvalRecord]]) -> None:
    """FR-5: every system must share the same question_id set, or the cost-per-correct
    head-to-head is not a fair comparison. Raise (not warn) on any mismatch."""
    sets = {sys: {r.question_id for r in recs} for sys, recs in by_system.items()}
    if len({frozenset(s) for s in sets.values()}) > 1:
        reference = next(iter(sets.values()))
        details = ", ".join(
            f"{sys} (Δ{len(s.symmetric_difference(reference))})" for sys, s in sets.items()
        )
        raise SystemExit(
            "Overlap guard (FR-5): systems do not share the same question_id set — the "
            f"cost-per-correct comparison would be unfair. Per-system sizes: {details}. "
            "If the full sweep halted on the cost ceiling, re-run it under a higher ceiling."
        )


def _table_rows(by_system: dict[str, list[EvalRecord]]) -> list[dict[str, object]]:
    rows = []
    for system in sorted(by_system):
        recs = by_system[system]
        cpc = compute_cost_per_correct(recs)
        recalls = [r.fact_recall for r in recs if r.fact_recall is not None]
        rows.append(
            {
                "system": system,
                "cost_per_correct": cpc,
                "fact_recall": (sum(recalls) / len(recalls)) if recalls else None,
                "total_gen_cost": sum((r.generation.cost_usd or 0.0) for r in recs),
                "n_correct": sum(1 for r in recs if r.failure_mode == CORRECT),
            }
        )
    return rows


def _fmt(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _print_table(rows: list[dict[str, object]]) -> None:
    cols = ["system", "cost_per_correct", "fact_recall", "total_gen_cost", "n_correct"]
    header = " | ".join(cols)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(_fmt(row[c]) for c in cols))


def _write_scatter(rows: list[dict[str, object]]) -> None:
    """FR-9: quality-at-cost scatter — fact_recall (y) vs cost_per_correct (x), one point per
    system. Systems with cost_per_correct=None (zero correct) are skipped."""
    plottable = [
        r for r in rows if r["cost_per_correct"] is not None and r["fact_recall"] is not None
    ]
    if not plottable:
        return
    PLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 5))
    for row in plottable:
        x, y = row["cost_per_correct"], row["fact_recall"]
        ax.scatter(x, y, s=80)
        ax.annotate(str(row["system"]), (x, y), textcoords="offset points", xytext=(6, 4))
    ax.set_xlabel("cost per correct answer (USD, generation only)")
    ax.set_ylabel("mean fact recall")
    ax.set_title("Quality at cost — router vs single-model baselines")
    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=120)
    plt.close(fig)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else RESULTS_PATH
    records = _load(path)

    by_system: dict[str, list[EvalRecord]] = defaultdict(list)
    for r in records:
        by_system[r.gen_ai.system].append(r)

    _assert_same_questions(by_system)

    rows = _table_rows(by_system)
    _print_table(rows)
    _write_scatter(rows)
    print(f"\nwrote {PLOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
