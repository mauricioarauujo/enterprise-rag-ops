"""Operational eval metrics over already-classified records (sprint-7/phase-3, FR-3).

`cost_per_correct` is the sprint-7 routing verdict's headline figure: of the dollars a
system spends *generating* answers, how many buy a *correct* one? It is the deployment-cost
lens on the cost/quality trade-off — judge cost is excluded because it is eval overhead,
identical across systems, and not something you pay in production (BRAINSTORM Tension 3).

Pure arithmetic over classified `EvalRecord`s; no I/O, no LLM API (so its tests are
cassette-free — ADR-0006 applies only to LLM-touching code). See the `rag-eval`
cost-accounting KB, which forward-references this metric as the phase-3 deliverable.
"""

from __future__ import annotations

from collections.abc import Iterable

from enterprise_rag_ops.eval.records import EvalRecord

# The classifier's "correct" label (FailureMode.CORRECT == "correct"); the correctness gate
# for the head-to-head denominator (OQ-4: failure_mode == "correct" is the Must path).
CORRECT = "correct"


def compute_cost_per_correct(records: Iterable[EvalRecord]) -> float | None:
    """Generation cost per correct answer for one system's records (FR-3).

    ``cost_per_correct = sum(generation.cost_usd) / count(failure_mode == "correct")``

    - **Numerator: generation cost only** (``EvalRecord.generation.cost_usd``) — the
      router-manufactured combined cost for router rows, the single-call cost for baselines.
      Judge cost (``EvalRecord.judge.cost_usd``) is never read.
    - **Denominator:** count of records whose ``failure_mode == "correct"``.
    - A ``None`` cost summand contributes ``0.0`` (the runner's ``(x or 0.0)`` convention).
    - **Returns ``None`` when the denominator is 0** (zero correct → undefined), matching the
      harness ``None``-on-empty-denominator convention.

    The caller groups records by system *before* calling — this operates on one system's
    records and assumes no system field beyond the cost it sums.
    """
    materialized = list(records)
    numerator = sum((r.generation.cost_usd or 0.0) for r in materialized)
    denominator = sum(1 for r in materialized if r.failure_mode == CORRECT)
    if denominator == 0:
        return None
    return numerator / denominator
