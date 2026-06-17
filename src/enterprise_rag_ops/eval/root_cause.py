"""Per-fact root-cause attribution — the shared leaf predicate (FR-1, FR-2, FR-4).

Why None-vs-non-None is the signal (NOT a set intersection): sprint-8/phase-1's FR-5
hallucination guard collapses any `FactVerdict.supporting_doc_id` not in the judge's
retrieved set to `None` *before* persistence, and that retrieved set is provably equal
to the persisted `EvalRecord.retrieval_ranked_ids` (same `chunk_hits` source, same
doc-level dedup). So on a persisted record every `supporting_doc_id` is either `None`
or already a member of `retrieval_ranked_ids` — a non-None intersection is tautological.

For a FAILED fact (`verdict in {"absent", "contradicted"}`):
  - `supporting_doc_id is None`     -> retrieval_gap  (no retrieved doc substantiates
                                       the fact; evidence never reached the generator)
  - `supporting_doc_id` is present  -> generation_gap (the evidence WAS retrieved; the
                                       generator failed to use it)

A defensive explicit membership check (FR-4) is kept so the predicate stays correct if
the FR-5 guard is ever relaxed. Pure leaf: no I/O, no network, imports only eval.schema
and eval.records — never runner / report / failure_taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.schema import FactVerdict

FAILED_VERDICTS: frozenset[str] = frozenset({"absent", "contradicted"})

FactGap = Literal["retrieval_gap", "generation_gap"]


def classify_fact_gap(
    fact_verdict: FactVerdict,
    retrieval_ranked_ids: list[str],
) -> FactGap | None:
    """Classify one fact verdict into a root-cause gap label (FR-1, FR-4).

    Returns:
        None              when verdict == "present" (the fact is not a failure).
        "retrieval_gap"   when the fact failed AND supporting_doc_id is None, or
                          (defensively, FR-4) supporting_doc_id is not in
                          retrieval_ranked_ids.
        "generation_gap"  when the fact failed AND supporting_doc_id is present in
                          retrieval_ranked_ids.
    """
    if fact_verdict.verdict not in FAILED_VERDICTS:
        return None
    doc_id = fact_verdict.supporting_doc_id
    if doc_id is None or doc_id not in retrieval_ranked_ids:
        return "retrieval_gap"
    return "generation_gap"


@dataclass(frozen=True, slots=True)
class RootCauseRollup:
    """Per-record root-cause counts (FR-2).

    `has_per_fact` distinguishes "no per-fact evidence" (record.per_fact is None ->
    has_per_fact=False, the degraded case the report maps to N/A) from "data present,
    zero gaps" (has_per_fact=True with all counts 0 -> 0.0%). This preserves the
    null-vs-absent distinction (phase-1 AC-7 / FR-6).

    `no_failed_facts` is True iff per-fact evidence exists but zero facts failed. It is
    False whenever `has_per_fact=False` (the degraded case — the flag is meaningless
    there), so `has_per_fact` is the sole discriminator between "degraded" and "some
    facts failed"; both carry `no_failed_facts=False`. The report does not read this
    flag — it re-derives "zero gaps" from `retrieval_gap + generation_gap == 0` — but it
    is kept on the rollup for a future per-record root-cause display.
    """

    retrieval_gap: int = 0
    generation_gap: int = 0
    no_failed_facts: bool = False
    has_per_fact: bool = True

    @property
    def total_failed(self) -> int:
        """Failed facts with an assigned gap (retrieval_gap + generation_gap)."""
        return self.retrieval_gap + self.generation_gap


def rollup(record: EvalRecord) -> RootCauseRollup:
    """Apply `classify_fact_gap` across `record.per_fact` (FR-2).

    Graceful degradation (FR-2 / NFR-1): when record.per_fact is None, returns a rollup
    with has_per_fact=False and zero counts — distinct from "zero gaps" — never raises.
    """
    if record.per_fact is None:
        return RootCauseRollup(has_per_fact=False)

    retrieval = 0
    generation = 0
    for fv in record.per_fact:
        gap = classify_fact_gap(fv, record.retrieval_ranked_ids)
        if gap == "retrieval_gap":
            retrieval += 1
        elif gap == "generation_gap":
            generation += 1
    return RootCauseRollup(
        retrieval_gap=retrieval,
        generation_gap=generation,
        no_failed_facts=(retrieval == 0 and generation == 0),
        has_per_fact=True,
    )
