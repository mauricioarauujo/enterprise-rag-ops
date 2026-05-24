# Per-Fact Judge Call

> **Purpose**: One structured-output call that scores a RAG answer against gold facts
> and verifies citation faithfulness — schema wiring, call, defensive re-validation,
> and pure-Python aggregation.
> **MCP Validated**: 2026-05-24

## When to Use

- Scoring a single `AnswerWithSources` against its question's `answer_facts`.
- Verifying that each cited `doc_id` actually supports the claim it was cited for.
- Any extension of the `Judge` Protocol (e.g. a `ClaudeJudge` for ADR-0005).

## Implementation

The full call lives in `eval/openai_judge.py`. The pattern has four steps:

```python
# Step 1: resolve cited docs from the retrieved chunk list
# A doc split across chunks is joined so the judge sees the whole doc.
doc_chunks: dict[str, list[str]] = defaultdict(list)
for c in retrieved_docs:
    doc_chunks[c.doc_id].append(c.text)
doc_text = {doc_id: "\n\n".join(texts) for doc_id, texts in doc_chunks.items()}
cited_docs = [
    (doc_id, doc_text.get(doc_id))          # None if not in retrieved set
    for doc_id in answer_with_sources.sources
]

# Step 2: build prompts (pure functions, no I/O)
system_prompt = build_judge_system_prompt()
user_prompt = build_judge_user_prompt(
    question=question,
    answer=answer_with_sources.answer,
    answer_facts=answer_facts,
    cited_docs=cited_docs,
)

# Step 3: single strict structured-output call
# Schema is the LLM-facing subset ONLY (no aggregate floats).
json_schema = {
    "name": "JudgeVerdict",
    "schema": _LLMJudgeVerdict.model_json_schema(),   # <-- private subset
    "strict": True,
}
response = self._client.chat.completions.create(
    model=self._model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    response_format={"type": "json_schema", "json_schema": json_schema},
)
raw = response.choices[0].message.content or ""

# Step 4: defensive re-validate, then aggregate floats, then assemble public model
llm_verdict = _LLMJudgeVerdict.model_validate_json(raw)   # ValidationError on drift
fact_recall, fact_precision, faithfulness_ratio = aggregate(
    llm_verdict.per_fact, llm_verdict.per_citation
)
return JudgeVerdict(
    per_fact=llm_verdict.per_fact,
    per_citation=llm_verdict.per_citation,
    fact_recall=fact_recall,
    fact_precision=fact_precision,
    faithfulness_ratio=faithfulness_ratio,
)
```

## Configuration

| Setting                   | Default                 | Description                                                                     |
| ------------------------- | ----------------------- | ------------------------------------------------------------------------------- |
| `RAG_JUDGE_MODEL` env var | `gpt-5-nano-2025-08-07` | Override judge model at runtime                                                 |
| `OPENAI_API_KEY` env var  | —                       | Required for `OpenAIJudge`; not for `StubJudge`                                 |
| Temperature               | model default           | GPT-5-class rejects explicit temperature; use schema constraint for determinism |

## Example Usage

```python
from enterprise_rag_ops.eval.interfaces import Judge
from enterprise_rag_ops.eval.openai_judge import OpenAIJudge
from enterprise_rag_ops.eval.stub_judge import StubJudge

# Production path (needs OPENAI_API_KEY)
judge: Judge = OpenAIJudge()

# CI / offline path (no key needed)
judge: Judge = StubJudge()

verdict = judge.judge(
    question="What is the capital of France?",
    answer_with_sources=answer,         # AnswerWithSources from the generator
    answer_facts=["Paris is the capital of France.", "France is in Europe."],
    retrieved_docs=chunks,              # list[Chunk] from the retriever
)
print(verdict.fact_recall)             # e.g. 0.5 or None
print(verdict.faithfulness_ratio)      # e.g. 0.5 or None
```

## Common Mistakes

### Wrong — feeding the full `JudgeVerdict` schema to strict mode

```python
# This includes the three floats, forcing the LLM to emit them.
# The LLM can disagree with its own verdict list.
json_schema = {
    "name": "JudgeVerdict",
    "schema": JudgeVerdict.model_json_schema(),   # BAD
    "strict": True,
}
```

### Correct — use the private LLM-facing subset

```python
json_schema = {
    "name": "JudgeVerdict",
    "schema": _LLMJudgeVerdict.model_json_schema(),   # GOOD
    "strict": True,
}
```

### Wrong — coercing `None` aggregate floats to `0` before averaging

```python
# Abstentions drag the mean down unfairly.
mean_recall = sum(v.fact_recall or 0 for v in verdicts) / len(verdicts)
```

### Correct — exclude `None` from aggregation

```python
scores = [v.fact_recall for v in verdicts if v.fact_recall is not None]
mean_recall = sum(scores) / len(scores) if scores else None
```

## See Also

- [../concepts/schema-as-ssot.md](../concepts/schema-as-ssot.md)
- [../concepts/per-doc-faithfulness.md](../concepts/per-doc-faithfulness.md)
- [../concepts/none-empty-denominator.md](../concepts/none-empty-denominator.md)
- [offline-ci-judge.md](offline-ci-judge.md)
- `eval/openai_judge.py`, `eval/prompt.py`, `eval/aggregate.py`
