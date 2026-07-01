# BRAINSTORM: phase-1-escalation-signal — Inference-Time Escalation Signal

**Sprint/Phase:** sprint-7/phase-1-escalation-signal | **Date:** 2026-06-04

---

## Problem Statement

Sprint 7 builds a cost-aware router that answers with `gemini-2.5-flash-lite` by
default and escalates to `claude-haiku-4-5` when a confidence signal indicates the
cheap model is likely wrong. The eval judge is offline and post-hoc — it cannot be
that signal. Phase-1's job is to pick a concrete inference-time signal, validate that
it statistically separates correct cheap-model answers from incorrect ones, and record
the decision as an ADR before phase-2 commits to building on it.

The baseline finding (see `docs/analysis/over-abstention.md`) sharpens the challenge:
Gemini's dominant failure mode is **confident hallucination** (46 hallucinations vs 10
for Claude Haiku, faithfulness 78.6% vs 92.1%). A router that only fires when Gemini
abstains would (a) trigger at most ~30% of the time and (b) be blind to Gemini's
actual failure class. The signal choice must address confident wrongness, not just
self-reported uncertainty.

---

## Suggested Research & KB Work

| Topic                                                        | Coverage                                                                                                                                                                                                                     | Action                                                                       |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Inference-time confidence signals for LLM routers / cascades | **Sufficient** — `docs/planning/research/sprint-7-escalation-signal-research.md` covers 6 micro-researches (Ramirez 2024, UCCI 2026, Soiffer EMNLP'25, Bouchard 2026, semantic entropy, SkewRoute). No re-derivation needed. | Cite the research doc.                                                       |
| Gemini logprob API surface                                   | **Thin** — research confirms Gemini Flash Lite exposes `avg_logprobs` / `response_logprobs` in the response object; our `GeminiGenerator` does not currently read them. Needs a targeted API probe.                          | Wire and confirm during phase-1 validation work.                             |
| Router/cascade pattern in `rag-generation` KB                | **Missing** — the KB has no cascade or `RouterGenerator` entry.                                                                                                                                                              | `/update-kb rag-generation` after phase-2 ADR lands (sprint-wide plan item). |
| Fair cascade evaluation / cost-quality Pareto                | **Sufficient** — research Q6 covers the pitfalls (double-counting, threshold overfitting, single-point reporting).                                                                                                           | Follow Q6 protocol during signal validation.                                 |

No `--deep-research` needed. The pre-brainstorm research doc is the primary source.

---

## Approaches Considered

| Approach                                     | Description                                                                                                                                                                                                                                                         | Pros                                                                                                                                                                                                                                                                            | Cons                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Effort |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A — Abstention sentinel only                 | Escalate whenever `answer == ABSTAIN_ANSWER`. Signal is already live — `did_abstain_e2e` is in `EvalRecord`. No new infra.                                                                                                                                          | Zero implementation cost; already measured in baseline; ties directly to the sprint narrative.                                                                                                                                                                                  | Blind to Gemini's dominant failure: **confident hallucination**. On our baseline, Gemini's abstain recall is only 70% and its hallucination count is 46. A pure abstain trigger would skip ~60% of hallucinated answers entirely. Research Q3 (Zhao 2025) confirms "low uncertainty does not guarantee correctness."                                                                                                                                                                                                                                                                                                | XS     |
| B — Cheap-model logprob / first-token margin | Read `response_logprobs` from the Gemini API response; compute the margin between the top-1 and top-2 token probabilities on the first generated token (or average sequence log-prob). Escalate when margin falls below a threshold calibrated on a held-out split. | Research's best zero-shot fit (Ramirez 2024: beats trained scorers on 25/27 setups; AUROC 0.71–0.87 in medical QA). Near-zero added latency — single generation call. Directly observable from the cheap model's own call without a protocol seam change.                       | Gemini currently returns only `avg_logprobs` at the response level — not token-level first-token margin. `response_logprobs` with token-level detail requires passing `logprobs=True` in `GenerateContentConfig` (needs a targeted Gemini API check). RAG context shifts the logprob distribution vs. closed-book QA, so the AUROC from the literature may not transfer directly — calibration on a held-out split is non-optional. `CallStats` does not yet carry a `confidence` field, so the logprob number must be threaded out of `generate_with_stats` somehow (via `CallStats` extension or a side-channel). | M      |
| C — Hybrid: abstention OR low logprob margin | Escalate when `did_abstain_e2e == True` OR `logprob_margin < threshold`. The abstention branch is free; the logprob branch addresses confident wrongness.                                                                                                           | Catches both failure modes. Abstention trigger costs nothing extra once logprobs are wired. Orthogonal signals reduce the probability that any single calibration failure collapses the router. Research Q3 explicitly recommends pairing abstention with an orthogonal signal. | Slightly more complex threshold logic (one threshold vs. a binary OR). Validation requires checking that the combined signal is better than each alone — not hard but needs discipline. The "or" semantics mean escalation rate is the union; if both signals fire on similar queries, there is little gain over logprob alone.                                                                                                                                                                                                                                                                                     | M      |
| D — Self-consistency / semantic agreement    | Sample N=3–5 generations from Gemini; measure semantic agreement via NLI or embedding cosine; escalate when agreement is below threshold.                                                                                                                           | Strongest signal for open-ended free-form RAG (Soiffer EMNLP'25: target quality at 40% cost). Explicitly training-free.                                                                                                                                                         | N calls = N× Gemini cost before deciding; adds latency proportional to N. At Gemini's $0.64/run and N=3, escalation decision alone costs ~$1.92/run equivalent — more than the strong model. Research ranks this lower for us precisely because the cost math only works when cheap is ≥10× cheaper AND escalation rate is low. Our price gap ($0.64 vs $1.70) is 2.7× — too small for self-consistency to win.                                                                                                                                                                                                     | L      |

---

## Recommended Approach

**Approach C (hybrid: abstention OR low logprob margin), with logprob as the primary
discriminative signal and abstention as a free secondary trigger.**

Rationale, grounded in our numbers:

1. **Approach A alone is insufficient.** Gemini's abstain recall is 70% (it misses
   30% of truly unanswerable questions) and it has 46 hallucinations. A router keyed
   only on abstention would ignore those hallucinations entirely. The pre-research
   doc explicitly flagged the reverted agy ADR for falling into this exact trap.

2. **Approach B (logprob) addresses the blind spot.** Ramirez 2024 (the closest prior
   art) shows first-token margin beats trained scorers zero-shot on 25/27 setups. This
   is the signal to invest in. The implementation cost (wiring `response_logprobs` from
   Gemini + extending `CallStats`) is bounded and localized to `gemini_generator.py` and
   `records.py`.

3. **Adding abstention for free (Approach C) is a strict improvement over B alone.**
   Abstention is already observable; the combined "OR" trigger only adds lines in the
   router's decision logic. If a question causes Gemini to abstain AND the logprob margin
   is high (confident abstention), we should still escalate — the abstain sentinel catches
   that case without requiring logprob calibration to cover it.

4. **Approach D is dominated.** The cost math fails at our price ratio (2.7×). Ruled out.

**Implementation-side note on seam widening:** the logprob number does not need to
change the public `Generator` Protocol. It can be surfaced as an optional field on
`CallStats` (`confidence_score: float | None = None`) populated only by
`GeminiGenerator.generate_with_stats`. The `RouterGenerator` (phase-2) will call
`generate_with_stats` directly (it is already the internal method the runner uses) and
read the field there. The public `generate()` seam is untouched.

---

## Validation Plan (the phase-1 deliverable)

The sprint risk says phase-1 must prove the signal separates correct from incorrect
cheap-model answers **before** phase-2 commits to building on it. The concrete
validation steps:

1. **Load the existing Gemini baseline JSONL** (from the sprint-5/6 eval run). Each
   record already has `failure_mode`, `did_abstain_e2e`, `fact_recall`, and
   `faithfulness_ratio` — these are the ground-truth labels.

2. **Re-run Gemini on the same question set with `response_logprobs=True`** (or
   `logprobs=True` in `GenerateContentConfig`) to obtain token-level log-probabilities
   for each answer. This is a cheap targeted re-run — Gemini only, dev subset (20
   questions), no judge needed. The output: a per-question `(logprob_margin,
correct_label)` table where `correct = (failure_mode == "correct")`.

3. **Compute AUROC** of logprob margin predicting `correct` across the dev set. Report
   the abstention-only baseline AUROC for comparison (`did_abstain_e2e` predicts
   `correct`). If logprob margin AUROC < 0.60, the signal is not discriminative enough
   to build on — flag this as a blocker and surface alternatives before phase-2.

4. **Hold-out discipline.** Split the question set into calibration (~20%) and
   test (~80%) before any threshold inspection. The calibration split sets the
   escalation threshold (e.g., isotonic regression or percentile); the test split
   reports the final discrimination metrics. Never tune on test.

5. **Report.** At minimum: AUROC (logprob alone vs. abstention alone vs. hybrid),
   escalation rate at the chosen threshold, and a separation plot (logprob distribution
   for correct vs. incorrect answers). This goes into the ADR as evidence for the
   signal choice.

---

## Scope (MoSCoW)

| Priority | Item |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| **Must** | Confirm Gemini Flash Lite exposes token-level logprobs via `response_logprobs` in `GenerateContentConfig` (API probe). |
| **Must** | Wire logprob extraction in `GeminiGenerator.generate_with_stats` — add `confidence_score: float                                                                | None`to`CallStats` or as a return side-channel. |
| **Must** | Run validation: re-run Gemini (dev subset, no judge) with logprobs; produce per-question `(logprob_margin, correct_label)` table from existing baseline JSONL. |
| **Must** | Compute and report AUROC for logprob margin, abstention sentinel, and hybrid (OR) against `failure_mode == "correct"` ground truth. |
| **Must** | Apply calibration/test split discipline — no threshold tuning on the test set. |
| **Must** | Draft ADR recording the chosen signal, the validation evidence, and the seam-widening decision (where the confidence number lives). |
| **Should** | Report the escalation rate the chosen threshold implies (to bound phase-2 cost estimate). |
| **Should** | Include a separation plot (logprob distribution: correct vs. incorrect) in the ADR supporting material. |
| **Could** | Evaluate `avg_logprobs` (response-level average) as a fallback if token-level `response_logprobs` is unavailable or returns empty with structured output. |
| **Won't** | Implement `RouterGenerator` (phase-2 work — this phase produces the signal contract only). |
| **Won't** | Threshold sweep / Pareto frontier (phase-3 work — phase-1 picks one operating point for the ADR, not a full sweep). |
| **Won't** | Wire logprobs for Anthropic or OpenAI generators — Anthropic exposes no token logprobs; OpenAI is not the cheap model. Phase-1 is Gemini-only. |
| **Won't** | Self-consistency / semantic agreement signal (cost math fails at our price ratio). |
| **Won't** | Retrieval-score gating as a standalone signal (raw RRF is not query-comparable per Q4; not worth pursuing when logprob is available). |
| **Won't** | Any change to the public `Generator` Protocol seam contract. |

---

## Open Questions

1. **Does `response_logprobs=True` in `GenerateContentConfig` work for structured JSON
   output requests?** Gemini's JSON-schema mode may return a single JSON-blob token,
   making first-token margin meaningless. If logprobs are not available in structured
   mode, the fallback is `avg_logprobs` (response-level) — but it is less discriminative.
   This is the single most blocking feasibility question for Approach C; it must be
   confirmed by API probe before any code is written.

2. **Where does `confidence_score` live in the data model?** Two options: (a) add
   `confidence_score: float | None = None` to `CallStats` in `records.py` — makes it
   visible in `EvalRecord` and persisted; (b) return it as a 4th element from
   `generate_with_stats` without touching `CallStats`. Option (a) persists the signal
   for forensics and replay; option (b) keeps `CallStats` focused on cost/latency.
   Which is the right abstraction boundary?

3. **What AUROC bar counts as "discriminative enough" to greenlight phase-2?** The
   research reports 0.71–0.87 on medical QA benchmarks. Our task (enterprise knowledge
   QA) may calibrate differently. A reasonable minimum bar is AUROC >= 0.65 — below
   this, a random router would be nearly as good. Should this bar be set explicitly in
   the DEFINE acceptance criteria?

4. **Which question split for calibration vs. test?** The baseline was run on 500
   questions. A 20/80 calibration/test split (100 questions calibration, 400 test) is
   the UCCI-recommended ratio. But the dev config runs only 20 questions — is the dev
   subset large enough for a meaningful AUROC, or should phase-1 run on the full 500
   (accepting the API cost)?

5. **Should the ADR record a specific threshold value, or a calibration procedure?**
   Threshold values are dataset- and distribution-specific and will drift if the
   question set changes. Recording the calibration procedure (e.g., "set at the 25th
   percentile of calibration-split logprob margin") is more durable than a hard number.
   The `/define` step should resolve which form the ADR acceptance criterion takes.

---

## Next Step

-> `/define sprint-7/phase-1-escalation-signal`
