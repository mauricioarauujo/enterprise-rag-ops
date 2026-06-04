# ADR 0011: Inference-Time Escalation Signal for the Cost-Aware Router

## Status

accepted

## Date

2026-06-04

## Context

Sprint 7 builds a cost-aware router that answers with a cheap generator
(`gemini-2.5-flash-lite`) by default and escalates to a stronger/safer one
(`claude-haiku-4-5`) when the cheap answer is likely wrong. The escalation decision must key
on an **inference-time** signal: the eval judge is offline and post-hoc (ADR-0001), so it
cannot be that signal. Phase 1's job was to **pick the signal, wire it into the cheap-model
generation path, and prove (or disprove) that it separates correct cheap-model answers from
incorrect ones** before phase 2 builds the router on it.

The baseline finding (`docs/analysis/over-abstention.md`) sharpened the constraint: the cheap
model's dominant failure is **confident hallucination** (46 hallucinations vs Claude Haiku's
10; faithfulness 78.6%; abstain-recall 70%). A trigger that fired only on abstention would
miss exactly that failure class. Pre-brainstorm research
(`docs/planning/research/sprint-7-escalation-signal-research.md`) ranked the **cheap-model
first-token logprob margin** as the best zero-shot fit, with abstention as a free secondary
trigger.

## Decision

### 1. The research-backed signal (logprobs) is infeasible on this stack — recorded, not worked around

The RISK-1 phase-0 spike (a live probe, run before finalizing the extraction) found that
**`gemini-2.5-flash-lite` — and the entire usable Gemini 2.5 family — returns
`400 INVALID_ARGUMENT: "Logprobs is not enabled"`** for any `response_logprobs` request, with
or without JSON mode, with or without the top-N `logprobs` flag. Older logprob-capable models
(`gemini-1.5-flash`, `gemini-2.0-flash`) are retired (404). So **neither first-token margin
nor `avg_logprobs` is obtainable** on the cheap model. The logprob signal is recorded as
infeasible rather than forced (e.g. by switching providers, which would invalidate the
baseline risk-profile narrative the sprint rests on).

### 2. Signal: hybrid abstention-OR-verbalized-confidence

The escalation signal is the cheap model's **verbalized confidence** (a `confidence` ∈ [0, 1]
field the model self-reports in its structured output) combined with the **abstention
sentinel** (a `did_abstain_e2e` OR-trigger). The hybrid escalates unless the model is
maximally confident _and_ did not abstain. Self-consistency was ruled out on cost (the 2.7×
cheap/strong price ratio inverts the math); raw retrieval RRF score was validated and rejected
(see §4).

### 3. Seam-widening: the signal rides `CallStats`, not the public Protocol

The confidence number is carried by a new optional field
`CallStats.confidence_score: float | None = None` (`eval/records.py`), populated **only** by
the Gemini path; every other generator and the retrieval-abstain stub leave it `None`. It
persists into `EvalRecord.generation` for forensics/replay with no `EvalRecord` change
(mirrors the `cost_usd: float | None` precedent). The public `Generator` Protocol
(`generate(context_chunks, question) -> AnswerWithSources`) is **byte-for-byte unchanged**
(SPRINT.md success criterion 1) — the router (phase 2) reads the field off
`generate_with_stats`. The verbalized `confidence` lives in the Gemini-only
`_GeminiResponseSchema` mirror and a Gemini-only prompt addendum; it is **stripped before
`AnswerWithSources` validation**, so the shared output contract (answer + sources,
`extra="forbid"`) is untouched.

### 4. Validation evidence (the measured decision)

500-question Gemini-confidence run (`configs/gemini-confidence.yaml`, ≈$0.64, under the $5
ceiling), classified **in the same run** so each confidence is paired with its own answer's
`failure_mode` (`correct = failure_mode == "correct"`; base rate 23.2%). Retrieval scores
captured locally (`scripts/capture_retrieval_scores.py`). AUROC computed pure-pandas
(`scripts/signal_validation.py`, Mann–Whitney U) on a seeded 80/20 test/calibration split,
test split only. Full report + separation plot: `docs/analysis/escalation-signal-validation.md`.

| Signal                            | AUROC (test, n=400) |
| --------------------------------- | ------------------- |
| **hybrid (confidence ∨ abstain)** | **0.685**           |
| verbalized confidence             | 0.667               |
| abstention (answered)             | 0.582               |
| retrieval RRF score               | 0.497 (≈ chance)    |

The verbalized confidence is **bimodal at {0, 1}** — the cheap model is overconfident: among
_answered_ questions its confidence is ≈0.99 whether right or wrong, so the signal's
discriminative power comes mostly from the abstention-correlated zeros, not fine-grained
confidence. This is exactly the overconfidence the research predicted for verbalized
confidence. Raw RRF retrieval score is non-discriminative per-query (research Q4 confirmed).

### 5. Calibration is a procedure, not a magic number

Because the signal is bimodal, a percentile threshold is degenerate (calibration P25 = 0.0).
The recorded operating-point **procedure** is: _escalate unless the model is maximally
confident (== 1.0) and did not abstain._ Implied escalation rate ≈54% (calibration 54.0%,
test 54.2% — stable). Any future threshold is set on a calibration split and never tuned on
the test split that reports the metric (research Q6 / UCCI discipline).

### 6. No hard AUROC bar — phase-2 go/no-go is a human judgment call

Per the DEFINE decision, phase 1 sets **no numeric greenlight threshold**. The numbers above
are the evidence; whether to build the router is a human call at the phase-2 design.

## Consequences

- **The honest verdict:** the best available inference-time signal is **weak** (hybrid AUROC
  0.685 — clearly above chance, but well below the 0.71–0.87 logprobs reach on other tasks
  the research cited), and catching most errors requires escalating ≈54% of queries. A router
  on this signal will erode much of the cheap/strong price gap before it buys quality. This is
  a valid sprint result (SPRINT.md criterion 4): a measured decision, not a vibes-based one.
- **Phase 2 builds with eyes open.** The `RouterGenerator` can still be built (the seam is
  wired and tested) and swept in phase 3 to measure cost-per-correct-answer — but the phase-1
  evidence says the bar for "routing beats the best single model on cost at equal quality" is
  high. A null phase-3 result is now the expected, honest baseline.
- **Seam contract preserved.** No reader, no other generator, and the public `Generator`
  Protocol are unchanged; backward-compatible with every prior `results/*.jsonl`.
- **Provenance.** Supersedes the logprob design in
  `.claude/sdd/features/sprint-7/phase-1-escalation-signal/DESIGN.md` (which carries a pivot
  amendment). Related: ADR-0003 (Generator seam), ADR-0005 (provider matrix), ADR-0007 (eval
  record schema), ADR-0001 (offline judge).
