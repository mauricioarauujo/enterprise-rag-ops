# ADR 0007: Evaluation Record Schema and Cost-Accounting Model

## Status

accepted

## Date

2026-05-25

## Context

In Sprint 2 / Phase 6, we implemented a multi-model evaluation runner that generates evaluation records. These records capture:

- The metadata of the run (e.g., question ID, category, run ID).
- LLM generation call details (input/output tokens, latency, cost).
- LLM judge call details (input/output tokens, latency, cost).
- Generated answer text and retrieved source documents.
- Computed metrics (fact recall, fact precision, faithfulness ratio, retrieval ranked IDs, abstention flags).

To ensure high data quality, minimal repository bloat, and alignment with modern standards, we need to:

1. Define a tool-agnostic schema for persisting these records to a JSONL format.
2. Align the fields with the OpenTelemetry (OTEL) GenAI semantic conventions drafted in ADR-0004.
3. Formulate the app-level cost-accounting model to calculate costs safely without hardcoding prices in source code.
4. Verify prices for the model matrix (including the new `gpt-5-nano-2025-08-07` model) against official API pricing.

## Decision

We adopt the following conventions and schemas for the persisted evaluation records:

### 1. Persistent Record Schema (`EvalRecord`)

We persist one record per question per model execution in a JSONL file. The JSON schema for each line (the `EvalRecord` Pydantic model) is:

| Field Name              | Type            | Description                                                                                                                                                        |
| :---------------------- | :-------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `question_id`           | `str`           | The unique identifier of the question.                                                                                                                             |
| `category`              | `str`           | The question category (e.g., `basic`, `conditional`, `info_not_found`).                                                                                            |
| `run_id`                | `str`           | The execution identifier (e.g., `baseline`).                                                                                                                       |
| `k`                     | `int`           | Retrieval cut-off (top-k) the run used; the report reads it rather than assuming 10.                                                                               |
| `gen_ai`                | `dict`          | Namespaced OpenTelemetry GenAI properties.                                                                                                                         |
| `gen_ai.request.model`  | `str`           | Model identifier requested.                                                                                                                                        |
| `gen_ai.system`         | `str`           | Model provider (e.g., `openai`, `anthropic`).                                                                                                                      |
| `gen_ai.operation.name` | `str`           | Operation name (always `"chat"`).                                                                                                                                  |
| `generation`            | `dict`          | Call statistics for the answer generation step (see `CallStats` below).                                                                                            |
| `judge`                 | `dict`          | Call statistics for the judge step (see `CallStats` below).                                                                                                        |
| `answer`                | `str`           | The raw text answer returned by the generator.                                                                                                                     |
| `sources`               | `list[str]`     | The document/chunk IDs cited as sources in the answer.                                                                                                             |
| `fact_recall`           | `float \| None` | Aggregate fact recall metric (`None` if generator abstained).                                                                                                      |
| `fact_precision`        | `float \| None` | Aggregate fact precision metric (`None` if generator abstained).                                                                                                   |
| `faithfulness_ratio`    | `float \| None` | Aggregate faithfulness metric (`None` if generator cited no sources).                                                                                              |
| `retrieval_ranked_ids`  | `list[str]`     | Deduplicated **doc-level** IDs from the retriever ranking — the offline retrieval-metric input (chunk IDs are mapped to their parent doc and de-duped first-wins). |
| `did_abstain_retrieval` | `bool`          | Whether the retriever abstained (no results above threshold).                                                                                                      |
| `did_abstain_e2e`       | `bool`          | Whether the generator abstained (returned the abstain answer phrase).                                                                                              |

#### `CallStats` Sub-schema:

| Field Name      | Type            | Description                                                      |
| :-------------- | :-------------- | :--------------------------------------------------------------- |
| `input_tokens`  | `int`           | Count of input tokens consumed.                                  |
| `output_tokens` | `int`           | Count of output tokens produced.                                 |
| `latency_s`     | `float`         | Call duration in seconds.                                        |
| `model`         | `str`           | Actual model ID used by the provider.                            |
| `system`        | `str`           | System identifier (`openai`, `anthropic`).                       |
| `cost_usd`      | `float \| None` | Derived cost of the call in USD. `None` if the price is missing. |

To keep the repository footprint small and clone times fast, we explicitly **exclude the raw verdict checklists** (individual per-fact annotations or per-citation checks) from the JSONL. Only python-derived aggregate metrics are persisted.

### 2. Cost-Accounting Model

We compute `cost_usd` dynamically at runtime using the following formula:

```
cost_usd = (input_tokens / 1,000,000) * input_usd_per_1m + (output_tokens / 1,000,000) * output_usd_per_1m
```

- Model prices are loaded dynamically from the YAML run configuration (`configs/baseline.yaml`).
- If a model does not have a price defined in the config, a warning is logged, and `cost_usd` is set to `None` (which renders as `"N/A"` in reports). This prevents misleading `$0.00` cost rollups.

### 3. Price-Verification of the Model Matrix

Prior to accepting this ADR, we verified the pricing of the baseline model matrix:

- **`gpt-5-nano-2025-08-07`**:
  - **Verified pricing**: Input: `$0.05` per 1M tokens, Output: `$0.40` per 1M tokens.
  - Source: Verified against official OpenAI pricing documentation for the nano-tier model.
- **`claude-3-5-haiku-20241022`**:
  - **Verified pricing**: Input: `$0.80` per 1M tokens, Output: `$4.00` per 1M tokens.
  - Source: Verified against official Anthropic pricing documentation.

These rates are correctly coded in `configs/baseline.yaml`.

## Consequences

- **Tool-agnostic Exportability**: The JSONL output is ready for direct ingest by OpenTelemetry-compatible backends (e.g. Langfuse, Arize Phoenix) without rewriting the instrumentation layer in Sprint 3.
- **Reduced Storage Overheads**: By omitting the raw JSON arrays of per-fact judgment lists, the JSONL file remains small enough to review and parse efficiently.
- **Safe Cost Calculation**: Reports distinguish clearly between zero cost (e.g., stubs) and missing price information (rendered as `"N/A"`).
- **Flexible Sweeps**: Pricing changes can be handled completely inside the YAML configuration files without requiring codebase modifications.
