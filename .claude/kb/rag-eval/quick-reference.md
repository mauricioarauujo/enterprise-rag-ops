# RAG Eval — Quick Reference

## Metric Formulas

| Metric               | Formula | `None` when |
| -------------------- | ------- | ----------- | --- | --------- | --- | ----------------------- | --- | --- | ------- | --- | ------------ | ----- |
| `fact_recall`        | `       | present     | /   | facts     | `   | `per_fact` is empty     |
| `fact_precision`     | `       | present     | / ( | present   | +   | contradicted            | )`  | `   | present | +   | contradicted | == 0` |
| `faithfulness_ratio` | `       | supported   | /   | citations | `   | `per_citation` is empty |

Full abstention (no facts, no citations) → `(None, None, None)`.  
Downstream averaging must **exclude** `None`, not coerce to `0`.

## Schema Fields

| Model              | Fields                                                                            | Notes                      |
| ------------------ | --------------------------------------------------------------------------------- | -------------------------- |
| `FactVerdict`      | `fact: str`, `verdict: Literal["present","absent","contradicted"]`                | Closed (`extra="forbid"`)  |
| `CitationVerdict`  | `doc_id: str`, `verdict: Literal["supported","unsupported"]`                      | Closed (`extra="forbid"`)  |
| `_LLMJudgeVerdict` | `per_fact: list[FactVerdict]`, `per_citation: list[CitationVerdict]`              | LLM-facing only; no floats |
| `JudgeVerdict`     | above + `fact_recall`, `fact_precision`, `faithfulness_ratio` (all `float\|None`) | Public output              |

## Judge call shape

```python
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "JudgeVerdict",
        "schema": _LLMJudgeVerdict.model_json_schema(),
        "strict": True,
    },
}
```

## Prompt structure

```
System: role + rubric + _LLMJudgeVerdict JSON schema
User:   QUESTION / ANSWER UNDER JUDGMENT /
        GOLD FACTS (numbered checklist) /
        CITED DOCUMENTS (one === doc {doc_id} === block per cited doc)
```

## Env variables

| Variable          | Default                 | Purpose                                     |
| ----------------- | ----------------------- | ------------------------------------------- |
| `RAG_JUDGE_MODEL` | `gpt-5-nano-2025-08-07` | Override judge model                        |
| `OPENAI_API_KEY`  | —                       | Required for live `OpenAIJudge`; not for CI |

## File map

| Module                 | Role                                                                       |
| ---------------------- | -------------------------------------------------------------------------- |
| `eval/schema.py`       | `FactVerdict`, `CitationVerdict`, `_LLMJudgeVerdict`, `JudgeVerdict`       |
| `eval/aggregate.py`    | Pure-Python `aggregate(per_fact, per_citation) -> tuple[float\|None, ...]` |
| `eval/interfaces.py`   | `Judge` Protocol (ADR-0005 seam)                                           |
| `eval/prompt.py`       | `build_judge_system_prompt()`, `build_judge_user_prompt(...)`              |
| `eval/openai_judge.py` | `OpenAIJudge` — only module importing `openai`                             |
| `eval/stub_judge.py`   | `StubJudge` — CI drop-in, no key needed                                    |
| `eval/questions.py`    | `Question` model + `load_questions()` loader                               |
