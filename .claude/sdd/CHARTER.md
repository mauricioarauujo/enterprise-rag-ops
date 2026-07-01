---
charter: enterprise-rag-ops
last_updated: "2026-07-01"
---

# enterprise-rag-ops — Charter (L0 Intent)

> The product's **north-star + risk posture** — the single L0 Intent source that
> direction reviews, phase Impact/KPI lenses, and risk-tier gating render from (never
> re-invented per phase). Long-lived: a north-star change is an ADR-level decision.
>
> _Authored at kbind adoption (2026-07-01) from repo signals (`AGENTS.md` § Project
> Purpose, `README.md`, ADRs 0001–0012). Ratify or revise via `/kbind:charter`._

## 1. North-star / mission

A production-grade **RAG evaluation and observability harness** whose eval evidence is
trustworthy enough to drive real decisions (model routing, cost trade-offs, failure
triage) — the differentiator is the harness around the RAG, not the RAG itself.

## 2. Success definition / KPI lens

- **Lens:** trustworthiness + legibility of eval evidence.
- **KPI(s):** per-fact recall/precision and faithfulness of the judged baseline; judge
  determinism (strict schema, discrete verdicts); cost-per-answer accounting that adds
  up; failure-mode coverage of the taxonomy.
- **Measurement:** the published baseline sweep (`results/baseline.{md,html,jsonl}`),
  `make lint test` + CI, and the Phoenix trace/score dashboards (Sprint 3+).

> Phase-level Impact/Outcome derives from this — don't re-author it per phase.

## 3. Risk-tier definitions (this product's R1 / R2 / R3)

| Tier                                                             | This product's surfaces                                                                                                                                                                                                                    |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **R1** — read-only / reversible                                  | cassette-replay eval runs, retrieval smoke, report rendering, trace reads, KB/doc reads                                                                                                                                                    |
| **R2** — normal mutating (default)                               | code edits, commits, branch PRs, index rebuilds, **live-API eval sweeps** (spend real provider budget — announce cost before a full sweep)                                                                                                 |
| **R3** — irreversible / destructive / security- or PII-sensitive | refreshing the **published baseline** (an outward-facing claim), triage → GitHub issue creation (outward-facing; dry-run default per ADR-0009), deleting `data/`/`results/` artifacts, `.env` secrets handling, history rewrite/force-push |

## 4. Direction question + non-negotiables

- **The one direction question:** _"Does this deliverable make the eval/observability
  evidence more trustworthy or more legible — rather than merely adding RAG features?"_
- **Non-negotiables / anti-goals:**
  - Never mock the LLM API in eval tests — cassette/replay only (ADR-0006).
  - Never refresh the published baseline from a partial or unverified sweep.
  - Triage-to-issues stays dry-run by default (ADR-0009).
  - Minimal scope, clean seams — no speculative infrastructure (AGENTS.md § Engineering
    Behavior).
