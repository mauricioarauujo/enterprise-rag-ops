# SPRINT 5: Closed-Loop — Eval → Observability → Action

**Sprint:** sprint-5 | **Date:** 2026-06-01 | **Status:** closed (2026-06-02)

## Goal

The harness already produces rigorous eval numbers (Sprint 2) and a trace/dashboard view
of what the system did (Sprint 3). What it does not yet do is **act** on its own findings.
This sprint closes that loop: turn the deterministic classified eval output into a triaged,
clustered diagnosis and into drafted GitHub Issues, and make a single failed trace
**legible** end-to-end in Phoenix (readable doc content, not just IDs). The substrate, eval,
and observability layers are done and untouched — this sprint is about turning their output
into action and into a visible root cause.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Slug                          |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| 14    | **`rag-triage` core (cluster + diagnose).** A new `rag-triage` CLI that reads the already-classified eval JSONL (`rag-classify` output), clusters by `failure_mode` × `category`, joins gold (`load_questions`) for context, and emits a deterministic, machine-readable triage report surfacing and quantifying the dominant pattern (e.g. over-abstention). Pure data step — no eval re-run, no external side effects, fully offline-testable.                                                | `phase-14-rag-triage`         |
| 15    | **Triage → GitHub Issues (drafted action).** Take the triage clusters and draft GitHub Issues — one per dominant failure cluster, grounded in the cluster stats + a concrete `rag-inspect`-style example. **Dry-run / draft by default**; real issue creation is explicit opt-in and **idempotent** (a cluster-signature dedup key so re-runs don't spam duplicates). Decision point — agent/LLM-draft vs template, and the GitHub integration boundary (`gh` CLI vs REST). **Write ADR-0009.** | `phase-15-triage-to-issues`   |
| 16    | **`--enrich-from-index` Phoenix hydration.** Activate the stubbed FR-12/AC-14 seam (`observability/attributes.py:39`): hydrate retrieved-doc **content** (+ score) onto the retriever span so "click a failed trace → see why" is visual end-to-end in Phoenix. Opt-in via flag; the heavy index import stays at the exporter/CLI boundary so `attributes.py` keeps its zero-lock-in, unit-testable shape (NFR-3).                                                                              | `phase-16-phoenix-enrichment` |

Planned breakdown, not a contract — each phase refines on `/brainstorm`. Two threads:
14→15 is the **action** loop (the headline senior signal); 16 is the **legibility** of a
single trace and is independent. Order leads with the action loop; Phase 16 is the flex —
if 14/15 overrun, 16 is the one to cut, and it loses nothing the other two depend on.

## Sprint-Wide Knowledge Plan

Two kinds of pre-work, keyed to each phase's decision point — research lands _before_ a
phase's brainstorm/ADR, KB work lands _after_ its ADR:

| Knowledge area                                                                                                                                           | Kind (research / KB / tech-agnostic) | Action                                                                                                                            | Timing                                                                                                         |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Triage clustering over classified JSONL — grouping by `failure_mode` × `category`, joining gold, aggregate stats                                         | tech-agnostic                        | Coverage holds — `rag-eval` (`eval-record-schema`, `retrieval-metric-aggregation`) + `observability/failure-taxonomy`             | Reuse at Phase 14; no new research                                                                             |
| GitHub Issues integration — `gh` CLI vs PyGithub/REST, issue **idempotency/dedup** patterns, agent/LLM-draft vs deterministic template, dry-run boundary | research                             | Context7/Exa on `gh` / GitHub Issues API (no `--deep-research`)                                                                   | **Before Phase 15 brainstorm** — the integration + idempotency is the real unknown and the outward-facing risk |
| Triage → issue-drafting design — agent boundary, idempotency key, side-effect safety                                                                     | decision → ADR                       | **Write ADR-0009**                                                                                                                | **At Phase 15** (decision time), not retro                                                                     |
| OpenInference `retrieval.documents.*.document.content` / `.score` convention for hydrated spans                                                          | tech-agnostic                        | Coverage holds — `observability/span-attribute-mapping` (OpenInference conventions already documented)                            | Reuse at Phase 16; no new research                                                                             |
| Observability → retrieval-index coupling when enrichment is activated (keep `attributes.py` pure; hydrate at the boundary)                               | decision (light)                     | Design note in Phase 16 brainstorm; **ADR only if the coupling proves non-trivial**                                               | At Phase 16                                                                                                    |
| `eval-triage` knowledge — the cluster→diagnose→issue pattern and its idempotency contract                                                                | KB                                   | `/update-kb rag-eval` (add `failure-triage` concept + `triage-to-issues` pattern; spin a new domain only if it outgrows rag-eval) | **After ADR-0009 lands** (Phase 15)                                                                            |
| Phoenix doc-content hydration — the activated `--enrich-from-index` path                                                                                 | KB                                   | `/update-kb observability` (refresh `span-attribute-mapping` + `dashboard-phoenix-boundary` for the now-live seam)                | **After Phase 16 impl**                                                                                        |

## Success Criteria

- **Triage is real and deterministic:** `rag-triage` runs on the published classified JSONL,
  clusters by `failure_mode` × `category`, and surfaces + quantifies the dominant pattern
  (the over-abstention finding) — reproducibly, with no eval re-run and no network.
- **The loop closes:** triage output produces drafted GitHub Issues, one per dominant
  cluster, each grounded in real cluster stats + a concrete example. Re-running is
  **idempotent** (no duplicate issues); real creation is explicit opt-in, dry-run by default.
  The agent/integration boundary is recorded in **ADR-0009**.
- **A failed trace is legible end-to-end:** with `--enrich-from-index`, clicking a failed
  trace in Phoenix shows readable retrieved-doc **content** (+ score) per doc — not just IDs.
- **No regression to the observability seam:** enrichment is opt-in and `attributes.py` stays
  import-light and unit-testable (NFR-3); the index dependency lives at the exporter/CLI
  boundary, not in the pure attribute mapper.
- **Localized, no re-run:** both triage and enrichment consume already-published artifacts
  (classified JSONL, gold, corpus) — neither requires re-running the expensive sweep.

## Risks

- **Gadget risk.** Agent-drafted issues are only a signal if grounded in a _real_ finding.
  Lead Phase 15 with the existing over-abstention cluster — cluster → draft → (opt-in) create,
  not a generic issue bot. If the issues aren't grounded in real data, the loop is a demo.
- **Outward-facing side effects.** Creating GitHub Issues is a real, hard-to-reverse external
  action. Default to **dry-run / draft**; require explicit opt-in for live creation; make it
  **idempotent** via a cluster-signature dedup key so re-runs never spam duplicates.
- **Observability coupling regression.** Activating `--enrich-from-index` risks pulling the
  retrieval index (BM25/LanceDB) into the observability path and breaking the pure,
  unit-testable `attributes.py` (NFR-3). Keep the heavy import at the exporter/CLI boundary;
  the attribute mapper must stay dependency-light. Enrichment is opt-in, never the default.
- **No-re-runs guard.** Both threads must consume the already-published JSONL / corpus — never
  trigger a fresh sweep (hardware-constrained). Triage and enrichment are read-only over eval
  output.
- **Scope creep into a bot.** "Agent drafts issues" can balloon into a full automation product.
  Hold the line: cluster → draft markdown → create issue (dry-run default). Phase 16 (legibility)
  is the flex; the action loop (14→15) is the sprint's point.

---

## Retrospective

**Closed:** 2026-06-02 | **Verdict:** all 3 phases shipped ✅

### Phases shipped vs planned

| Phase | Slug                                    | Verdict  | PR(s)       |
| ----- | --------------------------------------- | -------- | ----------- |
| 14    | `rag-triage` core                       | ✅ READY | #21         |
| 15    | triage → GitHub Issues + ADR-0009       | ✅ READY | #22         |
| 16    | `--enrich-from-index` Phoenix hydration | ✅ READY | #24, KB #25 |

All planned phases shipped. No phase cut — Phase 16 (the designated flex) made it in.

### What worked

- **The action loop is grounded, not a gadget.** `rag-triage` → `rag-issues` runs on the
  real classified `baseline.jsonl` and drafts a GitHub Issue anchored in the actual
  over-abstention cluster (`abstention_error`/`basic`, 201 records / 13.4%) with an idempotency
  marker — exactly the anti-gadget bar the Risks section set.
- **Outward-facing safety held.** Issue creation is dry-run/draft by default; live `--create`
  is explicit opt-in and idempotent via a body-marker fingerprint (ADR-0009).
- **The observability coupling regression was avoided.** Phase 16 activated `--enrich-from-index`
  with the heavy corpus read at the CLI/exporter boundary; `attributes.py` stayed import-light and
  signature-stable (NFR-1/NFR-3 intact).
- **No-re-run guard respected throughout.** All three phases consumed already-published artifacts
  (classified JSONL, gold, corpus) — zero fresh sweeps.
- **Knowledge loop fully discharged at close.** ADR-0009 landed (and the pre-existing ADR-0008
  index gap was backfilled); both scheduled KB captures shipped — `/update-kb rag-eval` (#23,
  `failure-triage` + `triage-to-issues`) and `/update-kb observability` (#25, the now-live
  `.content` seam). No outstanding KB/ADR debt.

### What slipped / scope changes

- **None against the plan.** Phase order and scope held. The only post-review polish was folding
  the three non-blocking phase-16 nits into the impl branch before merge.
- **Legibility is partial by design — and surfaced a follow-up.** Phase 16 delivered _retrieval_
  legibility (doc content on the retriever span) but the chain/generation/judge spans still carry
  only metadata: the question text isn't on the chain span, `record.answer` isn't on the
  generation span, and judge reasoning / generation input aren't persisted in `EvalRecord` at all.
  Validated visually in Phoenix on `qst_0493`. This is the seed for the **next sprint** (full
  trace legibility) — see Sprint Close.

## Sprint Close

- **Knowledge capture:** complete. No further `/new-kb` / `/update-kb` outstanding — the two
  scheduled captures (rag-eval #23, observability #25) and ADR-0009 all landed before close.
- **KB staleness sweep:** clean. The observability `.content` seam (the one stale spot) was
  refreshed in #25; no other domain the sprint touched is outdated.
- **ADR sweep:** clean. ADR-0009 (triage→issues) recorded; ADR-0008 index gap backfilled. No
  architectural decision left unrecorded.
- **Next sprint (decided 2026-06-02):** **full trace legibility** — hydrate the question text
  (gold join) → chain span, `record.answer` → generation span, and judge reasoning + generation
  input prompt onto their spans. Scope chosen: **full legibility** (incl. judge reasoning +
  generation input), which requires an `EvalRecord` schema change and re-running the eval sweep.
  ⚠️ Likely overflows a single sprint's budget — `/brainstorm` should propose splitting into a
  cheap export-only phase (answer + question, no re-run) and a costlier schema-change + re-run
  phase. Open via `/sprint-start` after this close.
