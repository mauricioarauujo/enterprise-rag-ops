# SPRINT 4: Polish & Ship (results-first)

**Sprint:** sprint-4 | **Date:** 2026-06-01 | **Status:** closed

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

---

## Retrospective

**Closed:** 2026-06-01 | **Phases shipped:** 10, 11, 12 (3 of 4 planned; 13 consciously deferred).

### Phases shipped vs planned

| Phase | Slug                        | Verdict  | PR  | Outcome                                                                                                                                                                                                                  |
| ----- | --------------------------- | -------- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 10    | `phase-10-gemini-generator` | ✅ READY | #17 | `GeminiGenerator` behind the `Generator` Protocol; `system` Literal → `google`; price entry; cassette; **ADR-0005 amended**; the twice-deferred **`rag-generation` KB built** (debt paid).                               |
| 11    | `phase-11-readme-results`   | ✅ READY | #18 | Published the 1499-record three-way baseline; `rag-inspect` read-only CLI; results-first README; the **AC-8 verification gate** (90.46% of claude-haiku abstentions are genuine generator behaviour, not the 0.45 gate). |
| 12    | `phase-12-writeup`          | ✅ READY | #19 | `docs/analysis/over-abstention.md` — the over-abstention finding walked end-to-end (`qst_0126`), grounded in published evidence.                                                                                         |
| 13    | `phase-13-leaderboard`      | —        | —   | **Skipped → backlog (LOW).** See Scope changes.                                                                                                                                                                          |

### Success criteria — final

- ✅ **Three-way comparison is real** — Gemini runs behind the seam; report + dashboard show three generators; judge held cross-family.
- ✅ **Provider addition localized** — a new generator file + one-line wire + config; runner/judge/observability untouched. ADR-0005 records it.
- ✅ **Clone-to-understand in minutes** — README gives architecture, run path, three-way numbers, headline finding; `make dash` works on a fresh clone.
- ✅ **A specific, reproducible finding is written up** — root cause verified _before_ publication (Phase 11 `rag-inspect` + AC-8), then deepened in the Phase 12 analysis.
- ❌ **Results submitted to the leaderboard** — **not met; consciously deferred** (the one unmet criterion). See Scope changes.

### What worked

- **Finding-before-evidence risk handled exactly as planned.** `rag-inspect` + the AC-8 gate (exhaustive over all 262 records) verified the over-abstention is genuine generator behaviour _before_ the README/writeup claimed it. The highest sprint risk was retired by design, not luck.
- **Results-first ordering held.** Phase 10's third generator produced the evidence (the abstention↔hallucination tradeoff) that Phases 11–12 wrote up; no ship phase starved.
- **agy-implement + Claude-review split paid off.** Token-heavy drafting ran in Antigravity/Gemini; Claude's review caught real defects every time — a personal-budget stranger-test leak in Phase 11's DESIGN, and absolute `file:///Users/...` link leaks + a stray `cache/` dir in Phase 12. The review gate, not the draft, protected quality.
- **Carried KB debt paid at its ripest moment.** `rag-generation` (twice-deferred) was built when three concrete providers made the multi-provider pattern real.

### What slipped / could improve

- **Recurring `agy` artifact friction.** Each `agy` run introduced a stray artifact that review had to clean (Phase 12: a local-path link leak + a `cache/` dir, now gitignored). Approaching the ≥2 threshold for a harness guardrail — a stranger-test grep (`/Users`, `file:///`) in the `/review` checklist would catch this mechanically. Logged as a watch item, not yet built.
- **Phase 13 mis-scoped at planning.** It was framed as a same-effort "email Joachim" step, but it is outward-facing, third-party-dependent, and only credible _with_ Onyx's official `answer_evaluation` scorer — real engineering that collides with the no-re-runs guard. Better surfaced late than shipped half-baked.

### Scope changes

- **Phase 13 (leaderboard) skipped and backlogged (LOW priority).** Decision (2026-06-01, with the user): emailing our custom-judge numbers without the official Onyx scorer doesn't hold up, and integrating that scorer is real effort against the no-re-runs guard and a tight budget — for a roadmap "(Stretch)" goal. The core portfolio value shipped in Phases 10–12. Recorded in `docs/planning/roadmap.md` § Backlog. The LinkedIn cross-post (Phase 12) was likewise kept out of tracked scope as a personal follow-on.

## Sprint Close

### Knowledge-feedback loop (sprint aggregate)

- **Knowledge capture — DONE in-sprint.** The one substantive item — `/new-kb rag-generation` (Phase 10) — was built and committed in PR #17 (`concepts/{generator-seam, structured-output-per-provider, per-provider-token-accounting}`, `patterns/add-a-generator`). Phase 11's optional "read-only inspect CLI" pattern was judged low-value and **not** built (raise only if a third such CLI appears). Phase 12: none. **No outstanding `/new-kb` / `/update-kb`.**
- **KB staleness — CLEAN.** Phase 10's three `rag-eval` staleness items (`multi-model-runner`, `stats-capture-seam`, `eval-record-schema` gaining `google`) were fixed within that phase's review. Phases 11–12 changed no documented API/enum/constraint. Nothing outstanding.
- **ADR sweep — CLEAN.** **ADR-0005 amended** (provider matrix → third generator family, independence restated, schema-dialect note) in Phase 10. No new ADRs warranted: Phases 11–12 cite existing ADRs and make no durable architectural decision; the Phase 13 skip is a scope/planning call (backlog), not an ADR.

### Archive

`.claude/sdd/features/sprint-4/` → `.claude/sdd/archive/sprint-4/` (joins sprint-1, sprint-2, sprint-3).

### Entry point for the next sprint

The substrate + eval + observability + public artifact are all shipped. Open items carried forward: (1) the leaderboard submission (backlog, LOW, gated on the official scorer); (2) the `/review` stranger-test grep guardrail (watch item); (3) the closed-loop ideas in `docs/planning/roadmap.md` § Backlog (`rag-triage` → GitHub Issues, `--enrich-from-index` Phoenix hydration). Next sprint TBD — `/sprint-start sprint-5` when scoped.
