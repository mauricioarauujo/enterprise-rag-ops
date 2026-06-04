# Enterprise RAG Ops

Production-grade RAG evaluation and observability over the [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/enterprise-rag-bench) dataset.

## What this project is

A harness for building, **evaluating**, and **observing** a retrieval-augmented generation system the way it would be done at a company that ships RAG to enterprise customers — per-fact LLM-as-judge scoring, retrieval metrics with abstention, multi-model comparison, OpenTelemetry tracing, and a failure-mode taxonomy surfaced in a dashboard.

The primary differentiator is not the RAG itself — it's the **evaluation harness** and **observability layer** around it.

## What this project is not

- Not a RAG framework to compete with LangChain / LlamaIndex
- Not a leaderboard chase — the goal is depth on eval + ops, not SOTA scores
- Not production code for a real customer

## Architecture

This project maps the complete RAG lifecycle from ingest to observability. Standardized schemas and protocols enable plug-and-play evaluation across various retrieval pipelines and generator models.

### System Pipeline

```
[Stratified HF Data]
       │
       ▼ (Deterministic Ingest)
[corpus.jsonl]
       │
       ▼ (Hybrid Retrieval: BM25 + Dense BGE-M3 in LanceDB)
[Retrieved Docs]
       │
       ▼ (Generation: Structured Outputs with Attribution)
[Answer + Sources]
       │
       ▼ (Evaluation: Per-Fact LLM-as-Judge & Retrieval Overlap)
[Eval Records / Reports] ──► [Observability: Traces, Latency & Cost in Arize Phoenix]
```

### Component Model

| Phase             | Component             | CLI Command / Entry Point    | Description                                                                   |
| ----------------- | --------------------- | ---------------------------- | ----------------------------------------------------------------------------- |
| **Ingest**        | HF document stream    | `rag-ingest`                 | Stratifies HF source documents into a local `corpus.jsonl` subset.            |
| **Retrieval**     | Chunking & Vector DB  | `rag-index`                  | Chunks corpus and indexes using BM25s (lexical) + dense (BGE-M3) in LanceDB.  |
| **Generation**    | Structured generation | `rag-ask`                    | Assembles context and calls the model, forcing JSON with source attribution.  |
| **Evaluation**    | Custom evaluation     | `rag-eval`                   | Runs per-fact recall judge, retrieval overlap metrics, and cost aggregations. |
| **Observability** | Failure mode taxonomy | `rag-classify` / `make dash` | Classifies failures and launches the Streamlit dashboard app.                 |

### Architecture Decision Records (ADRs)

| ADR                                                 | Title                          | Decision                                                                                                                                                        | Status   |
| --------------------------------------------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| [ADR-0001](docs/adr/0001-eval-framework.md)         | Custom Thin LLM Judge          | Implement custom per-fact prompt grading directly rather than utilizing heavy frameworks (like Ragas) to maintain transparency, debuggability, and performance. | accepted |
| [ADR-0002](docs/adr/0002-retrieval-architecture.md) | Hybrid Retrieval Seams         | Deploy hybrid BM25s (sparse lexical) + BGE-M3 (dense vectors) in LanceDB with Reciprocal Rank Fusion (RRF) to optimize retrieval recall.                        | accepted |
| [ADR-0003](docs/adr/0003-generation.md)             | Structured Generator Contract  | Enforce JSON output format with source attribution list directly via model-level JSON schema constraints.                                                       | accepted |
| [ADR-0004](docs/adr/0004-observability-tool.md)     | Phoenix OTEL Persisted Records | Instrument traces with OpenTelemetry-native metrics and export them to Arize Phoenix for cost, token, and latency tracking.                                     | accepted |
| [ADR-0005](docs/adr/0005-llm-provider-matrix.md)    | LLM Provider Matrix            | Support OpenAI, Anthropic, and Ollama providers behind a clean client abstraction wrapper.                                                                      | accepted |
| [ADR-0006](docs/adr/0006-cassette-replay.md)        | Offline Cassette Replays       | Use VCR.py replay cassettes for LLM/prompt-based unit tests to prevent network flakiness and save API costs in CI.                                              | accepted |
| [ADR-0007](docs/adr/0007-eval-record-schema.md)     | Flat Aggregates Schema         | Store flat aggregates (recall, precision, faithfulness ratios, and costs) in JSONL to limit file footprint while avoiding heavy database dependencies.          | accepted |
| [ADR-0008](docs/adr/0008-failure-taxonomy.md)       | Cascading Failure Classifier   | Adopt a rule-based failure mode classifier utilizing cascading metrics to automatically label runs into a clean, diagnostic taxonomy.                           | accepted |

## Multi-Model Baseline Results

This baseline represents 1,499 records across 3 models: `gpt-5-nano-2025-08-07`, `claude-haiku-4-5-20251001`, and `gemini-2.5-flash-lite`.

### Overall Quality Summary

| Model                         | Fact Recall | Fact Precision | Faithfulness | Abstain Precision | Abstain Recall |
| ----------------------------- | ----------- | -------------- | ------------ | ----------------- | -------------- |
| **gpt-5-nano-2025-08-07**     | 24.6%       | 80.3%          | 88.1%        | 10.5%             | 69.0%          |
| **claude-haiku-4-5-20251001** | 24.1%       | 91.4%          | 92.1%        | 9.7%              | 93.3%          |
| **gemini-2.5-flash-lite**     | 24.0%       | 78.2%          | 78.6%        | 13.6%             | 70.0%          |

### Cost & Latency Summary

| Model                         | Total Cost (USD) | Mean Latency (sec) | Total Tokens |
| ----------------------------- | ---------------- | ------------------ | ------------ |
| **gpt-5-nano-2025-08-07**     | $0.8861          | 48.38s             | 3,492,418    |
| **claude-haiku-4-5-20251001** | $1.7019          | 15.04s             | 2,963,710    |
| **gemini-2.5-flash-lite**     | $0.6383          | 21.94s             | 2,763,753    |

## The Finding: Abstention vs. Hallucination Tradeoff

By parsing baseline failure classifications, we identify a clear **abstention vs. hallucination tradeoff** among the three evaluated generator models:

1. **Claude Haiku (`claude-haiku-4-5-20251001`)** over-abstains but maintains the highest quality and lowest hallucination rate. It achieves **91.4% Fact Precision** and **92.1% Faithfulness**, coupled with an extremely high **Abstain Recall of 93.3%**.
2. **Gemini Flash Lite (`gemini-2.5-flash-lite`)** under-abstains, leading to the highest hallucination rates but offering the lowest cost ($0.6383).
3. **GPT-5 Nano (`gpt-5-nano-2025-08-07`)** sits directly in the middle on quality, latency, and cost, providing a balanced trade-off.

### Verification of the Over-Abstention Pattern

Using the `rag-inspect` tool, we verified that Claude Haiku's over-abstention is a **genuine generator model behavior**, not the `0.45` retrieval threshold gate firing.

An exhaustive analysis of all **262** `abstention_error` records for Claude Haiku shows that **90.46%** (237/262) followed the pattern:

- `did_abstain_retrieval == False` (retrieval succeeded)
- Gold overlap was non-empty (relevant documents were loaded into context)
- `did_abstain_e2e == True` (the generator chose to abstain regardless)

This confirms that Claude Haiku systematically elects to abstain even when provided with the correct gold context, prioritizing safety/precision over recall. (The 90.46% figure uses gold-doc overlap; a looser proxy that only requires retrieval to return any documents gives 99.2% — both well past the 70% bar.)

Read the full analysis: [Over-Abstention: when a RAG generator refuses answers it has](docs/analysis/over-abstention.md).

## Quickstart & Reproducing Results

You can explore the aggregate baseline results locally in **under 15 minutes** without requiring API keys or infrastructure spin-up.

### 1. Fast Dashboard Quickstart (~15 mins)

Clone the repository and launch the Streamlit dashboard over the pre-computed three-way baseline:

```bash
# Clone repository
git clone https://github.com/mauricioarauujo/enterprise-rag-ops.git
cd enterprise-rag-ops

# Install dependencies using uv
uv sync

# Run Streamlit dashboard
make dash
```

This launches a local dashboard showing quality, failure-mode breakdowns, and cost summaries across the three models.

### 2. Inspecting Individual Questions

Use the read-only `rag-inspect` command to see the prompt, answers, source lists, and gold-overlap highlights for specific questions:

```bash
# Inspect a specific question (e.g. qst_0008)
uv run rag-inspect --question-id qst_0008

# Filter the inspection to a single model (e.g. Claude Haiku)
uv run rag-inspect --question-id qst_0008 --model claude-haiku
```

### 3. Re-Running the Benchmark

To re-run the end-to-end evaluation pipeline yourself (requires `OPENAI_API_KEY` and other credentials):

```bash
# 1. Fetch data & build the gold-aware index
make build-index-gold

# 2. Run the multi-model baseline sweep
make eval-baseline

# 3. Classify failures and run dashboard
make classify
make dash
```

## How this was built

This repository is two artifacts in one: a production-grade RAG eval + observability system, and a worked demonstration of **spec-driven, AI-assisted engineering**. The code was written with an AI coding agent (Claude Code); the engineering discipline around it — the gates, the seams, the decision records, the reviews — is the design contribution, and it is what the orchestration layer under [`.claude/`](.claude/README.md) makes legible.

**The process.** Every non-trivial phase ran the same spec-driven pipeline before any code was written:

```
/brainstorm  →  /define  →  /design  →  /implement  →  /review
 approaches    requirements  architecture   code        verification
              + Clarity gate + file manifest           + knowledge loop
```

- **Decisions are recorded at decision time, not retrofitted.** Eight [ADRs](docs/adr/) capture the _why_ behind the eval framework, retrieval architecture, generator contract, and observability tool — each written while the trade-off was still live, which is the only time an ADR is honest.
- **Stabilized knowledge is distilled into a knowledge base** ([`.claude/kb/`](.claude/kb/)) built on three pillars — the codebase, official docs, and deep research — so domain reasoning (retrieval, eval, observability) is captured once and reused, not re-derived each session.
- **The harness improves itself.** Repeated reasoning becomes a KB entry; a repeated workflow becomes a command; a recurring specialist context becomes an agent — structure that grows from observed need, not speculation.

**What the AI did, and what it didn't.** The agent produced code and prose under a human-authored spec and human-run quality gates (a ≥12/15 Clarity gate on requirements, `make lint test` in CI, a per-phase review). The architecture — the Protocol seams, the bronze/gold eval-record split, the abstention model, the failure taxonomy — is designed, not generated. The harness exists to keep that distinction auditable.

**A guided tour (~30 min).**

| To see…                                  | Read                                                                                                                                                                               |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The product                              | [`src/enterprise_rag_ops/`](src/enterprise_rag_ops/) + [Architecture](#architecture)                                                                                               |
| The reasoning behind one feature         | one exemplar phase — [`per-fact judge`](.claude/sdd/archive/sprint-2/phase-4-perfact-judge/) (`DEFINE → DESIGN → REVIEW`): the core eval signal, from requirements to verification |
| The observability differentiator         | the [`failure-taxonomy`](.claude/sdd/archive/sprint-3/phase-8-failure-taxonomy/) phase artifacts                                                                                   |
| The decisions                            | [`docs/adr/`](docs/adr/)                                                                                                                                                           |
| The distilled domain knowledge           | [`.claude/kb/`](.claude/kb/)                                                                                                                                                       |
| How the orchestration layer is organized | [`.claude/README.md`](.claude/README.md)                                                                                                                                           |

## Provenance Note

The `results/baseline.jsonl` dataset (approx. 2.1 MB) represents the honest provenance of three merged baseline sweep runs (`baseline`, `baseline-anthropic`, and `gemini`). Run IDs and source parameters are preserved in their raw states to allow tracing accuracy audits down to individual model operations.

## License

MIT. See [LICENSE](LICENSE) for details.
