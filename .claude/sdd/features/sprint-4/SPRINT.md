# SPRINT 4: Polish & Ship (results-first)

**Sprint:** sprint-4 | **Date:** 2026-06-01 | **Status:** active

## Goal

Turn the built eval + observability substrate into a **public, reviewable artifact**.
First strengthen the evidence — add a third generator-under-test (Gemini
`gemini-2.5-flash-lite`) so the multi-model report is a genuine three-way comparison,
not single-model — then make the system legible: a README a fresh clone understands in
minutes, a written analysis of a specific reproducible finding, and the results published
to the EnterpriseRAG-Bench leaderboard. The substrate is done; this sprint is about
evidence and communication, not new capability.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Slug                        |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| 10    | **Third generator — `GeminiGenerator`.** A new file implementing the `Generator` Protocol (`generation/interfaces.py`) for `gemini-2.5-flash-lite` + runner/CLI wiring + extend the `system` Literal (`eval/config.py`) to a third family + price-table entry in `configs/baseline.yaml` + `google-genai` dep + a recorded cassette (ADR-0006). **Amend ADR-0005** (provider matrix currently OpenAI/Anthropic/Ollama). Generator-under-test only — never the judge (judge/generator independence). | `phase-10-gemini-generator` |
| 11    | **README + results.** A README pass: architecture + diagram, how-to-run, the published three-way multi-model numbers, and the headline finding (over-abstention). Pull in a small `rag-inspect <question_id>` helper (joins the eval JSONL + gold) to ground the writeup with one concrete failed-question example.                                                                                                                                                                                 | `phase-11-readme-results`   |
| 12    | **Written analysis.** A focused (~1500-word) post on one specific, reproducible finding — retrieval succeeds and hallucination is rare, yet the system over-abstains (abstain precision low). Grounded in the published results and a concrete example from Phase 11.                                                                                                                                                                                                                               | `phase-12-writeup`          |
| 13    | **Publish.** Submit the results to the EnterpriseRAG-Bench leaderboard (maintainer contact in `docs/dataset.md` / roadmap).                                                                                                                                                                                                                                                                                                                                                                         | `phase-13-leaderboard`      |

Planned breakdown, not a contract — each phase refines on `/brainstorm`. Ordering is
**results-first**: Phase 10 strengthens the evidence the later phases write up. If
Phase 10 overruns, the ship phases (11–13) are protected — polish is the flex, the
substrate is non-negotiable and already done.

## Sprint-Wide Knowledge Plan

Two kinds of pre-work, keyed to each phase's decision point — research lands _before_ a
phase's brainstorm/ADR, KB work lands _after_ its ADR:

| Knowledge area                                                                                                                                                                                                            | Kind (research / KB / tech-agnostic) | Action                                                      | Timing                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `google-genai` SDK wiring — client init, **structured-output forcing** for `AnswerWithSources` (the per-provider unknown, cf. OpenAI `strict` / Anthropic forced tool-use), token-usage accounting, `gen_ai.system` value | research                             | Context7/Exa on `google-genai` (no `--deep-research`)       | **Before Phase 10 brainstorm** — grounds the generator against the current SDK; structured-output is the real risk |
| Provider matrix decision — adding a third cloud family (Gemini) as generator-under-test                                                                                                                                   | decision → ADR                       | **Amend ADR-0005**                                          | **At Phase 10** (decision time), not retro                                                                         |
| `rag-generation` KB domain — the `Generator` seam, structured-output-per-provider pattern, the multi-provider generation contract                                                                                         | KB (carried debt — twice-deferred)   | `/new-kb rag-generation`                                    | **After Phase 10 ADR/impl** — a third provider makes the seam pattern concrete; freshest it will be                |
| Cassette/replay for the new provider's live test                                                                                                                                                                          | tech-agnostic                        | Coverage holds — `rag-eval/cassette-replay-eval` (ADR-0006) | Reuse at Phase 10; no new KB                                                                                       |
| README / writeup / leaderboard                                                                                                                                                                                            | tech-agnostic                        | None — the finding and the system are understood            | Phases 11–13; no KB/research                                                                                       |

## Success Criteria

- **Three-way comparison is real:** `gemini-2.5-flash-lite` runs in the sweep behind the
  `Generator` Protocol; the multi-model report and dashboard show three generators, with
  the judge held cross-family (independence preserved — Gemini never judges).
- **Provider addition is localized:** adding Gemini touched a new generator file + a
  one-line wiring + config, not the runner/judge/observability internals (proves the
  seam). ADR-0005 records the addition.
- **Clone-to-understand in minutes:** the README gives architecture, a run path, the
  published three-way numbers, and the headline finding; a fresh clone can run the
  dashboard and read real results with no infra spin-up.
- **A specific, reproducible finding is written up**, grounded in the published JSONL and
  one concrete example (via `rag-inspect`), with the finding's root cause verified (model
  behaviour vs. a harness/threshold artifact) before it is published.
- **Results are submitted** to the EnterpriseRAG-Bench leaderboard.

## Risks

- **Gemini structured-output forcing differs from OpenAI/Anthropic.** Each provider forces
  JSON/`AnswerWithSources` its own way; the `GeminiGenerator` may need provider-specific
  schema adaptation, and the recorded cassette is the test tax. This is the highest-effort
  unknown — front it with the Context7/Exa research before the brainstorm.
- **Finding-before-evidence.** The over-abstention result must be confirmed as real model
  behaviour, not a harness/abstention-gate artifact (the Sprint 1 0.45 threshold + Python
  short-circuit), **before** it is published as a finding. Phase 11's `rag-inspect` is the
  verification tool; the writeup (Phase 12) depends on that confirmation.
- **Polish is bottomless.** README and writeup can balloon into a product. Hold the line —
  the substrate is done; ship beats completeness. Results-first ordering must not let
  Phase 10 starve the ship phases.
- **Provider independence.** Gemini is a generator-under-test only — wiring it into the
  judge slot would reintroduce the same-family bias ADR-0005 exists to prevent.
- **Carried KB debt finally due.** `.claude/kb/rag-generation/` is still an empty,
  unregistered scaffold (deferred in Sprint 2 and Sprint 3). Phase 10 is its natural
  home; if Phase 10 slips, decide explicitly to pay it or drop the scaffold rather than
  carrying it a third time.
