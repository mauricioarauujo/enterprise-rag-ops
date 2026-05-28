# ADR 0004: Observability & Cost-Tracking Tool — Langfuse Self-Hosted, OTEL-Native Records

## Status

accepted

> Drafted in Sprint 2 / Phase 6 to constrain the eval-record schema **now**, so the
> Sprint 3 observability layer is an additive exporter rather than a rewrite. Acceptance is
> deferred to Sprint 3 / Phase 7, when the tool is actually wired and the choice is validated
> against a running deployment.

## Date

2026-05-25

## Context

The project's differentiator is the evaluation + observability layer. Sprint 3 (Phase 7) will
add tracing, cost rollups, and a failure-mode view. But Sprint 2 / Phase 6 builds the
multi-model eval **runner**, which produces one record per LLM call (model, token usage,
latency, derived cost, and the offline judge/retrieval/abstention scores). If those records
are shaped to a tool's data model only when Sprint 3 starts, Phase 6's persistence is thrown
away. Deciding the tool — or at least the **wire conventions** — now lets the Phase 6 record
be forward-compatible.

Decision criteria (what "good" means for this project):

- **Self-hostable** with no mandatory SaaS tenant; **OSS license** (MIT/Apache-2.0) fit for a
  public MIT repo; **low lock-in** (data exportable, OpenTelemetry-native preferred).
- Ingests both **traces** (a retrieval → generation → judge span tree) and **offline eval
  scores** (per-fact recall/precision, citation faithfulness, retrieval recall@k, abstention).
- Tracks **token cost + latency per call**; runnable locally by a reviewer via docker-compose.
- **Framework-agnostic**: the substrate uses neither LangChain nor LlamaIndex (ADR-0002/0003
  built custom seams), so the tool must support plain-Python manual instrumentation.
- **Budget-conscious**: self-hostable with minimal operational overhead; runnable from a
  `git clone` with no managed-service spend.

A focused Gemini Deep Research pass (2026-05-25, archived at
`.claude/kb/_research/archive/observability-2026-05-25.md`) compared Langfuse, Arize Phoenix,
LangSmith, and a pure-OTEL → Tempo/Jaeger path against these criteria.

## Decision

**Primary tool: Langfuse (self-hosted).** Runner-up: **Arize Phoenix**. The record wire format
is the **OpenTelemetry GenAI semantic conventions** regardless of tool, so a switch is a thin
remap, not a rewrite.

Rationale:

- **Langfuse** — MIT-licensed core, native OTLP ingestion, the most ergonomic manual-Python
  instrumentation (~38 LoC to trace a 3-step pipeline vs ~48 for Phoenix, ~55 for pure OTEL),
  and robust offline score write-back (`create_score` with a deterministic id as idempotency
  key). Self-host footprint is heavy (ClickHouse + Postgres + Redis), which is acceptable
  because it lands in Sprint 3, not now.
- **Arize Phoenix** (runner-up) — un-gated Apache-2.0, single-process/lightweight, OTEL +
  OpenInference native. Chosen as fallback if ClickHouse-cluster maintenance is too much
  DevOps; the tool-agnostic schema makes the swap code-free.
- **Rejected — LangSmith:** proprietary/closed-source, self-host is enterprise-only (sales
  contract + multi-node K8s), and it is optimized for LangChain/LangGraph — a poor fit for a
  custom thin substrate. Recorded as a considered alternative (the comparison is the signal).
- **Rejected as the product, adopted as the wire format — pure OTEL → Tempo/Jaeger:** maximum
  portability and zero lock-in, but generic APM backends have no LLM-native UI, no
  prompt/score model, and would require building a custom front-end + a secondary store for
  post-hoc eval scores. We adopt its **semantic conventions** without adopting it as the UI.

**Phased rollout** (this ADR governs Phase 1; Phases 2–3 are Sprint 3+):

1. **Phase 1 — now (Sprint 2 / Phase 6):** persist a **tool-agnostic per-call record to
   JSONL**, no live backend. This is the durable source of truth, is cloneable (a reviewer
   sees real numbers from `git clone`, no `docker-compose up`), and decouples persistence from
   any tool. The concrete persisted schema is pinned in **ADR-0007** (eval-record schema +
   cost model).
2. **Phase 2 — Sprint 3:** deploy self-hosted Langfuse (docker-compose); an async exporter
   replays the Phase 1 JSONL into Langfuse, using deterministic score IDs as idempotency keys.
3. **Phase 3 — later:** route through an OpenTelemetry Collector exporting OTLP to both
   Langfuse (LLM eval) and Tempo/Jaeger (general APM).

**Record field conventions (OTEL GenAI), to shape `CallStats`/`EvalRecord` in Phase 6:**

| Concept             | OTEL GenAI attribute                                                                            | Notes                                                                          |
| ------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Model               | `gen_ai.request.model`                                                                          | per call                                                                       |
| Provider/system     | `gen_ai.system`                                                                                 | e.g. `openai`, `anthropic`                                                     |
| Operation           | `gen_ai.operation.name`                                                                         | `chat` for generation + judge                                                  |
| Input tokens        | `gen_ai.usage.input_tokens`                                                                     | from provider `usage`                                                          |
| Output tokens       | `gen_ai.usage.output_tokens`                                                                    | from provider `usage`                                                          |
| Cost (USD)          | derived (`cost_usd`)                                                                            | **app-computed** from the ADR-0007 price table; not a canonical OTEL attribute |
| Retrieval span      | `db.system.name` / `db.collection.name` + `retrieval.documents.{i}.document.{id,content,score}` | retrieval is a `db`/retriever span, not a `gen_ai` chat call                   |
| Offline eval scores | `gen_ai.evaluation.{name, score.value, score.label, explanation}`                               | per-fact recall/precision, faithfulness, recall@k, abstention                  |

## Consequences

- **Phase 6 records are forward-compatible:** Sprint 3 adds a Langfuse (or Phoenix) exporter
  over the same JSONL, not a re-instrumentation. "Scalable from day 0 = the shape is right."
- **JSONL is the cloneable artifact:** published baseline numbers need no running infra.
- **Cost is app-derived** from a config price table (ADR-0007), since `gen_ai.usage.cost_usd`
  is not a stable OTEL attribute and no candidate computes it natively for these models.
- **Heavy self-host footprint is deferred,** not avoided: Sprint 3 must budget for ClickHouse +
  Postgres + Redis, or fall back to Phoenix (the tool-agnostic schema makes that free).
- **Open follow-up before acceptance:** the deep-research price table cites aggregator sources;
  verify per-model prices (especially `gpt-5-nano-2025-08-07`) against official OpenAI/Anthropic
  pricing pages when ADR-0007 locks the table.
- This ADR picks the **tool + wire conventions**; **ADR-0007** pins the **persisted record
  schema + cost-accounting model**. The two are written together in Phase 6.

## Acceptance Note

### Arize Phoenix Deployment (2026-05-28)

We have formally accepted **Arize Phoenix** as the deployed observability backend.

- **Hardware Rationale:** Our development environments run on 8 GB RAM machines. The self-hosted Langfuse stack (requiring ClickHouse, Postgres, and Redis) has an operational memory footprint (~4-6 GB) that is prohibitive for concurrent local workflows. Arize Phoenix runs as a single lightweight container, fitting comfortably within our hardware budget.
- **Pinned Image Tag:** We have deployed Arize Phoenix using the specific stable tag `arizephoenix/phoenix:version-15.0.0` to guarantee reproducible deployments and avoid issues with `:latest` image drift.
- **Schema Portability:** Because we strictly adhere to OpenTelemetry GenAI semantic conventions and the OpenInference wire format, all traced metadata (question ID, category, tokens, cost) and offline metric annotations (faithfulness, recall, precision, abstentions) are mapped using standardized keys. This ensures zero lock-in: if hardware capacity scales in a future sprint, migrating to Langfuse or an OTel Collector fan-out remains a thin mapping configuration swap rather than a pipeline rewrite.
