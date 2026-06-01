# BRAINSTORM: phase-7-tracing — Langfuse Exporter & ADR-0004 Acceptance

**Sprint/Phase:** sprint-3/phase-7-tracing | **Date:** 2026-05-27

## Problem Statement

The Phase 6 multi-model runner produces a durable `results/*.jsonl` (one `EvalRecord` per
question per model) shaped to OTEL GenAI conventions per ADR-0004/0007. Phase 7 closes the
observability loop: a replay exporter reads that JSONL and writes each record into a
self-hosted Langfuse instance as a `retrieval → generation → judge` span tree with offline
eval scores attached, re-runnable idempotently via deterministic trace and score IDs. The
phase also validates that the Langfuse stack actually runs on a constrained dev machine,
formally accepting ADR-0004 (currently "proposed") against a live deployment.

---

## Research & KB Scan

| Topic                                                                                                                                | KB file / domain                                                                                                                                                          | Coverage                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OTEL GenAI semantic conventions — span kinds, attribute names, retrieval doc attributes                                              | ADR-0004, `_research/archive/observability-2026-05-25.md`                                                                                                                 | Sufficient — ADR-0004 pins the complete attribute mapping; archived deep-research file provides full field-level detail.                                                                                                               |
| Langfuse v3 Python SDK — `start_as_current_observation`, `create_score`, `create_trace_id`, `flush`, `usage_details`, `cost_details` | Not in KB — archived research file references stale v2 API (`langfuse.trace()` / `trace.span()`). Current v3 APIs confirmed via Context7 and provided in the phase brief. | Thin → no `/new-kb` needed before `/define`; grounding is provided in this brainstorm. The `observability` KB domain build is scheduled _after_ ADR-0004 acceptance (SPRINT.md).                                                       |
| Langfuse self-host footprint — docker-compose stack, Postgres + ClickHouse + Redis + MinIO                                           | ADR-0004 names the components. Actual resource requirements on an 8 GB Air are a live validation, not a KB matter.                                                        | Sufficient for scoping; real risk is resolved by the footprint-first spike (Decision 5).                                                                                                                                               |
| Arize Phoenix self-host footprint — single-process, OTEL + OpenInference                                                             | ADR-0004 (runner-up rationale).                                                                                                                                           | Sufficient — fallback path is justified; no additional research needed. Note: Phoenix score write-back uses `px_client.spans.upload_evaluations()` with a dataframe, not `create_score`; the swap is small but not literally zero LoC. |
| Idempotency via deterministic trace IDs                                                                                              | Not in KB. `Langfuse.create_trace_id(seed=...)` confirmed in v3 SDK via Context7.                                                                                         | Thin → covered by Decision 2 below; straightforward enough that no KB entry is needed before `/define`.                                                                                                                                |
| `EvalRecord` / `CallStats` schema                                                                                                    | `src/enterprise_rag_ops/eval/records.py`, ADR-0007 (accepted).                                                                                                            | Sufficient — the exporter's full input contract is defined. Key constraint: record stores ranked doc IDs only; no chunk content or per-doc scores (ADR-0007 storage/clone footprint decision).                                         |

**Conclusion.** No `/new-kb`, `/update-kb`, or `--deep-research` passes block `/define`.
The `observability` KB domain (`/new-kb observability`) executes after ADR-0004 is accepted
at phase close — it captures decided design, not pre-decision research.

---

## Approaches Considered

### Decision 1 — Exporter instrumentation: Langfuse v3 SDK vs raw OTLP

The exporter must write a three-level span tree and attach offline eval scores per record.
Two instrumentation paths:

| Approach                                                                                                                                                                                                              | Pros                                                                                                                                                                                                                | Cons                                                                                                                                                                                                                                                                      | Effort |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Langfuse v3 Python SDK — `start_as_current_observation(as_type="span"/"generation")` context managers; `create_score` for offline scores; `cost_details` native field; `create_trace_id(seed=...)` for idempotency | ~38 LoC ergonomic; nesting automatic via context; `cost_details` maps directly from `EvalRecord.generation.cost_usd`; `create_score` is first-class with `data_type` and idempotency key; native to the chosen tool | Langfuse SDK coupling; Phoenix fallback requires a ~30 LoC remap (different score API); not "code-free" but still localized to one module                                                                                                                                 | S      |
| B. Raw OTLP via `opentelemetry-sdk` to Langfuse's OTLP endpoint — generic span/attribute API; endpoint URL is the only tool-specific config                                                                           | Maximally tool-agnostic at the wire; a Langfuse → Phoenix swap is a URL change; matches the ADR-0004 Phase 3 OTEL-Collector path                                                                                    | No first-class offline score model in generic OTEL — scores need a side-channel (back to the SDK anyway); `cost_details` must be span attributes instead of native field; substantially more boilerplate with no benefit for this phase's scope; premature generalization | M–L    |

**Leaning: A.** ADR-0004's "tool-agnostic" principle protects the _schema_ (OTEL GenAI
attribute names are used regardless of SDK), not the _call style_. Building the OTEL-Collector
path now is the explicitly deferred ADR-0004 Phase 3 work. The Phoenix fallback (~30 LoC
remap) is localized to `observability/exporter.py` — the `observability/` module boundary
is the seam; the SDK is an implementation detail inside it.

---

### Decision 2 — Idempotency: deterministic IDs vs exporter-side state file

Re-running the same JSONL must not create duplicate traces or scores in Langfuse.

| Approach                                                                                                                                                                           | Pros                                                                                                                                                                                                  | Cons                                                                                                                                                                                         | Effort |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Deterministic IDs via `Langfuse.create_trace_id(seed=f"{run_id}:{question_id}:{model}")` — score IDs seeded from `f"{trace_seed}:{score_name}"`; Langfuse upserts on a known ID | Zero exporter state; seed is self-documenting and reproducible from the JSONL alone; works across separate process invocations; different `run_id` values naturally produce separate trace namespaces | Relies on Langfuse v3 upsert-on-known-ID semantics (confirmed); async ingestion means the trace may not be immediately queryable after the first flush — not a correctness issue for re-runs | S      |
| B. Exporter-side state file tracking `(run_id, question_id, model) → trace_id`                                                                                                     | Decouples idempotency from backend internals                                                                                                                                                          | State file must be managed; breaks if deleted or backend wiped; git footprint risk; adds an artifact not derivable from the JSONL                                                            | M      |

**Leaning: A.** Deterministic IDs are the primitive Langfuse v3 provides for exactly this
use case. The seed formula encodes all uniqueness dimensions: the eval sweep (`run_id`), the
question (`question_id`), and the generator model. No side-file needed.

---

### Decision 3 — Retrieval-span fidelity: id+rank-only vs re-hydrate vs named seam

`EvalRecord.retrieval_ranked_ids` stores doc-level ID strings; `EvalRecord.sources` stores
cited IDs. Chunk content and per-doc relevance scores were deliberately excluded from
`EvalRecord` (ADR-0007 storage/clone footprint decision). The OTEL GenAI retrieval span
ideal includes `retrieval.documents.{i}.document.content` and `.score`.

| Approach                                                                                                                                                                | Pros                                                                                                                                                                 | Cons                                                                                                                                                                        | Effort |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. id+rank-only retrieval spans — populate `retrieval.documents.{i}.document.id` and rank position (index in `retrieval_ranked_ids`) only; omit `.content` and `.score` | Zero extra dependencies; exporter stays additive over JSONL alone; honest about what the record persists; doc IDs + rank are sufficient to diagnose a retrieval miss | Span is less rich than the OTEL ideal; `.content` absent                                                                                                                    | S      |
| B. Re-hydrate content and scores at export time — load LanceDB + BM25 index at export time, look up each doc ID, populate `.content` / `.score`                         | Maximally rich retrieval spans                                                                                                                                       | Adds hard LanceDB + BM25 dependency to the exporter; breaks additive/cloneable design principle; index may be stale or absent on a different machine; export time increases | L      |
| C. id+rank-only now (same as A) with a named `--enrich-from-index` seam documented in code — a future flag for B, not built in Phase 7                                  | Same as A with an explicit extension point; leaves the door open without building it                                                                                 | Content absent in Phase 7 traces                                                                                                                                            | S      |

**Leaning: C.** The diagnostic value in Phase 7 — "which docs were ranked, in what order,
and did cited sources overlap with gold" — is fully available from `retrieval_ranked_ids`
and `sources` alone. Re-hydration couples the exporter to a running index for a portfolio
phase where the additive/cloneable property matters more. The `--enrich-from-index` flag is
the named seam; it can be added in Phase 8/9 or never. ADR-0004's `retrieval.documents.*`
attribute slots remain reserved.

---

### Decision 4 — Span tree shape and score attachment placement

One `EvalRecord` maps to one Langfuse trace with three child spans: `retrieval`,
`generation`, `judge`. Offline eval scores attach via `create_score`. The question is
whether scores land on the trace root or the semantically aligned child span.

| Approach                                                                                                                                                                                                                                                                                                                                                                | Pros                                                                                                                                                                                       | Cons                                                                                                                                                 | Effort |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. All scores on trace root — `fact_recall`, `fact_precision`, `faithfulness_ratio`, `did_abstain_retrieval`, `did_abstain_e2e` all as `create_score` on the trace; spans carry only telemetry (tokens, cost, latency)                                                                                                                                                  | Simple; Langfuse UI score aggregation operates at trace level by default; fewer API calls                                                                                                  | Loses the semantic link between score and span; a reviewer cannot tell at a glance which span produced which score; misses the "where it broke" goal | S      |
| B. Semantically aligned attachment — `fact_recall` + `fact_precision` on `judge` span (judge produced them); `faithfulness_ratio` on `generation` span (answer vs. sources); `did_abstain_retrieval` on `retrieval` span; `did_abstain_e2e` on trace root. Trace-level rollups for the three float metrics as a Should (duplicate to enable Langfuse aggregation views) | Semantically coherent; a reviewer opening the `judge` span immediately sees recall/precision; directly delivers the "where it broke" experience; extra `create_score` calls are negligible | Slightly more API calls per record                                                                                                                   | S–M    |

**Leaning: B.** The Sprint 3 portfolio bar is "a reviewer opens a failed trace and sees
what happened, where it broke, and what it cost." Span-aligned scores deliver that directly.
Trace-level rollups for the float metrics (duplicated from span to root) are a Should to
enable Langfuse's built-in aggregation view — the per-span attachment is the Must.

---

### Decision 5 — Footprint de-risking and ADR-0004 acceptance path

Phase 7 must commit a `docker-compose.yml` for Langfuse and validate it on the dev machine.
The self-host footprint is the highest risk (SPRINT.md).

| Approach                                                                                                                                                                                                                                                                                                                                       | Pros                                                                                                                                                                                                                                             | Cons                                                                                                                                                                                                  | Effort                                 |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| A. Build exporter first, validate infra at phase close — implement the full exporter against the Langfuse v3 SDK; stand up docker-compose and run end-to-end as the final step; accept ADR-0004 if it works                                                                                                                                    | Feels more like forward progress; code is written against a known SDK                                                                                                                                                                            | Discovering ClickHouse OOM at phase-close after ~4h of implementation is the worst-case outcome; all exporter code may need a Phoenix remap under time pressure                                       | M                                      |
| B. Validate footprint first (spike) — run `docker-compose up` with a minimal Langfuse config as the FIRST task in the phase; if RAM is acceptable, proceed with the Langfuse SDK path; if ClickHouse OOMs, pivot to Phoenix immediately (the exporter diff is ~30 LoC as established in Decision 1); record the outcome in ADR-0004 acceptance | Fail-fast on the highest-risk item; remaining ~4h of implementation is committed to the right SDK path; ADR-0004 acceptance is honest about hardware constraints; the Phoenix pivot trigger is decided before a line of exporter code is written | Adds an explicit sequential dependency: infra validation before SDK implementation                                                                                                                    | M (same total; earlier decision point) |
| C. Start with Arize Phoenix as primary, treat Langfuse as "if footprint allows" upgrade                                                                                                                                                                                                                                                        | Zero footprint risk; single-process Phoenix fits easily on 8 GB                                                                                                                                                                                  | Inverts the ADR-0004 decision hierarchy; Langfuse is the tool the ADR justifies and the portfolio demonstrates; Phoenix-first means accepting the runner-up by default before even trying the primary | S                                      |

**Leaning: B.** SPRINT.md calls the footprint "the highest risk." A 20-minute
`docker-compose up` + ingestion of one hand-built trace resolves the biggest unknown at
the start of the phase. The explicit Phoenix-fallback trigger (e.g., "if ClickHouse
container exceeds X GB RAM or the stack OOMs on first ingest") must be named in `/define`
so there is no ambiguity at implementation time. Approach C bypasses the primary tool
without evidence; Approach A buries the risk.

---

## Recommended Approach

**Decision 1: Langfuse v3 SDK** (Approach A). OTEL GenAI attribute names are used
regardless; the SDK handles transport. Phoenix fallback is a ~30 LoC remap localized to
`observability/exporter.py`. The `observability/` module is the seam.

**Decision 2: Deterministic IDs** (Approach A) seeded from
`f"{run_id}:{question_id}:{model}"`. No stateful side-files; replay is naturally idempotent
across invocations.

**Decision 3: id+rank-only retrieval spans with named `--enrich-from-index` seam**
(Approach C). Exporter stays additive over JSONL; honest about what ADR-0007 persists;
extension point is documented.

**Decision 4: Semantically aligned score attachment** (Approach B). `fact_recall` /
`fact_precision` on `judge` span; `faithfulness_ratio` on `generation` span; abstention
flags on their respective spans; trace-level float rollups as a Should.

**Decision 5: Validate footprint first** (Approach B). Run `docker-compose up` and ingest
one trace before writing exporter code; name the Phoenix pivot trigger explicitly in
`/define`; record the validated outcome in ADR-0004 acceptance note.

Rationale across all decisions: the 5h budget is tight, and the infra risk is resolved
before irreversible implementation work begins. Every other choice keeps the exporter
additive over the JSONL, uses ergonomic v3 SDK primitives against a pre-chosen tool, and
follows the minimal-scope/clean-seam engineering ethos.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                                                                                                                                                                                                            |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | Footprint validation: `docker-compose up` for self-hosted Langfuse (or Phoenix if Langfuse OOMs) runs cleanly on the dev machine. Outcome recorded in ADR-0004 acceptance note with hardware and RAM context. This is the first task in the phase, not the last.                                                                                                                |
| Must     | `infra/langfuse/docker-compose.yml` (or `infra/phoenix/`) committed; `make trace-up` target brings the backend up.                                                                                                                                                                                                                                                              |
| Must     | `src/enterprise_rag_ops/observability/exporter.py` — `replay_jsonl(path, langfuse_client)` reads a `results/*.jsonl`, iterates `EvalRecord` objects, writes one trace per record with `retrieval`, `generation`, `judge` child spans via `start_as_current_observation`.                                                                                                        |
| Must     | Span attributes follow ADR-0004 OTEL GenAI conventions: `gen_ai.request.model`, `gen_ai.system`, `gen_ai.operation.name`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `cost_details` (from `cost_usd`); retrieval span populates `retrieval.documents.{i}.document.id` and rank position.                                                                        |
| Must     | Deterministic trace IDs via `Langfuse.create_trace_id(seed=f"{run_id}:{question_id}:{model}")`. Score IDs seeded from `f"{trace_seed}:{score_name}"`. Re-running the same JSONL upserts, no duplicates.                                                                                                                                                                         |
| Must     | Offline eval scores attached to semantically aligned spans: `fact_recall` + `fact_precision` on `judge` span; `faithfulness_ratio` on `generation` span; `did_abstain_retrieval` on `retrieval` span; `did_abstain_e2e` on trace root. `create_score` with `data_type="NUMERIC"` or `"BOOLEAN"`.                                                                                |
| Must     | `langfuse.flush()` called before process exit. Exporter is robust to `cost_usd=None` — skip `cost_details` if absent; never write `$0.00` as a substitute for missing cost (same "N/A not 0" convention as the HTML report).                                                                                                                                                    |
| Must     | `rag-export-traces` console script in `pyproject.toml`; entry point `observability/cli.py:main`; `--results` path argument; credentials via env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`).                                                                                                                                                           |
| Must     | `make export-traces` Makefile target — runs `uv run rag-export-traces --results results/baseline.jsonl`; requires the backend to be up.                                                                                                                                                                                                                                         |
| Must     | ADR-0004 status updated "proposed" → "accepted" with a validation note: tool validated, hardware context, docker-compose version pinned, any deviation (e.g. Phoenix adopted if Langfuse OOMs).                                                                                                                                                                                 |
| Must     | `tests/test_exporter.py` — unit tests over a hand-built 2-record JSONL + a fake/patched Langfuse client. Asserts: correct span tree shape; correct attribute names per ADR-0004; score attachment to the right span; deterministic ID reproducibility; idempotency (second call produces identical IDs); `cost_usd=None` handled gracefully. No real Langfuse running required. |
| Should   | Trace-level rollup scores for `fact_recall`, `fact_precision`, `faithfulness_ratio` duplicated from span level to trace root, to enable Langfuse's built-in score aggregation views.                                                                                                                                                                                            |
| Should   | `--dry-run` flag on `rag-export-traces` — parses JSONL, logs what would be exported, writes nothing to the backend. Useful for validating a JSONL before committing to the write.                                                                                                                                                                                               |
| Should   | `/new-kb observability` after ADR-0004 is accepted — captures the decided exporter pattern, span tree shape, score attachment, idempotency seed formula, docker-compose footprint. Per SPRINT.md: execute at phase close.                                                                                                                                                       |
| Could    | `did_abstain_retrieval` and `did_abstain_e2e` exported with a human-readable `comment` field (e.g. `"retriever returned no results above threshold"`).                                                                                                                                                                                                                          |
| Could    | `--enrich-from-index` flag — named seam for a future re-hydration path that loads LanceDB + BM25 and populates `retrieval.documents.{i}.document.{content,score}`. Not built in Phase 7; documented in code as the extension point.                                                                                                                                             |
| Won't    | Live in-process tracing during the eval run — the JSONL is the durable source of truth (ADR-0004 Phase 1 decision). Not re-opened.                                                                                                                                                                                                                                              |
| Won't    | OTEL Collector multi-backend fan-out — ADR-0004 Phase 3, explicitly deferred.                                                                                                                                                                                                                                                                                                   |
| Won't    | Failure-mode classifier — Phase 8 (`phase-8-failure-taxonomy`).                                                                                                                                                                                                                                                                                                                 |
| Won't    | Streamlit dashboard — Phase 9 (`phase-9-dashboard`).                                                                                                                                                                                                                                                                                                                            |
| Won't    | Re-hydrating corpus chunk content for retrieval spans in Phase 7 — deferred to the `--enrich-from-index` Could seam.                                                                                                                                                                                                                                                            |
| Won't    | Any changes to the eval runner or `EvalRecord` schema — the exporter is purely additive over the JSONL; no eval-path code is touched. Widening `EvalRecord` to store chunk content/scores would touch ADR-0007 and is out of scope.                                                                                                                                             |
| Won't    | Langfuse cloud / managed tier — self-hosted only (ADR-0004 OSS/self-host requirement).                                                                                                                                                                                                                                                                                          |

---

## Resolved Decisions (2026-05-27)

User reviewed the Open Questions and made the calls below. These **supersede conflicting
details above**; `/define` folds them into clean requirements.

**Tool — Arize Phoenix, not Langfuse (resolves Q1; overrides Decision 5).**
The deployed observability backend is **Arize Phoenix**. Rationale: the dev machine is an
8 GB MacBook Air running concurrent workloads; the Langfuse self-host stack (ClickHouse +
Postgres + Redis + MinIO, ~4–6 GB) is infeasible alongside daily work. Decision 5's
"validate-first spike" (Approach B) is **not executed** — the choice is made by
high-confidence resource analysis and documented honestly as a _reasoned decision_, **not**
as a failed empirical test. Phoenix is the ADR-0004 pre-justified runner-up; the OTEL-GenAI
wire format keeps the schema identical. This supersedes the Langfuse-specific framing in
Decisions 1–2, Decision 5, and Scope — the exporter targets Phoenix (OTEL/OpenInference
spans + Phoenix score write-back), and the connection config adjusts accordingly. ADR-0004
is **accepted** with deployed tool = Phoenix and a note explaining the hardware-driven
adoption of the runner-up.

**Deployment & pinning — single Phoenix container (resolves Q2; Option B).**
`docker-compose.yml` with **one** `arizephoenix/phoenix` container, image pinned to a
specific version tag (never `:latest`), persistence via a mounted **SQLite** volume. No
Postgres (over-engineering for a replay demo). Keeps the exit demo `docker-compose up`
identical, far lighter than Langfuse would be. `/design` pins the exact stable version tag.

**Cost = None handling — honest propagation (resolves Q3; Option A).**
`cost_usd=None` means _unknown_, never _zero_. Per span: omit the cost field if None (never
write 0). Trace-level total: compute only if **both** generation and judge costs are known;
if either is None, omit the total. Same "N/A never 0" convention as the HTML report. The
exporter handles None **defensively regardless** of any upstream change — it reads an
external JSONL artifact and must not assume the producer validated.

**Connection config — env var + optional override (resolves Q4; Option A+).**
The exporter reads the Phoenix endpoint from the native env var `PHOENIX_COLLECTOR_ENDPOINT`
(default `http://localhost:6006`), with an optional `--endpoint` CLI flag that overrides it.
Self-hosted local Phoenix needs **no credentials**; if auth is ever added, the key comes
**only** via env var — never a CLI flag (shell-history leak) or committed YAML. Keeps
`clone → docker-compose up → make export-traces` working with zero configuration.

**Results path — Make variable with default (resolves Q5; Option A).**
`make export-traces` uses `RESULTS_FILE ?= results/baseline.jsonl` (default = the canonical
baseline artifact), overridable in one line (`make export-traces RESULTS_FILE=...`). Chains
cleanly with `make eval-baseline`. **`/define` to-do:** cross-check with the Phase 6 gitignore
decision — for the exit demo to run cost-free (no eval re-run), a `baseline.jsonl` must be
committed, but `results/` is currently gitignored. `/define` reconciles whether a baseline
JSONL (or a small sample) is committed for the cloneable demo.

**Backlog (ADR-0007 amendment, NOT Phase 7) — fail-loud at pre-flight.**
Upstream improvement raised in review: the eval runner should **validate at config-load**
that every model has a price entry and **refuse to start** if not (fail fast, before any
spend), and require local/free models to declare an explicit `$0` price (so "free" is
_declared_, not _unknown_). That would let `cost_usd` become non-optional at the source. It
touches ADR-0007 (accepted) + the Phase 6 runner, so it is **out of Phase 7's
additive-exporter scope** — logged as a separate `fix/` + ADR-0007 amendment. It does **not**
replace the exporter's defensive None handling (boundary robustness).

---

## Open Questions

> **All five open questions are resolved** — see § Resolved Decisions. The questions below are
> retained as the historical record of what `/define` had to close.

**Q1 — What is the Phoenix-fallback trigger threshold?**
If ClickHouse on Docker Desktop exceeds X GB RAM (or the stack OOMs on first ingest),
the phase pivots to Arize Phoenix. The trigger must be named concretely before implementation
starts — otherwise the footprint-first spike has no pass/fail criterion. `/define` must
specify the threshold (e.g., "if ClickHouse alone exceeds 3 GB resident set, or if the
full stack cannot start cleanly, switch to Phoenix").

**Q2 — Which Langfuse v3 docker-compose version and image tags to pin?**
The SPRINT.md and ADR-0004 describe the components but do not pin versions. The archived
deep-research file may reference a stale stack. `/define` must specify: pull the official
Langfuse docker-compose at a pinned release tag, or derive a minimal compose from scratch;
which exact `LANGFUSE_*` env vars are required for a functional self-host. This closes the
committed `infra/langfuse/docker-compose.yml` content.

**Q3 — How should the exporter handle `cost_usd=None` on generation or judge spans?**
`CallStats.cost_usd` is `float | None`. `cost_details` in Langfuse accepts numeric values.
Options: (a) skip `cost_details` entirely if any component is None; (b) include only the
components that are present. `/define` must pick one and ensure `$0.00` is never written
in place of a genuinely absent cost (consistency with the HTML report's "N/A not 0"
convention).

**Q4 — Credential passing: env vars, CLI flags, or config YAML?**
The Langfuse client requires `public_key`, `secret_key`, and `host`. Env vars
(`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`) are the Langfuse-native
default and keep secrets out of CLI history. A config YAML is consistent with the runner's
`RunConfig` pattern but adds a file to manage. `/define` picks the convention so the
Makefile target and test harness can be written unambiguously.

**Q5 — Default `--results` path for `make export-traces`?**
Phase 6 produces `results/baseline.jsonl` (or a run-id-suffixed path). `/define` must
pin whether `make export-traces` hardcodes `results/baseline.jsonl` or reads a `RESULTS_FILE`
variable, so the `make eval-baseline → make export-traces` workflow is reproducible for a
reviewer running both targets in sequence.

---

## Suggested ADRs

**ADR-0004 — Accept** (status change "proposed" → "accepted"). The acceptance note appended
to `docs/adr/0004-observability-tool.md` should record: the tool validated (Langfuse or
Phoenix), hardware context, docker-compose version pinned, and any deviation from the
proposed decision (e.g. Phoenix adopted as primary if Langfuse OOMs). No new ADR number;
the existing file gets a status update and an "Acceptance Note" section.

**No new ADRs are needed for this phase.** The exporter architecture, span tree shape, and
idempotency strategy are implementation details within the boundary ADR-0004 already defines.
ADR-0008 (failure-mode taxonomy schema) belongs to Phase 8. Widening `EvalRecord` would
touch ADR-0007 — that is explicitly Won't for this phase.

**Backlog — ADR-0007 amendment (not Phase 7).** Require every config model to declare a price
(explicit `$0` for local/free models) and validate at the runner's pre-flight, failing fast
before any spend; this makes `cost_usd` non-optional at the source. Raised during this review;
out of the additive-exporter scope (touches ADR-0007 + the Phase 6 runner). Tracked as a
separate `fix/`. See § Resolved Decisions.

---

## Next Step

→ `/define sprint-3/phase-7-tracing`
