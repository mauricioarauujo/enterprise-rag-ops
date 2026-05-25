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
# tests/eval/conftest.py — vcr_record fixture
record_mode = os.environ.get("VCR_RECORD_MODE", "none")  # fail if no cassette
vcr.VCR(cassette_library_dir="tests/eval/cassettes",
        record_mode=record_mode, filter_headers=["authorization"])

# Record: VCR_RECORD_MODE=once uv run pytest tests/eval/test_abstention.py -m vcr
# Replay (default): make test  (no key, no network)
```

## File map

| Module                      | Role                                                                                     |
| --------------------------- | ---------------------------------------------------------------------------------------- |
| `eval/schema.py`            | `FactVerdict`, `CitationVerdict`, `_LLMJudgeVerdict`, `JudgeVerdict`                     |
| `eval/aggregate.py`         | Pure-Python `aggregate(per_fact, per_citation) -> tuple[float\|None, ...]`               |
| `eval/interfaces.py`        | `Judge` Protocol (ADR-0005 seam)                                                         |
| `eval/prompt.py`            | `build_judge_system_prompt()`, `build_judge_user_prompt(...)`                            |
| `eval/openai_judge.py`      | `OpenAIJudge` — only module importing `openai`                                           |
| `eval/stub_judge.py`        | `StubJudge` — CI drop-in, no key needed                                                  |
| `eval/questions.py`         | `Question` model + `load_questions()` loader                                             |
| `eval/retrieval_metrics.py` | `recall_at_k`, `precision_at_k`, `mrr`, `ndcg_at_k`, `deduplicate_ranked_ids`            |
| `eval/retrieval_eval.py`    | `aggregate_retrieval_metrics` — per-category aggregation, None-skipping                  |
| `eval/abstention.py`        | `compute_abstention_metrics`, `evaluate_retrieval_abstention`, `evaluate_e2e_abstention` |
| `generation/schema.py`      | `ABSTAIN_ANSWER` sentinel (shared by `cli.py` and `prompt.py`)                           |
