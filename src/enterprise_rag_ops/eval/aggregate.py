"""Pure-Python aggregation of verdict lists into the three judge floats (FR-4).

No LLM call, no I/O — given the two verdict lists, return
`(fact_recall, fact_precision, faithfulness_ratio)`. Fully deterministic (NFR-2):
identical lists yield byte-identical floats.

Empty-denominator convention = **`None`** (orchestrator decision 2): a missing
denominator is "not applicable", never silently `0.0` or `1.0`. An abstention with no
facts and no citations therefore aggregates to `(None, None, None)`. Downstream
averaging (Phase 6) must exclude `None`, not coerce it.
"""

from __future__ import annotations

from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict


def aggregate(
    per_fact: list[FactVerdict],
    per_citation: list[CitationVerdict],
) -> tuple[float | None, float | None, float | None]:
    """Compute `(fact_recall, fact_precision, faithfulness_ratio)` from verdicts.

    - `fact_recall = |present| / |facts|` — `None` when `per_fact` is empty.
    - `fact_precision = |present| / (|present| + |contradicted|)` — `None` when that
      denominator is 0 (no `present` and no `contradicted`; e.g. all `absent`).
    - `faithfulness_ratio = |supported| / |citations|` — `None` when `per_citation`
      is empty.
    """
    n_present = sum(1 for f in per_fact if f.verdict == "present")
    n_contradicted = sum(1 for f in per_fact if f.verdict == "contradicted")
    n_supported = sum(1 for c in per_citation if c.verdict == "supported")

    fact_recall = n_present / len(per_fact) if per_fact else None

    precision_denom = n_present + n_contradicted
    fact_precision = n_present / precision_denom if precision_denom else None

    faithfulness_ratio = n_supported / len(per_citation) if per_citation else None

    return fact_recall, fact_precision, faithfulness_ratio
