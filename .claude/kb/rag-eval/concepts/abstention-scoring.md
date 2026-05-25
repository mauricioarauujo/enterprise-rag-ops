# Abstention Scoring

> **Purpose**: How the eval harness scores whether the RAG system correctly identifies
> unanswerable questions — the empty-gold predicate, the two-layer architecture, and
> why the generator is the operative abstention layer.
> **Confidence**: HIGH (codebase — Phase 5, ground-truth inspected)
> **Codebase**: `eval/abstention.py`, `generation/schema.py`, `generation/cli.py`,
> `generation/prompt.py`, ADR-0003 (Phase-5 update note), ADR-0006

## The Unanswerable Predicate

A question is unanswerable when `len(expected_doc_ids) == 0` — not when its
`category == "info_not_found"`. These are not equivalent.

Phase-5 inspection of the 500-question corpus found 30 unanswerable questions:
20 are `info_not_found`, but 10 are `high_level`. A category-string check misses
that second group (33% of unanswerable questions). The predicate is always:

```python
# eval/abstention.py — compute_abstention_metrics
should_abstain = len(q.expected_doc_ids) == 0
```

## Precision and Recall over the Predicate

Abstention scoring is standard binary classification: TP when the system abstains
on an unanswerable question, FP when it abstains on an answerable one.

```python
# eval/abstention.py — compute_abstention_metrics
for q in questions:
    should_abstain = len(q.expected_doc_ids) == 0
    did_abstain = did_abstain_map[q.question_id]
    if should_abstain and did_abstain:     tp += 1
    elif not should_abstain and did_abstain: fp += 1
    elif should_abstain and not did_abstain: fn += 1
    else:                                    tn += 1

precision = tp / (tp + fp) if (tp + fp) > 0 else None
recall    = tp / (tp + fn) if (tp + fn) > 0 else None
```

`None` follows the same empty-denominator convention as fact_recall — see
[none-empty-denominator.md](none-empty-denominator.md).

## Two Abstention Layers

The system has two points where abstention can fire:

| Layer          | Where                                | Definition                              | When it fires                           |
| -------------- | ------------------------------------ | --------------------------------------- | --------------------------------------- |
| Retrieval gate | `generation/cli.py`                  | `retrieve_chunks()` returns `[]`        | Top-1 cosine < 0.45 threshold           |
| Generator      | `generation/prompt.py` + `schema.py` | Answer equals `ABSTAIN_ANSWER` sentinel | Context insufficient per model judgment |

The gate fires **without an LLM call** (zero cost). The generator requires an LLM
call because the retrieved context was above the cosine threshold but still
insufficient.

## Why the Gate Rarely Fires for Unanswerable Questions

The Phase-5 threshold sweep found that `info_not_found` gate-recall is **0.0** at
the 0.45 threshold. Unanswerable questions have lexically and semantically similar
context in the corpus — their best dense similarity score sits above the threshold.
The retriever returns results; the gate does not fire.

This means: **the generator is the operative abstention layer for unanswerable
questions in practice.** End-to-end abstention is only machine-checkable if the
generator emits a canonical, exact-match signal.

## The Enforced Sentinel Contract

`ABSTAIN_ANSWER = "I don't have enough information to answer this question."` lives
in `generation/schema.py` (shared by `cli.py` and `prompt.py`, breaking the import
cycle). The generator prompt explicitly instructs the model to emit exactly this
string — not a paraphrase — when context is insufficient:

```
If the context does not contain enough information to answer, you MUST set `answer`
to exactly this string — "I don't have enough information to answer this question."
— and return an empty `sources` list. Do not answer from prior knowledge.
```

End-to-end abstention detection is then a simple exact match:

```python
# eval/abstention.py — evaluate_e2e_abstention
did_abstain = ans.answer == ABSTAIN_ANSWER and len(ans.sources) == 0
```

A free-form abstention (e.g. "The provided context does not contain…") would fail
this check even though the model behaved correctly. This exact failure was caught
by the Phase-5 review when a hand-fabricated cassette was replaced with a real
recording — the genuine model response was free-form, not the sentinel.

## Two Evaluation Functions

```python
# eval/abstention.py

# Retrieval-level: did the retriever return an empty list?
evaluate_retrieval_abstention(questions, retrieved_results)
# → {"precision": float|None, "recall": float|None, "tp", "fp", "fn", "tn"}

# End-to-end: did answer == ABSTAIN_ANSWER and sources == []?
evaluate_e2e_abstention(questions, answers)
# → {"precision": float|None, "recall": float|None, "tp", "fp", "fn", "tn"}
```

Both call `compute_abstention_metrics` with a `did_abstain_map`.

## Related

- [none-empty-denominator.md](none-empty-denominator.md)
- [../patterns/cassette-replay-eval.md](../patterns/cassette-replay-eval.md)
- `eval/abstention.py`, `generation/schema.py`, `generation/cli.py`
- `docs/adr/0003-generation.md` (Phase-5 update note)
- `docs/adr/0006-cassette-replay.md`
