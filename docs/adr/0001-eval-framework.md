# ADR-0001: Eval Framework Choice — Deferred to Sprint 2

**Status:** deferred
**Date:** 2026-05-18

## Context

Phase 2 (Sprint 1) builds the hybrid retriever; the eval framework — RAGAs vs.
DeepEval vs. a custom per-fact judge — has no empirical signal to compare against
until the retriever is in place. Picking one now would be a guess.

## Decision

Defer the eval-framework choice to **Sprint 2**, when the eval harness is the
sprint's primary deliverable. ADR-0002 (retrieval architecture) is the first
substantive ADR.

## Consequences

- The Phase 2 smoke gate uses an inline `Recall@k` check, not a framework — fine
  for one metric on 3 questions; it does not generalize to the Sprint 2 eval
  surface (per-fact judge, abstention scoring, multi-metric reporting).
- Sprint 2 must open this ADR fresh with the candidate matrix (RAGAs / DeepEval /
  custom) and decide based on observed retrieval failure modes.
