# Review: sprint-7/phase-1-escalation-signal — Inference-Time Escalation Signal

**Branch:** `sprint-7/phase-1-escalation-signal` | **Date:** 2026-06-04 | **Verdict:** ✅ READY

## Summary

Phase-1 picks, wires, and validates the cheap-model escalation signal for sprint-7's
cost-aware router. The research-backed logprob signal proved infeasible (Gemini 2.5 returns
`400 "Logprobs is not enabled"`), so the signal pivoted to the model's **verbalized
confidence**, validated on the full 500 questions alongside abstention and retrieval score.
The honest finding: the best signal is weak (hybrid AUROC 0.685, ~54% escalation to catch
most errors). The seam is wired behind the unchanged `Generator` Protocol, the deliverable
ADR-0011 records the measured decision, and `make lint test` is green. Code review returned
READY with two non-blocking nits, both fixed.

## Mechanical Checks

| Step   | Status | Notes                             |
| ------ | ------ | --------------------------------- |
| Format | PASS   | pre-commit prettier/ruff auto-fix |
| Lint   | PASS   | `ruff check src tests` clean      |
| Tests  | PASS   | 294 passed, 17 deselected (live)  |

## Issues

<details>
<summary>⚠️ Stale config header — <code>configs/gemini-confidence.yaml:1</code> — FIXED</summary>

Header was copied verbatim from `gemini-only.yaml` ("Sprint 4 / Phase 10"). Rewritten to
describe the sprint-7 verbalized-confidence validation run + `run_id` rationale.

</details>

<details>
<summary>⚠️ Developer named in stakeholder roles — <code>DEFINE.md:85,91</code> — FIXED</summary>

`(Mauricio)` appeared in two stakeholder bullets. Not a stranger-test violation (no
career/budget content), but anonymised to "Phase-2 `RouterGenerator` author" / "phase-2
go/no-go reviewer" for a cleaner public artifact.

</details>

<details>
<summary>💡 Retrieval AUROC computed on a reduced n (note only) — <code>scripts/signal_validation.py</code></summary>

Retrieval-abstained rows (`retrieval_top_score=None`) are dropped by `_auroc`'s `dropna()`,
so the retrieval AUROC uses fewer than the full test-split n. No practical consequence (the
result is ≈chance, 0.497, and stated as such), but a future reviewer might expect a footnote.
Left as-is; the run had 0 retrieval-abstentions on these 500 so the effect is nil this run.

</details>

## Acceptance Criteria (vs DEFINE.md)

| AC                                                   | Status        | Evidence                                                                                                      |
| ---------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------- |
| AC-1 logprob-availability spike FIRST                | ✅ (pivoted)  | Spike found Gemini 2.5 `400 "Logprobs is not enabled"` → ADR-0011 §1; signal pivoted to verbalized confidence |
| AC-2 `CallStats.confidence_score` optional/defaulted | ✅            | `records.py:33`; `test_records.py` round-trip                                                                 |
| AC-3 Gemini populates confidence; others None        | ✅            | `_parse_confidence`; `test_verbalized_confidence_scenarios`                                                   |
| AC-4 public `Generator` seam unchanged               | ✅            | `interfaces.py` untouched; `generate()` returns bare answer                                                   |
| AC-5 500-q re-run under ceiling                      | ✅            | `results/gemini-confidence.jsonl` 500 rows, ≈$0.64                                                            |
| AC-6 correct-label join                              | ✅ (improved) | same-run `rag-classify` (stronger than the baseline-join the DESIGN specced)                                  |
| AC-7 multi-signal AUROC reported (no bar)            | ✅            | 4 signals; hybrid 0.685 / conf 0.667 / abstain 0.582 / retrieval 0.497                                        |
| AC-8 calibration/test split discipline               | ✅            | seeded 80/20, metrics on test only                                                                            |
| AC-9 separation plot + escalation rate               | ✅            | `escalation-signal-separation.png`; ~54% escalation                                                           |
| AC-10 ADR exists + complete                          | ✅            | `docs/adr/0011-escalation-signal.md`, accepted                                                                |
| AC-11 tests pass, no mocked LLM                      | ✅            | `FakeGeminiClient`/cassette only; 294 passed                                                                  |

## Knowledge Capture Suggestions

| What was learned                                                                                                                                                           | Suggested KB domain               | Action                                                                                                        |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Gemini 2.5 family (flash-lite + flash) rejects `response_logprobs` with `400 "Logprobs is not enabled"`; verbalized confidence is the fallback signal                      | `rag-generation`                  | `/update-kb rag-generation` — operational provider limitation + the Gemini-only confidence-field pattern      |
| Cheap-model verbalized confidence is bimodal/overconfident → weak escalation signal (AUROC ~0.69); signal-validation scaffold (same-run classify → pure-pandas AUROC join) | `rag-eval` / future `rag-routing` | **Defer** — sprint plan lands the router/cascade pattern after phase-2; the cost-per-correct metric ≈ phase-3 |

## KB Staleness

| KB File                                                         | What Changed                                                                                                     | Impact                        | Action                                                                 |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------- |
| `rag-eval/concepts/stats-capture-seam` (+ `eval-record-schema`) | `CallStats` gained `confidence_score: float \| None`                                                             | Field list slightly stale     | `/update-kb rag-eval` — note the optional field (Gemini-only producer) |
| `rag-generation/concepts/structured-output-per-provider`        | `_GeminiResponseSchema` carries a Gemini-only `confidence` field, stripped before `AnswerWithSources` validation | New provider-specific pattern | Fold into the `/update-kb rag-generation` above                        |

## ADR

ADR-0011 (`docs/adr/0011-escalation-signal.md`, accepted) is the phase deliverable — records
the logprob-infeasibility finding, the verbalized-confidence pivot, the seam-widening
decision, the AUROC evidence, the calibration procedure, and the no-hard-bar framing. ADR
index updated (also backfilled the missing 0010 row). No further ADR needed.

## Suggested Next Steps

1. Open the PR for `sprint-7/phase-1-escalation-signal` → `main`.
2. After merge, run the flagged `/update-kb rag-generation` + `/update-kb rag-eval`
   (Gemini-no-logprobs operational fact + `CallStats.confidence_score`).
3. Phase-2 (`phase-2-router-generator`) reads `CallStats.confidence_score` off
   `generate_with_stats` — but with eyes open: ADR-0011 says the signal is weak, so a null
   phase-3 cost result is the honest expectation.
