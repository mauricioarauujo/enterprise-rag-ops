# SPRINT 6: Full Trace Legibility — A Failed Trace Explains Itself

**Sprint:** sprint-6 | **Date:** 2026-06-02 | **Status:** closed

## Goal

Sprint 5 made the **retrieval** half of a Phoenix trace legible — clicking a failed trace
shows the retrieved-doc content. But the chain, generation, and judge spans still carry only
metadata: there is no question text, no generated answer, and no judge reasoning on the spans,
so "why did this question fail?" is still only half-answerable visually. This sprint closes
that gap end-to-end — a single failed trace should let a reviewer read the **question**, the
**answer**, the **retrieved evidence**, and the **judge's verdict reasoning** without leaving
Phoenix. The work splits along a hard data boundary: question + answer are already available
(no re-run), while judge reasoning + the generation input prompt are not persisted today and
require an `EvalRecord` schema change and a fresh eval sweep.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Slug                            |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| 17    | **Question + answer legibility (no re-run).** Hydrate the generated answer (`record.answer`, already persisted) onto the generation span, and the **question text** — joined from gold via `load_questions` at the export/CLI boundary, the same way `rag-triage` does — onto the chain span, using the OpenInference `input.value` / `output.value` (or `llm.*_messages`) convention. Consumes only already-published artifacts (results JSONL + gold); **no schema change, no re-run.** The cheap, immediate win that lands most of the legibility.               | `phase-17-qa-legibility`        |
| 18    | **`EvalRecord` schema extension for judge reasoning + generation input (ADR).** Decide and record what to persist so the judge's verdict and the generation's input become inspectable — the judge `per_fact` / `per_citation` verdicts (or a compact rationale summary) and the generation input prompt — **against** the ADR-0007 clone-footprint decision that deliberately excluded them. This is a schema + writer change plus the footprint trade-off call. **Write ADR-0010** (amends ADR-0007). No hydration yet — this phase makes the data _persistable_. | `phase-18-evalrecord-reasoning` |
| 19    | **Re-run + hydrate the full trace.** Re-run the eval sweep on the extended schema to populate judge reasoning + generation input (the hardware-constrained step — reuses the existing eval-baseline recipe), then hydrate them onto the judge and generation spans and verify a **fully legible** failed trace end-to-end in Phoenix (question → evidence → answer → judge verdict). Closes the sprint goal.                                                                                                                                                        | `phase-19-full-trace-hydration` |

Planned breakdown, not a contract — each phase refines on `/brainstorm`. **Order leads with the
cheap win:** Phase 17 needs no re-run and delivers most of the visible legibility, de-risking the
sprint. Phases 18→19 are the **costly flex** (schema change + a fresh sweep); if the sprint
tightens, 17 alone is already a real improvement and 18/19 can defer. 18 is a pure decision/data
phase; 19 is the one expensive run.

## Sprint-Wide Knowledge Plan

Two kinds of pre-work, keyed to each phase's decision point — research lands _before_ a phase's
brainstorm/ADR, KB work lands _after_ its ADR:

| Knowledge area                                                                                                                                                  | Kind (research / KB / tech-agnostic) | Action                                                                                                                                         | Timing                                                                      |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| OpenInference LLM-span I/O convention — `input.value` / `output.value` vs `llm.input_messages` / `llm.output_messages`, and what Phoenix's **Info** tab renders | research (light)                     | Context7/Exa on OpenInference span semconv (no `--deep-research`) — confirm the exact attribute keys Phoenix needs to show input/output        | **Before Phase 17 brainstorm** — the unknown is which keys make Info render |
| Gold-question join at the export boundary (`load_questions` → question text by `question_id`)                                                                   | tech-agnostic                        | Coverage holds — `rag-eval` (`eval-record-schema`, questions loader) + the `rag-triage` precedent (`failure-triage`)                           | Reuse at Phase 17; no new research                                          |
| Keep `attributes.py` pure; new boundary reads (gold join) live at the CLI/exporter edge                                                                         | tech-agnostic                        | Coverage holds — `observability/dashboard-phoenix-boundary` (boundary-enrichment rule, added sprint-5) + `span-attribute-mapping`              | Reuse at Phase 17; no new research                                          |
| `EvalRecord` footprint trade-off — persisting `per_fact` / `per_citation` / generation input vs the ADR-0007 clone-overhead exclusion                           | decision → ADR                       | **Write ADR-0010** (amends ADR-0007); design the minimal persistable shape (full verdicts vs compact summary)                                  | **At Phase 18** (decision time)                                             |
| Eval re-run on an extended schema — backward-compat of old JSONL, sweep recipe, cost/host constraints                                                           | tech-agnostic                        | Coverage holds — `rag-eval` runner + the eval-baseline run recipe; ADR-0006 (cassette/replay) for test path                                    | Reuse at Phase 19; no new research                                          |
| Span-attribute-mapping KB — the now-live `input.value`/`output.value` + judge-reasoning attributes                                                              | KB                                   | `/update-kb observability` (refresh `span-attribute-mapping` + `span-tree-shape`) — twice: after Phase 17 (I/O) and after Phase 19 (reasoning) | **After Phase 17 impl**, then **after Phase 19 impl**                       |
| `eval-record-schema` KB — the extended record fields                                                                                                            | KB                                   | `/update-kb rag-eval` (refresh `eval-record-schema` for the new judge-reasoning / generation-input fields)                                     | **After ADR-0010 lands** (Phase 18)                                         |

## Success Criteria

- **Question + answer on the trace (no re-run):** after `rag-export-traces`, a failed trace's
  chain span shows the question text and its generation span shows the generated answer —
  produced from the already-published results JSONL + gold, with **no eval re-run and no schema
  change** (Phase 17). Phoenix's **Info** tab renders them (not just the Attributes tab).
- **Judge reasoning is persistable:** `EvalRecord` carries the judge's verdict reasoning (and the
  generation input) under a footprint-bounded shape, recorded in **ADR-0010** as a deliberate
  amendment to ADR-0007 (Phase 18). Old JSONL still loads (backward-compatible / optional fields).
- **A failed trace explains itself end-to-end:** after the re-run, clicking one failed trace in
  Phoenix surfaces — in order — the question, the retrieved evidence (content), the answer, and the
  judge's per-fact verdict reasoning, with no need to leave Phoenix or read raw JSONL (Phase 19).
- **Purity + opt-in preserved:** `attributes.py` stays import-light (the gold join lives at the
  CLI/exporter boundary, like `--enrich-from-index`); enrichment paths remain opt-in and default-off.

## Risks

- **Re-run is the expensive, host-constrained step.** The eval sweep is the one costly action in
  the sprint (the eval-baseline recipe runs under real hardware/API limits). Quarantine it to
  Phase 19 and front-load all no-re-run value in Phase 17, so the sprint delivers even if the
  re-run slips.
- **Schema bloat reverses a deliberate decision.** ADR-0007 excluded `per_fact` / `per_citation`
  from `EvalRecord` on purpose (clone footprint). Phase 18 must justify the reversal and pick a
  **bounded** shape (a compact rationale summary may beat full verdict lists) — not silently
  re-add everything. ADR-0010 owns this trade-off.
- **Backward compatibility.** Extending `EvalRecord` must keep existing `results/*.jsonl` loadable
  (new fields optional / defaulted), or every prior run and the dashboard break.
- **Observability-coupling regression (carried from Sprint 5).** The gold-question join must stay
  at the CLI/exporter boundary; `attributes.py` must remain pure and unit-testable. Do not pull
  the questions loader into the mapper.
- **Convention drift.** If the wrong OpenInference keys are used, Phoenix shows the data under
  Attributes but the Info tab stays empty (the exact symptom this sprint exists to fix). The Phase
  17 research item must nail the `input.value`/`output.value` (and/or message) keys before impl.

## Retrospective

**Shipped vs planned:** All three planned phases delivered and merged — 17 qa-legibility (#28),
18 evalrecord-reasoning (#29, #30), 19 full-trace-hydration (#31, squash `a51305f`). The sprint
goal is met: **a failed trace explains itself end-to-end**, verified in Phoenix on trace
`qst_0498` (question → retrieved evidence → answer → judge verdict).

**What worked**

- **"Lead with the cheap win" ordering paid off.** Phase 17 (no re-run, no schema change) landed
  most of the visible legibility and de-risked the sprint before the expensive Phase 19 sweep.
- **The hard data boundary drove a clean split.** Identifying upfront what was already-available
  (question + answer) vs not-persisted (judge reasoning) made the 17→18→19 decomposition obvious.
- **ADR-0010 honored ADR-0007 instead of reversing it.** The bronze/gold split (verdicts → gold,
  full raw payload → opt-in gitignored bronze) respected the clone-footprint decision rather than
  silently re-adding everything to `EvalRecord`.

**What slipped / scope changes**

- **Phase 19's operational run missed `rag-classify`** → `failure_mode=None` on all 1500 records
  reddened CI. Caught in `/review`, fixed (re-classify + report re-render), and the DESIGN runbook
  patched so it can't recur. Root cause was a runbook gap, not a code bug — **the gate did its job.**
- **The re-run grew 2 → 3 models** (Gemini added as a third generator-under-test, a former backlog
  "closed-loop idea"), which finally exercises the dashboard's real multi-model comparison. Positive
  scope creep, absorbed within the one budgeted sweep.

**Decision recorded for the portfolio narrative:** the **3-layer separation** — aggregate dashboard
→ per-trace Phoenix → ground truth in `rag-inspect` — was affirmed as deliberate. Gold stays out of
traces because traces model runtime (production has no answer key). Surfaced when reviewing whether
to hydrate `expected_doc_ids` onto spans; chosen not to.

## Sprint Close

- **Date closed:** 2026-06-04
- **Phases:** 17 ✅ (#28) · 18 ✅ (#29, #30) · 19 ✅ (#31, `a51305f`). All `REVIEW.md` verdicts ✅ READY.
- **ADRs:** ADR-0010 written + accepted (Phase 18, amends ADR-0007). None pending.
- **KB (all Sprint-6 `/update-kb` done):** `rag-eval` `eval-record-schema` (#30); `observability`
  `span-attribute-mapping` + `span-tree-shape`, `rag-generation` `raw-payload-serialization` (new),
  `rag-eval` `bronze-raw-archive` (new) + `stats-capture-seam` (#31).
- **Backlog generated:** resumable/cached eval sweep on the bronze substrate (own ADR/phase);
  Phoenix native-widget cost/latency fidelity (LOW/cosmetic). Both in `docs/planning/roadmap.md`.
- **Archived:** `.claude/sdd/features/sprint-6/` → `.claude/sdd/archive/sprint-6/`.
