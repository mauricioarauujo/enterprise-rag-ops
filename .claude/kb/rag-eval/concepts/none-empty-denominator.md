# The `None` Empty-Denominator Convention

> **Purpose**: Why empty-denominator eval ratios yield `None` rather than `0.0` or
> `1.0`, and what downstream code must do with `None` values.
> **Confidence**: HIGH (codebase — explicitly designed and tested)
> **MCP Validated**: 2026-05-24

## Overview

Three metrics are computed from the two judge verdict lists:
`fact_recall`, `fact_precision`, and `faithfulness_ratio`. Each has a denominator that
can be zero: an abstention produces no facts and no citations. The convention is:

**Empty denominator → `None` ("not applicable"), never `0.0` or `1.0`.**

This is an explicit design decision (ADR-0001, orchestrator decision 2), not a
default. Getting it wrong produces misleading dataset-wide averages.

## Why Not `0.0`

An abstention — an answer that says "I don't know" and cites nothing — has
`per_fact = []` and `per_citation = []`. Setting `fact_recall = 0.0` would make it
look as bad as an answer that contradicted every fact. Setting `faithfulness_ratio =
1.0` would make it look perfectly faithful. Neither is correct: the question is
simply unanswerable from the evidence, and the metric is not applicable.

## The Three Rules (from `eval/aggregate.py`)

```python
# fact_recall = |present| / |facts|
fact_recall = n_present / len(per_fact) if per_fact else None

# fact_precision = |present| / (|present| + |contradicted|)
# None when no present or contradicted facts (e.g. all absent)
precision_denom = n_present + n_contradicted
fact_precision = n_present / precision_denom if precision_denom else None

# faithfulness_ratio = |supported| / |citations|
faithfulness_ratio = n_supported / len(per_citation) if per_citation else None
```

Note: `fact_precision` has a second edge case beyond empty `per_fact` — an answer
that omits every fact (all `absent`) has `n_present = 0` and `n_contradicted = 0`,
making the denominator 0. `None` is returned: "there are no claims to evaluate for
precision."

## Full Abstention

An answer with no facts supplied and no citations produces:

```python
(fact_recall, fact_precision, faithfulness_ratio) == (None, None, None)
```

This is "not applicable", not "perfectly faithful" or "perfectly wrong".

## Downstream Contract

Any code that aggregates scores across questions (Phase 6 runner) must:

```python
# Correct: exclude None values
scores = [v.fact_recall for v in verdicts if v.fact_recall is not None]
mean_recall = sum(scores) / len(scores) if scores else None

# Wrong: coercing None to 0 before averaging
mean_recall = sum(v.fact_recall or 0 for v in verdicts) / len(verdicts)
```

The contract is stated in `JudgeVerdict`'s docstring and in ADR-0001 consequences.
Phase 6 owns the averaging; Phase 4 only produces the `None`.

## `JudgeVerdict` field types

```python
fact_recall: float | None = Field(default=None, ...)
fact_precision: float | None = Field(default=None, ...)
faithfulness_ratio: float | None = Field(default=None, ...)
```

The `default=None` lets `JudgeVerdict` be constructed from the two lists alone before
`aggregate()` is called — the public model is constructible from LLM output before
the Python aggregation step runs.

## Related

- [../patterns/per-fact-judge-call.md](../patterns/per-fact-judge-call.md)
- `eval/aggregate.py`, `eval/schema.py`
- `tests/eval/test_aggregate.py`
- `docs/adr/0001-eval-framework.md` § Consequences
