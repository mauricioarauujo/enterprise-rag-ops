# SPRINT 7: Cost-Aware Routing — Make the Tradeoff Pay Off

**Sprint:** sprint-7 | **Date:** 2026-06-04 | **Status:** closed

## Goal

The multi-model baseline established a finding: three generators with near-identical fact
recall have radically different cost and risk profiles — one is cautious, precise, and
expensive; one is cheap but hallucination-prone; one sits in the middle. This sprint turns
that finding into an **operational mechanism**: a cost-aware router that answers with a cheap
generator by default and **escalates to a stronger one on an inference-time confidence
signal**, then uses the existing eval harness to prove — with numbers — whether routing beats
any single model on **cost-per-correct-answer at equal quality**. The point on display is the
harness paying off: a measured architectural decision, not a vibes-based one.

## Phase Breakdown

| Phase | Intent                                                                                                                                                                                                                                                                                                          | Slug                         |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| 1     | Decide and expose the **inference-time escalation signal** the router keys on (the eval judge is offline, so it cannot be that signal). Candidates: generator abstention sentinel, retrieval score, self-consistency. Validate the signal is discriminative before building on it; record the choice as an ADR. | `phase-1-escalation-signal`  |
| 2     | Implement a **`RouterGenerator`** behind the existing `Generator` Protocol seam — cheap default → escalate to the strong/safe model on the phase-1 signal — and wire it into the runner/config as a system-under-test.                                                                                          | `phase-2-router-generator`   |
| 3     | **Routing evaluation & finding** — sweep the router against the single-model baselines through the eval harness; report cost-per-correct-answer and quality-at-cost; deliver an honest verdict (and write-up) on whether routing pays off.                                                                      | `phase-3-routing-evaluation` |

## Sprint-Wide Knowledge Plan

| Knowledge area                                                                                                                      | Kind                              | Action                                                       | Timing                            |
| ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------ | --------------------------------- |
| Cost-aware routing / model cascades — escalation policies, inference-time confidence signals for RAG generators, cascade evaluation | research (undecided design space) | Context7/Exa, or `--deep-research`                           | **Before** phase-1 brainstorm/ADR |
| Router as a `Generator`-seam composite (cheap→strong)                                                                               | KB                                | `/update-kb rag-generation` (add the router/cascade pattern) | **After** the phase-2 ADR lands   |
| `cost-per-correct-answer` (quality-at-cost) eval metric definition                                                                  | tech-agnostic                     | `/update-kb rag-eval` (metric concept)                       | When it stabilizes (≈ phase-3)    |

## Success Criteria

1. A `RouterGenerator` runs end-to-end **behind the existing `Generator` Protocol** — no change to the seam contract.
2. The escalation decision keys on a documented **inference-time** signal (ADR-recorded), independent of the offline eval judge.
3. The eval harness produces a head-to-head: **router vs each single-model baseline**, reporting cost-per-correct-answer (or quality-at-cost) per system.
4. A clear, **honest verdict**: does routing beat the best single model on cost at equal quality? Either outcome is a valid sprint result — the deliverable is the _measured_ decision plus a short write-up.

## Risks

- **The offline-judge wrinkle (core design risk).** Escalation cannot use the eval judge (it runs offline, post-hoc). If no available inference-time signal (abstention / retrieval score / self-consistency) is discriminative enough, the router cannot beat a single model. _Mitigation:_ phase-1 validates signal discriminativeness **before** the router is built.
- **Sweep cost.** Running the router plus re-running baselines costs API spend. _Mitigation:_ iterate on the capped `configs/baseline.dev.yaml` (20 questions); full 500-question sweep only for the final numbers.
- **Outcome risk.** Routing may not pay off on this benchmark. _Mitigation:_ frame a null result as an honest finding, not a failure — the senior signal is the rigorous measurement, not a guaranteed win.
- **Scope creep on threshold tuning.** _Mitigation:_ pick one escalation threshold, measure, stop; defer a sweep over thresholds unless the sprint has room.

## Retrospective

**Outcome: all 4 success criteria met; the sprint delivered a measured _null_ verdict.**
A `RouterGenerator` runs behind the unchanged `Generator` Protocol (criterion 1), keys on a
documented inference-time signal (verbalized confidence, ADR-0011 — criterion 2), and was
swept head-to-head against the three baselines on cost-per-correct (criterion 3). The verdict
(criterion 4): **routing does not pay off — the router is strictly dominated.** Gemini alone
is ~9× cheaper per correct at equal quality; gpt-5-nano alone is 2× cheaper _and_ the highest
quality (500 q, $4.43). Realized escalation ≈52% (cost-derived) matched ADR-0011's calibrated
~54%, and the weak signal (AUROC 0.685) bought no quality dividend — exactly as predicted.

**What worked.** The risk register called every shot. The "offline-judge wrinkle" forced the
verbalized-confidence pivot in phase 1 (after logprobs proved infeasible on Gemini 2.5); the
"outcome risk" framed the null as a valid result up front, so phase 3 was a clean measurement
rather than a scramble for a win. Dev-first discipline (20 q before 500 q) caught the pipeline
end-to-end cheaply.

**What slipped / changed scope.** The full 500-q sweep repeatedly died on a single transient
OpenAI judge timeout — one unhandled exception in `process_one` killing all ~2500 calls. This
forced an **unplanned runner-hardening detour** (transient-error skip + `--resume`), a
deliberate exception to phase-3's NFR-1 "runner unchanged" constraint, landed as its own
`fix(runner)` commit. It partially delivers backlog B-02 (the _resumable_ half; the
content-addressable cache half remains). Net: the detour was the right call — without it the
sprint's headline deliverable was uncompletable on the 8 GB Air.

**Carryover (non-blocking, → sprint close / next sprint):** two deferred `/update-kb` writes
(rag-eval cost-per-correct; rag-generation router-cascade) + a runner-resume KB line.

## Sprint Close

| Phase | Slug                         | Verdict                                          |
| ----- | ---------------------------- | ------------------------------------------------ |
| 1     | `phase-1-escalation-signal`  | ✅ READY (ADR-0011, PR #36)                      |
| 2     | `phase-2-router-generator`   | ✅ READY (ADR-0012, PR #37)                      |
| 3     | `phase-3-routing-evaluation` | ✅ READY (PR #38 — null verdict + runner resume) |

All phases shipped. Backlog: **B-07 (cost-aware router) → done**; **B-02** annotated (resume
half delivered). ADRs: 0011 + 0012 written in-sprint; the runner hardening is a robustness
fix, no ADR. Folder archived to `.claude/sdd/archive/sprint-7/`.
