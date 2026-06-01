# SPRINT 3: Observability

**Sprint:** sprint-3 | **Date:** 2026-05-26 | **Status:** closed (2026-06-01)

## Goal

Turn the per-call eval records into an **observable** system. Every question's
retrieval → generation → judge pipeline becomes a traced span tree with token cost and
latency; a classifier tags _why_ each answer failed (retrieval miss, hallucination,
formatting, abstention error); and a dashboard surfaces traces, cost rollups, and the
failure-mode breakdown. The bar: a reviewer opens a failed trace and sees, at a glance,
what the system did, where it broke, and what it cost.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Slug                       |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| 7     | Tracing: stand up self-hosted Langfuse (docker-compose); an exporter replays the Phase 6 eval JSONL into it as OTEL-GenAI span trees (deterministic score IDs as idempotency keys). **Accept ADR-0004** by validating against the running deployment. _(Shipped 2026-05-30: deployed tool = **Arize Phoenix** per ADR-0004 Acceptance Note — hardware rationale, single SQLite container, OTel-GenAI wire format unchanged. Idempotency is reset-and-replay, not deterministic seed — Phoenix has no upsert-by-seed primitive.)_ | `phase-7-tracing`          |
| 8     | Failure-mode taxonomy: a rule-based classifier over `EvalRecord` aggregates + gold tags each answer (retrieval miss / hallucination / formatting / abstention error / correct). Write **ADR-0008** (taxonomy schema)                                                                                                                                                                                                                                                                                                             | `phase-8-failure-taxonomy` |
| 9     | Streamlit dashboard: traces explorer + cost rollups (per model / category / cycle) + failure-mode breakdown, reading the same JSONL artifact                                                                                                                                                                                                                                                                                                                                                                                     | `phase-9-dashboard`        |

Planned breakdown, not a contract — each phase refines on `/brainstorm`.

## Sprint-Wide Knowledge Plan

Two kinds of pre-work, keyed to each phase's decision point — research lands _before_ a
phase's brainstorm/ADR, KB work lands _after_ its ADR. Tech-agnostic knowledge can be
KB'd whenever it stabilizes.

**The headline:** Sprint 3's tool decision is already made. ADR-0004 (Langfuse
self-hosted; Phoenix runner-up; OTEL GenAI wire format) was **drafted in Sprint 2 / Phase 6**
from a consumed Gemini Deep Research pass (`.claude/kb/_research/archive/observability-2026-05-25.md`),
and the Phase 6 `EvalRecord` is already shaped to OTEL GenAI conventions. So the
design-space research is done; the remaining pre-work is implementation-doc grounding
(current Langfuse self-host APIs) and a light taxonomy-schema decision.

| Knowledge area                                                                                                                                                          | Kind                   | Action                                                                     | Timing                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Observability tool choice (Langfuse vs Phoenix vs OTEL→APM)                                                                                                             | research — **done**    | ADR-0004 drafted from Gemini Deep Research (archived); _accept_ in Phase 7 | Decision made in Sprint 2; **accept ADR-0004 at Phase 7** after validating the running deployment        |
| Langfuse self-host wiring — docker-compose footprint, OTLP ingestion, manual-Python instrumentation, `create_score` write-back                                          | research               | Context7/Exa on current Langfuse self-host + Python SDK                    | **Before Phase 7 brainstorm** — grounds the exporter against current APIs (the _what_ is already chosen) |
| Failure-mode taxonomy schema — categories derivable from `EvalRecord` aggregates (`fact_recall`, `faithfulness_ratio`, `retrieval_ranked_ids`, abstention flags) + gold | research (light) → ADR | light Exa scan of RAG failure taxonomies; write **ADR-0008**               | **Before/at Phase 8 brainstorm + ADR-0008** — do not over-survey; the signal is the chosen schema        |
| `observability` KB domain — chosen instrumentation pattern, JSONL→Langfuse exporter, taxonomy schema                                                                    | KB                     | `/new-kb observability`                                                    | **After ADR-0004 accepted (Phase 7) + ADR-0008 (Phase 8)** — documents the decided design                |
| Streamlit dashboard + Langfuse query API                                                                                                                                | tech-agnostic          | Context7 on Streamlit + Langfuse query, as needed at impl time             | Phase 9 (implementation-time; no ADR)                                                                    |

## Success Criteria

- **Local, cloneable observability:** self-hosted Langfuse comes up via docker-compose,
  and the Phase 6 baseline JSONL replays into it idempotently (deterministic score IDs),
  re-runnable without duplicate records.
- **Traceable pipeline:** each question appears as a `retrieval → generation → judge`
  span tree, with input/output tokens, derived cost (USD), and latency on the relevant
  spans, following OTEL GenAI semantic conventions (ADR-0004).
- **Failure attribution:** every answer carries a failure-mode tag (or "correct") from a
  rule-based classifier; false abstentions and spurious citations are distinguishable —
  a reviewer can tell a retrieval miss from a hallucination from a formatting fault.
- **Dashboard:** a Streamlit app shows a traces explorer, cost rollups (per model / per
  category / per cycle), and the failure-mode breakdown, reading the same JSONL.
- **Decisions captured:** ADR-0004 accepted (tool validated against a running
  deployment, not just on paper); ADR-0008 (failure-mode taxonomy schema) written and
  accepted at decision time.
- **The exit demo:** clone → `docker-compose up` → open a failed trace → see _why_ it
  failed (retrieval miss vs hallucination vs format).

## Risks

- **Self-host footprint vs local resources (highest risk).** Langfuse self-host pulls
  ClickHouse + Postgres + Redis — heavy for a constrained dev machine. Mitigations are
  pre-justified in ADR-0004: fall back to **Arize Phoenix** (single-process; the
  tool-agnostic OTEL-GenAI schema makes the swap code-free), or run Langfuse on a larger
  machine. Phase 7 must validate the footprint _before_ committing the exporter — this is
  exactly what defers ADR-0004 acceptance to Phase 7.
- **Taxonomy precision vs available signal.** `EvalRecord` deliberately omits the raw
  per-fact / per-citation verdict lists (storage/clone footprint), so the classifier works
  off aggregates + gold. Fine-grained modes (e.g. _which_ fact hallucinated) may need
  re-deriving from gold, or depend on the deferred `supporting_doc_id` backlog item. Keep
  ADR-0008's taxonomy at the granularity the persisted signal actually supports.
- **Dashboard scope is bottomless.** "Traces + costs + failure breakdown" can balloon into
  a product. Hold to CLI + minimal Streamlit (a project-level OUT-of-scope line); the
  observability layer is non-negotiable, the dashboard polish is the flex.
- **Tool churn after acceptance.** If Phase 7 validation flips ADR-0004 to Phoenix, the
  exporter and Phase 9 query layer must target the runner-up cleanly — the shared wire
  format (OTEL GenAI) is what keeps that a remap, not a rewrite. Don't hard-code
  Langfuse-only assumptions into the dashboard.
- **Carried-forward KB debt — empty `rag-generation` scaffold.** Sprint 2 closed
  (archived; FR-10 gold-aware guard fix shipped in #11), but its retro left one open item:
  `.claude/kb/rag-generation/` is still an empty `concepts/` + `patterns/` scaffold, not
  registered in `_index.yaml`. Phase 8's failure-taxonomy classifier reads generation +
  abstention contracts (single enforced sentinel at gate and generator — ADR-0003 update),
  so `/new-kb rag-generation` is cheapest to pay before Phase 8 brainstorm. Not on the
  Sprint 3 critical path, but the freshest it will ever be.

---

## Retrospective

**Outcome: all three phases shipped ✅ READY, all success criteria met.** The
differentiator layer (observability) is now end-to-end: traced span trees → failure
attribution → an aggregate dashboard, all over the cloneable JSONL.

| Phase | Slug                       | Shipped    | PR  | Verdict  |
| ----- | -------------------------- | ---------- | --- | -------- |
| 7     | `phase-7-tracing`          | 2026-05-30 | #12 | ✅ READY |
| 8     | `phase-8-failure-taxonomy` | 2026-05-30 | #13 | ✅ READY |
| 9     | `phase-9-dashboard`        | 2026-06-01 | #15 | ✅ READY |

(KB domain for Phases 7–8 landed separately in #14.)

### What worked

- **ADR-0004's pre-justified runner-up paid off.** The Langfuse→Phoenix swap at Phase 7
  acceptance was a localized remap, not a rewrite — exactly because the OTEL-GenAI /
  OpenInference wire format was decided up front. The highest sprint risk (self-host
  footprint on 8 GB hardware) resolved cleanly via the planned fallback.
- **The JSONL-as-SSoT spine held across all three phases.** Tracing (replay), taxonomy
  (post-hoc tag), and the dashboard (render) all read the same `EvalRecord` JSONL — no
  re-instrumentation, no schema migration. Phase 9's dashboard reuses
  `generate_report_data` unchanged.
- **Schema forward-compatibility from Sprint 2 was real, not aspirational.** `failure_mode`
  added as an additive `str | None` field; older records parse cleanly.
- **The implement-in-Antigravity split scaled.** Phase 9's implement ran in Gemini against
  the DESIGN contract; Claude stayed orchestrator/reviewer and caught a real env-var drift
  (`PHOENIX_BASE_URL` → `PHOENIX_COLLECTOR_ENDPOINT`) at design time.

### What slipped / scope notes

- **Tool flipped from the ADR-0004 primary (Langfuse) to the runner-up (Phoenix)** at
  Phase 7 acceptance — anticipated and absorbed, but the SPRINT.md plan/success-criteria
  text was written Langfuse-first and read slightly stale through the sprint. Minor; the
  ADR Acceptance Note is the SSoT.
- **Dashboard held to scope.** The "bottomless dashboard" risk did not materialize —
  aggregate-only, deep-linking to Phoenix rather than rebuilding its explorer. Two small
  follow-ups deferred to Sprint 4 (empty-JSONL guard; per-trace deep-link once the Phoenix
  v15 URL shape is confirmed — seam marked `TODO(FR-11)`).

### Carried forward → Sprint 4

- **`rag-generation` KB scaffold is still empty and unregistered** — flagged in the Sprint 2
  retro AND this sprint's risks ("cheapest to pay before Phase 8 brainstorm"), and deferred
  **both** times. Phase 8 shipped fine without it, so it was never on the critical path —
  but it is now twice-deferred KB debt. Decide in Sprint 4: pay it (`/new-kb rag-generation`)
  or formally drop the scaffold.
- **Two dashboard follow-ups** (above) — natural fit for Sprint 4 polish.

## Sprint Close

- **Phase completion:** 3/3 phases shipped with ✅ READY reviews (PRs #12, #13, #15; KB #14).
- **Knowledge capture:** complete. Phases 7–8 → `observability` KB domain (#14: 5 concepts,
  3 patterns). Phase 9 → `observability/patterns/dashboard-phoenix-boundary` (this session).
  No outstanding `/new-kb` / `/update-kb` for Sprint 3 material.
- **KB staleness sweep:** one Low item fixed — `rag-eval/eval-record-schema` now lists the
  `failure_mode` field and cross-references the observability taxonomy that owns it. No
  other drift (`rag-retrieval` untouched; `observability` current).
- **ADR sweep:** all decisions recorded — ADR-0004 **accepted** (Phase 7, Phoenix validated
  against the running deployment), ADR-0008 **written + accepted** (Phase 8, taxonomy).
  Phase 9 correctly added no ADR (presentation layer over ADR-0004/0007/0008).
- **Archived:** `.claude/sdd/features/sprint-3/` → `.claude/sdd/archive/sprint-3/`
  (phase-9 folder renamed `phase-9-dashboard` for naming consistency with phases 7–8).
