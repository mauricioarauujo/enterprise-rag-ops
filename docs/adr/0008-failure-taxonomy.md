# ADR 0008: Rule-Based Failure-Mode Taxonomy and Classifier

## Status

accepted

## Date

2026-05-30

## Context

In evaluation, identifying that a pipeline execution failed is only the first step. To enable systematic diagnosis, we need a failure taxonomy that classifies each evaluation record into a specific failure category based on aggregate metrics and gold standards.

## Decision

We adopt a rule-based failure-mode taxonomy with a first-match cascade classifier. The details of the taxonomy, predicates, thresholds, and field ownership are described below:

### 1. Vocabulary (FR-11a)

The classifier assigns exactly one of five mutually exclusive failure-mode labels (represented as strings):

- **`abstention_error`**: A discrepancy between when the RAG system should have abstained (because the question is unanswerable from the gold documents) and when it actually abstained.
- **`retrieval_miss`**: A failure where the retriever did not return any gold documents in its top-$k$ retrieved slice for an answerable question, resulting in a binary retrieval failure.
- **`hallucination`**: The system retrieved relevant documents, but the generated answer was unfaithful to them (faithfulness ratio falls below the specified threshold).
- **`incomplete`**: The system retrieved documents and cited them faithfully, but the generated answer failed to recover a sufficient portion of the required gold facts (fact recall falls below the specified threshold).
- **`correct`**: A positive classification indicating that the system correctly abstained when it should have, or correctly answered with high faithfulness and recall.

### 2. Cascade Order and Justification (FR-11b)

The classification follows a strict, priority-ordered cascade:
`abstention_error` → `retrieval_miss` → `hallucination` → `incomplete` → `correct`

**Justification for `abstention_error` first:** A false abstention (an answerable question where the model refused to answer) results in a fact recall of 0.0 or `None` and has no sources cited. If not checked first, such records would mis-classify as `incomplete` or fall through to `correct`. Checking `abstention_error` at the very start of the cascade ensures that this specific behavioral discrepancy is correctly identified and categorized without being masked by downstream metrics.

### 3. Per-Label Predicates by Field Name (FR-11c)

Predicates evaluate an `EvalRecord` and the gold `Question` using the following logic and fields:

- **`_should_abstain`**: `len(question.expected_doc_ids) == 0`
- **`_retrieval_hit`**: `len(question.expected_doc_ids) > 0` and `bool(set(question.expected_doc_ids) & set(record.retrieval_ranked_ids[:record.k]))`
- **`is_abstention_error`**: `_should_abstain(question) != record.did_abstain_e2e`
- **`is_retrieval_miss`**: `len(question.expected_doc_ids) > 0` and `not (set(question.expected_doc_ids) & set(record.retrieval_ranked_ids[:record.k]))`
- **`is_hallucination`**: `_retrieval_hit(record, question)` and `record.faithfulness_ratio is not None` and `record.faithfulness_ratio < HALLUCINATION_FAITHFULNESS_THRESHOLD`
- **`is_incomplete`**: `_retrieval_hit(record, question)` and `not is_hallucination(record, question)` and `not record.did_abstain_e2e` and `record.fact_recall is not None` and `record.fact_recall < INCOMPLETE_RECALL_THRESHOLD`

### 4. Empirical Threshold Values and Baseline-Distribution Rationale (FR-11d)

We define the threshold constants exactly as:

- `HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5`
- `INCOMPLETE_RECALL_THRESHOLD = 0.5`

#### Baseline-distribution rationale:

- **`HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5`**, predicate `faithfulness_ratio < 0.5` (**strict `<`**).
  - **Distribution:** `faithfulness_ratio` is 519 non-null, 480 `None` (≈ the 478 e2e abstentions → no sources cited → `None` per ADR-0007 empty-denominator). Strongly **bimodal**: **433 records at exactly 1.0**, a low tail, **37 records < 0.5**, with a borderline cluster of **21 at exactly 0.5**, 58 < 0.6.
  - **Why strict `<` 0.5:** the conservative "majority of cited docs unfaithful" reading. The 21 `==0.5` borderline records stay **OUT** of hallucination (exactly half faithful is not flagged). The predicate flags 37/519 ≈ 7.1% of grounded answers **in isolation** — a real, non-trivial tail, not noise. **Post-cascade**, the committed baseline carries **33** `hallucination` tags: a few low-faithfulness records are claimed earlier by `abstention_error`/`retrieval_miss` (checked first), so the final tally is ≤ the isolated-predicate count by construction.

- **`INCOMPLETE_RECALL_THRESHOLD = 0.5`**, predicate `fact_recall < 0.5`.
  - **Distribution:** `fact_recall` is 999 non-null, 0 `None`. Zero-inflated: **630 at exactly 0.0**, median 0.0, p75 = 0.4, p90 = 1.0, mean 0.243.
  - **Why 0.5:** "fewer than half the gold facts recovered = incomplete", symmetric with the faithfulness cut. The mass of zeros is dominated by the 478 abstentions + retrieval failures, which the cascade strips **before** `incomplete` is reached (`abstention_error` + `retrieval_miss` are checked first) — so the raw zeros are **not** the population the `incomplete` predicate sees. The threshold is applied only on the **post-cascade population** (retrieval hit, faithfulness OK, not abstaining), so abstention/miss zero-inflation does not distort it.

### 5. Incomplete Definition (FR-11e)

The label `incomplete` signifies a quality failure where the system successfully retrieved relevant documents and cited them faithfully (above the hallucination threshold), yet the generated response missed required gold facts (fact recall below 0.5). It represents an answer-completeness/under-generation failure rather than a structural formatting issue (which cannot be inferred from metric aggregates). We rename this label from `formatting` to `incomplete` to accurately reflect its semantic meaning.

### 6. Aggregate-Granularity Precision Limitation (FR-11f)

The classifier operates entirely on aggregates and gold data. Because individual per-fact validation checks or per-citation verification verdicts are omitted from the persistent `EvalRecord` to minimize disk footprints, we cannot pinpoint _which_ specific fact was hallucinated or _which_ source citation was unfaithful. Classification is a high-level diagnostic mapping rather than a fine-grained citation validator.

### 7. Field Ownership and Serialization (FR-11g)

ADR-0008 defines and owns the `failure_mode` field on `EvalRecord`.

- The field is added as `failure_mode: str | None = None`.
- Pydantic serializes and deserializes the string value natively. Using a string type maintains backward compatibility with older untagged results (which parse cleanly to `None`).
- This design cross-references the schema conventions set forth in [ADR 0007](0007-eval-record-schema.md).
