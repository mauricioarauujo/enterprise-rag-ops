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

## Retrieval Aggregation

```python
# eval/retrieval_eval.py
results = aggregate_retrieval_metrics(questions, ranked_results, k=10)
# → {"single_hop": {"recall_at_10": 0.72, "mrr": 0.65, ...}, ...}
# None if a category has no valid values (e.g. all unanswerable).
```

## Abstention Precision/Recall

```python
# eval/abstention.py
# Predicate: len(expected_doc_ids) == 0  (NOT category == "info_not_found")
# e2e: answer == ABSTAIN_ANSWER (exact sentinel from generation/schema.py) and sources == []
evaluate_retrieval_abstention(questions, retrieved_results)  # retriever returned []
evaluate_e2e_abstention(questions, answers)
# → {"precision": float|None, "recall": float|None, "tp", "fp", "fn", "tn"}
```

## Cassette/Replay (vcrpy)

```python
# tests/conftest.py — shared root fixture (Phase 6+)
# Filters request creds AND scrubs account-identifying response headers.
# vcrpy 6 has no filter_response_headers — use before_record_response.
vcr.VCR(
    cassette_library_dir="tests/eval/cassettes",
    record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
    filter_headers=["authorization", "x-api-key"],
    before_record_response=_scrub_response,   # drops org-id, set-cookie, cf-ray
)

# Record: VCR_RECORD_MODE=once uv run pytest tests/eval/test_abstention.py -m vcr
# Replay (default): make test  (no key, no network)
```

## File map (key modules)

Phase 4/5: `eval/schema.py` · `eval/aggregate.py` · `eval/interfaces.py` · `eval/prompt.py`
· `eval/openai_judge.py` · `eval/stub_judge.py` · `eval/questions.py`
· `eval/retrieval_metrics.py` · `eval/retrieval_eval.py` · `eval/abstention.py`
· `generation/schema.py` (ABSTAIN_ANSWER) · `tests/eval/cassettes/`

Phase 6: `eval/records.py` · `eval/config.py` · `eval/runner.py` · `eval/report.py`
· `generation/openai_generator.py` · `generation/anthropic_generator.py`
· `tests/conftest.py` (root vcr_record fixture)
