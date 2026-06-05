# RAG Eval — Quick Reference

## Metric Formulas

| Metric               | Formula                              | `None` when                   |
| -------------------- | ------------------------------------ | ----------------------------- |
| `fact_recall`        | `present / facts`                    | `per_fact` is empty           |
| `fact_precision`     | `present / (present + contradicted)` | `present + contradicted == 0` |
| `faithfulness_ratio` | `supported / citations`              | `per_citation` is empty       |

Full abstention (no facts, no citations) → `(None, None, None)`.  
Downstream averaging must **exclude** `None`, not coerce to `0`.

## Schema Fields

| Model              | Fields                                                                            | Notes                      |
| ------------------ | --------------------------------------------------------------------------------- | -------------------------- |
| `FactVerdict`      | `fact: str`, `verdict: Literal["present","absent","contradicted"]`                | Closed (`extra="forbid"`)  |
| `CitationVerdict`  | `doc_id: str`, `verdict: Literal["supported","unsupported"]`                      | Closed (`extra="forbid"`)  |
| `_LLMJudgeVerdict` | `per_fact: list[FactVerdict]`, `per_citation: list[CitationVerdict]`              | LLM-facing only; no floats |
| `JudgeVerdict`     | above + `fact_recall`, `fact_precision`, `faithfulness_ratio` (all `float\|None`) | Public output              |

## Judge call / Prompt

`response_format`: `type=json_schema`, `name=JudgeVerdict`, `schema=_LLMJudgeVerdict.model_json_schema()`, `strict=True`. Prompt: `System` = role+rubric+schema; `User` = QUESTION / ANSWER / GOLD FACTS (numbered) / CITED DOCUMENTS (one block per `doc_id`).

## Env variables

| Variable          | Default                 | Purpose                                     |
| ----------------- | ----------------------- | ------------------------------------------- |
| `RAG_JUDGE_MODEL` | `gpt-5-nano-2025-08-07` | Override judge model                        |
| `OPENAI_API_KEY`  | —                       | Required for live `OpenAIJudge`; not for CI |

## Retrieval Aggregation

```python
results = aggregate_retrieval_metrics(questions, ranked_results, k=10)  # eval/retrieval_eval.py
# → {"single_hop": {"recall_at_10": 0.72, "mrr": 0.65, ...}, ...}; None if a category has no valid values.
```

## Abstention Precision/Recall

```python
# eval/abstention.py — predicate: len(expected_doc_ids) == 0 (NOT category=="info_not_found")
# e2e: answer == ABSTAIN_ANSWER (exact sentinel, generation/schema.py) and sources == []
evaluate_retrieval_abstention(questions, retrieved_results)  # retriever returned []
evaluate_e2e_abstention(questions, answers)
# → {"precision": float|None, "recall": float|None, "tp", "fp", "fn", "tn"}
```

## Cassette/Replay (vcrpy)

```python
# tests/conftest.py — shared root fixture (Phase 6+). Scrubs creds + account headers.
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

## Triage / Issues (Sprint 5, Phase 14+15)

```
rag-triage --results results/baseline.jsonl       # writes results/triage.json
rag-issues --triage results/triage.json           # dry-run: writes results/issues/*.md
rag-issues --triage results/triage.json --create  # idempotent GitHub creation via gh CLI
rag-issues ... --all-clusters                     # all clusters (default: dominant only)
```

| Item             | Value                                                                                |
| ---------------- | ------------------------------------------------------------------------------------ |
| Cluster key      | `(failure_mode, category)` from the record's own fields                              |
| Rate             | `count / total_records` (integer division never occurs; `total==0` → early return)   |
| Representative   | `min(bucket, key=lambda r: r.question_id)` — lex-first question_id                   |
| Sort order       | `count desc`, tiebreaker `(failure_mode, category) asc`                              |
| `SCHEMA_VERSION` | `"1.0"` — embedded in `TriageReport`; `rag-issues` hard-rejects mismatches           |
| Fingerprint      | `rag-triage-cluster: {fm}\|{cat} schema={version}` — substring of hidden HTML marker |
| Default labels   | `["rag-triage"]`                                                                     |

## Router Combined Cost + Cost-Guard (ADR-0012)

- Combined cost (`RouterGenerator`): cheap always + strong iff escalated, `None`→`0.0`, `model="router"`.
- Runner guard `if gen_stats.cost_usd is None:` — a pre-set generator cost is owned, not recomputed (the `"router"` row, with no price entry, survives); judge cost always recomputed. Out of scope: cost-per-correct-answer metric (phase-3). See `concepts/cost-accounting.md` + `rag-generation/patterns/router-cascade-composite.md`.

## File map (key modules)

Phase 4/5: `eval/schema.py` · `eval/aggregate.py` · `eval/interfaces.py` · `eval/prompt.py`
· `eval/openai_judge.py` · `eval/stub_judge.py` · `eval/questions.py`
· `eval/retrieval_metrics.py` · `eval/retrieval_eval.py` · `eval/abstention.py`
· `generation/schema.py` (ABSTAIN_ANSWER) · `tests/eval/cassettes/`
Phase 6: `eval/records.py` · `eval/config.py` · `eval/runner.py` · `eval/report.py`
· `generation/openai_generator.py` · `generation/anthropic_generator.py` · `tests/conftest.py`
Phase 14+15: `eval/triage.py` · `eval/triage_cli.py` · `eval/issues.py` · `eval/github.py` · `eval/issues_cli.py`
Phase 19: `eval/raw_call.py` (RawCall) · `eval/bronze.py` (BronzeWriter) — bronze archive, opt-in via `RunConfig.persist_bronze`
S7-P2: `generation/router_generator.py` (RouterGenerator) · `eval/config.py` (RouterConfig) · `eval/runner.py` (cost-guard) — ADR-0012
