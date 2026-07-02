# SPRINT 9: Architecture Documentation & Phoenix Deep-Dive

**Sprint:** sprint-9 | **Date:** 2026-06-19 | **Status:** active

## Goal

The harness is feature-complete (Sprints 1–8) but under-documented at the **system-narrative**
level: a reader can follow individual modules, but there is no single artifact that traces a
question end-to-end, records _why_ each differentiator is built the way it is, or maps the
project onto the Phoenix-native experimentation model it deliberately does **not** use. This
sprint produces those comprehension artifacts — a data-flow walkthrough, design-rationale notes
for the eval/observability internals, and a Phoenix deep-dive that includes a native-experiment
demo and an ADR recording the custom-harness-vs-Phoenix-native decision.

No production behaviour changes: this sprint adds documentation, one ADR, and one small,
isolated demo. The custom harness is **not** rewritten onto Phoenix-native primitives.

## Phase Breakdown

Pedagogical order: **foundation → internals → Phoenix** (the role of Phoenix is clearest once
the data flowing into it is understood). Each phase produces a reviewable artifact that is
validated against the code.

| Phase | Intent                                                                                                                                                                                     | Slug                            |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------- |
| 1     | End-to-end data-flow walkthrough: trace one question ingest → retrieval → generation → judge → `EvalRecord` → report → Phoenix trace, naming every seam.                                   | `phase-1-data-flow-walkthrough` |
| 2     | Eval/observability internals design notes: per-fact judge + `supporting_doc_id`, failure taxonomy cascade, `root_cause`, cost accounting, the mapper/exporter seam — each with its _why_.  | `phase-2-internals-rationale`   |
| 3     | Phoenix deep-dive: REST + GraphQL (the APIs the exporter already uses), a small Phoenix-native experiment demo over the 500-question set, and ADR-0013 "custom harness vs Phoenix-native". | `phase-3-phoenix-deep-dive`     |

## Sprint-Wide Knowledge Plan

This sprint is itself a knowledge-capture exercise; its outputs land in `docs/architecture/`
and `docs/adr/`, not the KB. The Phoenix-native experiment path (Datasets → Experiments →
Evaluators) is the one area where current Phoenix docs should be pulled (Context7) before
phase 3, since it is the part of Phoenix the project does not yet exercise. No new code module
KB is anticipated.

## Success Criteria

1. `docs/architecture/data-flow.md` traces one question end-to-end across all seams and is
   accurate to the current code (every named hop resolves to a real module/function).
2. A design-rationale doc covers the eval/observability differentiators (per-fact
   `supporting_doc_id`, taxonomy cascade, `root_cause`, cost-per-correct, mapper/exporter
   purity seam), each with the decision _and its rationale_, cross-linked to its ADR where one
   exists.
3. A runnable Phoenix-native experiment demo exists over the EnterpriseRAG-Bench set
   (isolated; does not touch the offline harness), with a short README on how to run it.
4. **ADR-0013** records the custom-harness-vs-Phoenix-native decision: what Phoenix-native
   offers, what the custom harness offers (offline/no-lock-in/CI-friendly, domain logic the
   framework wouldn't give for free), and why custom was chosen — written so a reviewer can
   evaluate the trade-off.
5. `make lint test` stays green; no production module under `src/` changes behaviour (docs +
   one isolated demo + one ADR only).

## Risks

- **Scope creep into a rewrite.** The temptation in phase 3 is to port the harness onto
  Phoenix-native Datasets/Experiments/Evaluators. That would erase the project's differentiator
  and is an explicit **Won't** — the demo is additive and isolated, the harness stays as is.
- **Docs drifting from code.** Walkthroughs that aren't checked against the code go stale.
  Mitigation: every named hop/seam in phase 1–2 is verified against the actual module before it
  is written down (the artifacts cite `file:function`).
- **Tight budget.** ~5h/week; the deep, guided authoring style makes this slower than a feature
  sprint. Phase 3's demo is the cut line if time runs short — phases 1–2 carry the core
  comprehension value and are self-contained.
