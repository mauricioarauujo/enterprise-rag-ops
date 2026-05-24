# Judge Determinism Without Multi-Sample

> **Purpose**: How `strict: true` + a closed discrete `Literal` vocabulary provides
> sufficient reproducibility for per-fact judging, and when to escalate to multi-sample.
> **Confidence**: HIGH (codebase) — MEDIUM (external literature: multi-sample escalation
> threshold not formally benchmarked for this schema)
> **MCP Validated**: 2026-05-24

## Overview

LLM judge outputs are non-deterministic by default: the same prompt can yield
different verdicts across runs. Two strategies exist to counter this:

1. **Constrain the output space** — use `strict: true` structured output with a
   small, closed `Literal` vocabulary so the model has fewer degrees of freedom.
2. **Sample multiple times and aggregate** — majority-vote over N samples.

This codebase uses strategy 1 only (ADR-0001 decision Q1). Strategy 2 is deferred
as an escalation path, not a default.

## How Determinism Is Achieved Here

Three mechanisms work together:

**Closed discrete vocabulary.** `FactVerdict.verdict` is exactly
`Literal["present", "absent", "contradicted"]` — three options, no free-form text.
`CitationVerdict.verdict` is `Literal["supported", "unsupported"]` — two options.
The LLM cannot emit a continuous score or a synonym.

**`strict: true` structured output.** The OpenAI API enforces the schema server-side
before the response is returned. Extra fields are rejected; the closed `Literal`
constraint is enforced at decode time.

**Defensive Pydantic re-validation.** Even after `strict` mode, the returned JSON is
re-validated through `_LLMJudgeVerdict.model_validate_json(raw)`. Any drift surfaces
as a typed `ValidationError` rather than a silent wrong value.

**No explicit temperature.** GPT-5-class models reject an explicit `temperature`
parameter. Reproducibility rests on the schema constraints, not temperature pinning.
This matches the `OpenAIGenerator` constraint (ADR-0003).

## When to Escalate to Multi-Sample

Multi-sample majority-vote is warranted when anchor cases — hand-labeled verdicts
known to be correct — show observable drift across runs on the single-call path.
The discrete vocabulary makes per-verdict disagreement rate the right metric
(not continuous score variance).

```python
# Escalation signal: run the same question N times, check verdict agreement
from collections import Counter
verdicts = [judge.judge(q, a, facts, docs).per_fact for _ in range(N)]
for i, fact in enumerate(facts):
    outcomes = Counter(v[i].verdict for v in verdicts)
    if outcomes.most_common(1)[0][1] < N * 0.8:
        print(f"Fact {i} shows drift: {outcomes}")
```

ADR-0001 defers multi-sample to this escalation path only; the cost of N× calls
per question (for a 500-question benchmark) is the primary reason.

## Aggregation Is Separately Deterministic

`aggregate(per_fact, per_citation)` is a pure Python function with no randomness:
identical verdict lists always produce byte-identical floats. The non-determinism
lives only in the LLM call; once the verdict lists are fixed, the three metrics are
fixed.

## Conflict Flag — Temperature and Reproducibility

Some LLM-as-judge literature recommends `temperature=0` for reproducibility.
This codebase cannot follow that advice for GPT-5-class models (they reject an
explicit temperature). The mitigation is the schema constraint approach above.

**CONFLICT (LOW):** External literature defaults to `temperature=0`; codebase uses
schema-constraint approach. The two are not contradictory — schema constraints are
strictly stronger for discrete verdicts — but a future model that accepts temperature
should set `temperature=0` as an additional guard.

## Related

- [schema-as-ssot.md](schema-as-ssot.md)
- [../patterns/per-fact-judge-call.md](../patterns/per-fact-judge-call.md)
- `eval/openai_judge.py`, `eval/schema.py`
- `docs/adr/0001-eval-framework.md` § Decision (determinism row)
