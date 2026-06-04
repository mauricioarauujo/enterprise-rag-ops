# DESIGN: sprint-7/phase-1-escalation-signal — Inference-Time Escalation Signal

**Sprint/Phase:** sprint-7/phase-1-escalation-signal | **Date:** 2026-06-04

## Architecture

Phase-1 ships **two things**: (a) the **production seam wiring** of a cheap-model
confidence number from the Gemini generation path onto `CallStats`, and (b) an
**off-surface validation pipeline** that proves the signal separates correct from
incorrect Gemini answers, reported in an ADR. There is **no hard AUROC bar** — a weak
signal is an ADR-recorded finding (DEFINE decision 2).

The whole flow turns on the **RISK-1 spike (AC-1)**: whether `gemini-2.5-flash-lite`
exposes usable **token-level** logprobs while `response_mime_type="application/json"` is
active. That spike chooses which signal `_compute_confidence` returns — it runs FIRST,
before the extraction code is finalized.

### Data flow

```
                    ┌─────────────── PRODUCTION SEAM (committed, tested) ───────────────┐
GeminiGenerator.generate_with_stats(ctx, q)                                              │
  config = GenerateContentConfig(                                                        │
      response_mime_type="application/json",                                             │
      response_schema=_GeminiResponseSchema,                                             │
      response_logprobs=True,           # NEW (FR-2)                                      │
      logprobs=5,                       # NEW — top-N candidates per token (FR-2)         │
      system_instruction=...)                                                            │
        │                                                                                │
        ▼                                                                                │
  response.candidates[0].{avg_logprobs, logprobs_result}                                 │
        │                                                                                │
        ▼                                                                                │
  conf = _compute_confidence(response)   # NEW helper (FR-2)                              │
        │   first-token margin (top-1 logprob − top-2 logprob)  ── if token candidates   │
        │   else avg_logprobs (fallback)                        ── RISK-1 branch          │
        │   else None                                           ── defensive (missing)    │
        ▼                                                                                │
  CallStats(..., confidence_score=conf)  # NEW field: float | None = None (FR-1)         │
  RawCall.response += logprob payload    # _serialize_response extension (FR-2)          │
        │                                                                                │
        ▼                                                                                │
  runner.py:187 → EvalRecord.generation (CallStats) → results/<run>.jsonl  (NFR-3)       │
        └─ retrieval-abstain stub (runner.py:175-182) leaves confidence_score=None       │
                    └──────────────────────────────────────────────────────────────────┘

                    ┌─────────────── OFF-SURFACE VALIDATION (scripts/, dev) ───────────┐
configs/gemini-logprobs.yaml  ──rag-eval──▶  results/gemini-logprobs.jsonl  (FR-4, AC-5) │
   (500 q, logprobs on, ≤$5)                  (one confidence_score / question_id)        │
        │                                                                                │
        ▼                                                                                │
scripts/signal_validation.py  (FR-5, FR-6 — pure pandas, no live API)                    │
   JOIN on question_id  vs  results/baseline.jsonl                                        │
       filtered to gen_ai.request.model == "gemini-2.5-flash-lite"                        │
   attach correct = (failure_mode == "correct")                                          │
        │                                                                                │
        ├─ 20/80 calibration/test split (seeded) — threshold set on calib ONLY (AC-8)    │
        ├─ _auroc(scores, labels) → Mann–Whitney U (rank-based, pure pandas)             │
        │     three signals: logprob-alone / abstain-alone / hybrid-OR (AC-7)            │
        └─ separation plot + escalation rate                                             │
        ▼                                                                                │
docs/analysis/escalation-signal-validation.md  (+ separation-plot.png)  (FR-6, AC-9)     │
        ▼                                                                                │
docs/adr/0011-escalation-signal.md   (FR-7, AC-10 — the phase deliverable)               │
                    └──────────────────────────────────────────────────────────────────┘
```

### Named helpers (the implementer must create exactly these)

- **`_compute_confidence(response) -> float | None`** in `gemini_generator.py` — module-level,
  defensive (mirrors the `getattr(..., 0) or 0` token-accounting at `gemini_generator.py:193-197`).
  Returns first-token margin when `candidates[0].logprobs_result.top_candidates[0].candidates`
  has ≥2 entries (margin = `[0].log_probability − [1].log_probability`); else `avg_logprobs`
  (`candidates[0].avg_logprobs`) as the RISK-1 fallback; else `None`. **Never raises.**
- **`_auroc(scores: pd.Series, labels: pd.Series) -> float`** in `scripts/signal_validation.py` —
  AUROC as the rank-based Mann–Whitney U statistic: `AUROC = (sum_of_positive_ranks −
n_pos*(n_pos+1)/2) / (n_pos * n_neg)`, using `scipy`-free `pandas.Series.rank()` (average ties).
  ~10 lines, no sklearn. For a boolean signal (abstain-alone) the same formula collapses to the
  expected two-rank value.

### Resolved design decisions (the three the orchestrator flagged)

1. **AUROC in pure pandas, no `scikit-learn`.** `_auroc` is the Mann–Whitney U statistic via
   `pandas.Series.rank()` — rank-based, ~10 lines, deterministic, zero new dependency. Honors the
   repo's minimal-scope ethos; avoids a heavy transitive dep for one number. (Infra Gap G-1.)
2. **Separation plot via `matplotlib` in the `[dependency-groups] dev` group — NOT a runtime dep.**
   AC-9 requires a committed plot artifact; a real PNG is the honest deliverable. `matplotlib`
   is added **only to the dev group** (`pyproject.toml:49-55`, alongside `pytest`/`vcrpy`), so it
   never enters the production package surface (`dependencies`, `pyproject.toml:11-25`). The
   analysis script that imports it lives in `scripts/` (off-surface), consistent with NFR-7. The
   considered alternative — an ASCII/markdown histogram with zero deps — was rejected: a committed
   PNG reads better in the ADR and the dev-group placement already keeps the surface clean.
   (Infra Gap G-1.)
3. **Analysis + re-run driver live in a new top-level `scripts/` dir (committed, not gitignored),
   off the production package surface.** No `scripts/` dir exists today; committed eval CLIs are
   `src/enterprise_rag_ops/eval/*_cli.py` wired into `[project.scripts]`. The validation script is
   a one-shot dev analysis, **not** a production entry point — putting it under
   `src/enterprise_rag_ops/eval/` would pollute the shipped package and tempt a `[project.scripts]`
   wiring it does not deserve. `scripts/signal_validation.py` is the clean, minimal home (NFR-7).
   It is **committed** (the analysis must be reproducible for the ADR), not gitignored. (Infra Gap G-2.)
4. **Re-run = the existing `rag-eval` CLI with a logprobs-on config — no new driver code.** Once
   FR-2 lands, logprobs are captured on **every** Gemini call automatically, so the "re-run" is
   just `rag-eval` over `configs/gemini-logprobs.yaml` (a copy of `gemini-only.yaml` with a distinct
   `run_id: gemini-logprobs` so it does not clobber `results/gemini.jsonl`). The judge still runs
   (small extra `gpt-5-nano` spend, still ≪ $5; total ≈ $0.64 + judge), but **its output is unused** —
   labels come from `baseline.jsonl`. This is strictly more minimal than adding a no-judge code
   path (FR-4 / AC-5). The judge cost is acceptable; no new branch in `runner.py`. (Resolved below.)

## File Manifest

Prescriptive — an Antigravity/Gemini executor needs no extra context. All `direct`: no
specialist owns `generation/` or `eval/` (the DEFINE Infrastructure Readiness table lists
`—` throughout; prior generation/eval phases shipped `direct`).

| File                                                    | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Owner                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Phase order |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | --- |
| **(spike — no committed file)**                         | RISK-1 probe (AC-1): one live `gemini-2.5-flash-lite` call with `response_logprobs=True`, `logprobs=5`, `response_mime_type="application/json"` active. Inspect `response.candidates[0]`: is `logprobs_result.top_candidates[0].candidates` populated with ≥2 entries carrying `.log_probability`/`.token` (→ margin usable), or only `avg_logprobs` (→ fallback)? **Verify the exact SDK field names** (`avg_logprobs`, `logprobs_result`, `chosen_candidates`, `top_candidates[].candidates[].log_probability`) against the installed `google-genai>=1.0` — names below are the design's best read and MUST be confirmed here. Record the outcome (it feeds ADR FR-7 item 5 and `_compute_confidence`'s primary branch). Throwaway — not committed.                                                                                                                                                                                                                                                    | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 0           |
| `src/enterprise_rag_ops/eval/records.py`                | In `CallStats` (`records.py:24-32`), after `cost_usd: float \| None = None` (`:32`), add `confidence_score: float \| None = None`. Mirror the `cost_usd` optional-default precedent **exactly**. No other field, no `EvalRecord` change (`generation: CallStats` at `:88` carries it for free). (FR-1, AC-2, NFR-3.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 1           |
| `src/enterprise_rag_ops/generation/gemini_generator.py` | (1) Add module-level `\_compute_confidence(response) -> float                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | None`per § Architecture — first-token margin primary,`avg_logprobs`fallback,`None`defensive, never raises. (2) In`generate_with_stats`, add `response_logprobs=True`and`logprobs=5`to the`GenerateContentConfig` (`gemini_generator.py:177-184`). (3) After the token-accounting block (`:193-197`), call `conf = \_compute_confidence(response)`and pass`confidence_score=conf`into the`CallStats(...)` constructor (`:199-205`). (4) Extend `\_serialize_response` (`:36-108`) to capture the logprob payload (`candidates[].avg_logprobs`+`logprobs_result`) into `RawCall.response`for forensics — defensive`getattr`, same style as the existing candidate/usage walk. `generate` (`:159-162`) is **untouched** — still returns only `AnswerWithSources` (FR-3/AC-4). (FR-2, AC-1, AC-3.) | direct      | 2   |
| `configs/gemini-logprobs.yaml`                          | **New.** Copy of `configs/gemini-only.yaml` with `run_id: "gemini-logprobs"` (so it writes `results/gemini-logprobs.jsonl`, not clobbering `results/gemini.jsonl`). `limit: null` (all 500), `cost_ceiling_usd: 5.0` unchanged, prices unchanged. Logprobs are on automatically via FR-2 — no config knob needed. (FR-4, AC-5.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 3           |
| `results/gemini-logprobs.jsonl`                         | **New (generated, gitignored — `results/` is in `.gitignore`).** Produced by `rag-eval --config configs/gemini-logprobs.yaml`. ~500 rows, each with `generation.confidence_score`. The deliverable is the _run_ (AC-5), not a committed file. The validation script reads it locally.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | direct (run)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | 4           |
| `scripts/signal_validation.py`                          | **New** (new top-level `scripts/` dir, committed, not gitignored). Pure-pandas, deterministic, **no live API**. (1) Load `results/gemini-logprobs.jsonl` → `(question_id, confidence_score, did_abstain_e2e)`. (2) Load `results/baseline.jsonl`, filter `gen_ai.request.model == "gemini-2.5-flash-lite"`, JOIN on `question_id`, attach `correct = (failure_mode == "correct")` (AC-6). (3) Seeded 20/80 calibration/test split (seed recorded as a module constant). (4) `_auroc` (Mann–Whitney U, pure pandas) for three signals predicting `correct`: logprob-alone, abstain-alone, hybrid-OR — reported on the **test** split; any threshold set on **calibration** only (AC-7, AC-8). (5) Compute escalation rate at the chosen operating point. (6) Emit the markdown report + the `matplotlib` separation-plot PNG. Writes to `docs/analysis/`. (FR-5, FR-6, AC-6/7/8/9.)                                                                                                                       | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 5           |
| `docs/analysis/escalation-signal-validation.md`         | **New (generated by the script, committed).** The report: three-way AUROC table (logprob/abstain/hybrid-OR), escalation rate at the operating point, embedded separation plot, honest framing, **no greenlight bar stated**. The ADR's supporting evidence. (FR-6, AC-7, AC-9.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 5           |
| `docs/analysis/escalation-signal-separation.png`        | **New (generated, committed).** Separation plot: confidence distribution for correct vs incorrect Gemini answers. Referenced by the report + ADR. (FR-6, AC-9.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 5           |
| `pyproject.toml`                                        | Add `"matplotlib>=3.8,<4.0"` to **`[dependency-groups] dev`** (`pyproject.toml:49-55`) — NOT to `dependencies` (`:11-25`). For the FR-6 separation plot only; off the production surface (NFR-7, design decision 2). No `[project.scripts]` entry for `signal_validation.py` (it is a dev one-shot, not a product CLI).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 5           |
| `docs/adr/0011-escalation-signal.md`                    | **New.** ADR-0011, `Status: accepted`, `Date: 2026-06-04`. Repo ADR format (Status / Date / Context / Decision / Consequences — cf. ADR-0010). Body satisfies AC-10 (1–6): (1) signal choice — hybrid abstention-OR-logprob, first-token margin primary + `avg_logprobs` fallback, cite `docs/planning/research/sprint-7-escalation-signal-research.md`; (2) seam-widening — confidence on `CallStats.confidence_score`, Gemini path only, public `Generator` Protocol untouched; (3) validation evidence (the FR-6 AUROC table + separation plot + escalation rate, link `docs/analysis/escalation-signal-validation.md`); (4) calibration-procedure-not-magic-number convention (record the _procedure_, e.g. "threshold at the Nth percentile of the calibration split"); (5) the **RISK-1 outcome** — which signal (margin or `avg_logprobs`) was actually used under structured output, from the spike; (6) explicit "no hard AUROC bar; phase-2 go/no-go is a human judgment call." (FR-7, AC-10.) | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 6           |
| `tests/eval/test_records.py`                            | **Extend** (exists). Add an AC-2 test: `CallStats.model_fields["confidence_score"]` exists, annotated `float \| None`, default `None`; a `CallStats` built **without** it round-trips (`model_validate_json(model_dump_json())` equal, `confidence_score is None`); one built with `confidence_score=0.42` round-trips losslessly and the key appears in the JSON. All in-memory, no LLM, no network. (FR-8, AC-2.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 7           |
| `tests/generation/test_gemini_generator.py`             | **Extend** (exists). Extend `FakeResponse`/`FakeGeminiClient` (`:33-56`) to optionally carry a logprob payload (fake `candidates[0].avg_logprobs` + `logprobs_result.top_candidates[0].candidates` with `.log_probability`/`.token`). Add AC-3 tests: (a) payload with ≥2 top-candidates → `confidence_score == ` first-token margin (top-1 − top-2); (b) payload with only `avg_logprobs` → `confidence_score == avg_logprobs` (fallback); (c) **no** logprob payload → `confidence_score is None`, no crash; (d) `generate()` still returns a bare `AnswerWithSources` (AC-4). Refresh/extend the `@pytest.mark.vcr test_live_replay` cassette (`tests/eval/cassettes/gemini_generator.yaml`) so the replayed response carries logprobs and asserts a non-`None` `confidence_score` — **never mock the genai client** (ADR-0006, NFR-2). (FR-8, AC-3, AC-4, AC-11.)                                                                                                                                    | direct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 7           |

No `interfaces.py` change, no `runner.py` change (the abstain stub at `:175-182` already
omits `confidence_score`, so the new default `None` covers it — confirm by review, do not
edit), no reader edit (dashboard/report/inspect/triage/exporter), no new `[project.scripts]`
entry, no baseline/Claude/OpenAI re-run. By FR-3/NFR-1/NFR-3 and the Out-of-Scope list.

## Implementation Phases

Ordered per the convention (data/config → core `src/` → eval wiring → report → tests →
docs/ADR), with the **RISK-1 spike pulled to phase 0** because it gates the
`_compute_confidence` implementation choice (AC-1).

0. **RISK-1 spike (AC-1) — FIRST, gates the approach.** One throwaway live Gemini call with
   `response_logprobs=True`, `logprobs=5`, JSON mode active. **Branch:**
   - **(a) margin usable** — `logprobs_result.top_candidates` carries ≥2 per-token candidates →
     first-token margin is the primary signal in `_compute_confidence`.
     - **(b) JSON mode collapses per-token candidates** — only `avg_logprobs` present → the
       documented `avg_logprobs` fallback is the signal. Either way, **confirm the exact SDK field
       names** before writing step 2. Record the outcome for ADR item 5. No numeric bar — gates the
       _implementation choice_, not the phase.
1. **`CallStats.confidence_score`** — `records.py`. The optional-defaulted field. _No dependency._
   Satisfies FR-1; checkable by AC-2.
2. **Gemini extraction seam** — `gemini_generator.py`: `_compute_confidence` (branch from step 0),
   the config flags, the `CallStats` population, the `_serialize_response` extension. **Depends on
   step 1** (the field must exist). Satisfies FR-2, FR-3; checkable by AC-1, AC-3, AC-4.
3. **Re-run config** — `configs/gemini-logprobs.yaml`. _No dependency._ Satisfies FR-4 prep.
4. **Validation re-run** — `rag-eval --config configs/gemini-logprobs.yaml` (500 q, ≤$5).
   **Depends on steps 2–3.** Produces `results/gemini-logprobs.jsonl`. Satisfies FR-4; AC-5.
5. **Analysis + report + plot dep** — `scripts/signal_validation.py`, `pyproject.toml` (matplotlib
   dev), the two `docs/analysis/` artifacts. **Depends on step 4 + `baseline.jsonl`.** Satisfies
   FR-5, FR-6; AC-6, AC-7, AC-8, AC-9.
6. **ADR-0011** — `docs/adr/0011-escalation-signal.md`. **Depends on steps 0 + 5** (records the
   RISK-1 outcome + the validation evidence). Satisfies FR-7; AC-10.
7. **Tests** — `tests/eval/test_records.py` + `tests/generation/test_gemini_generator.py`.
   **Depend on steps 1–2.** Satisfies FR-8; AC-3, AC-4, AC-11.
8. **Quality pass** — `make lint test`. Targeted first:
   `uv run pytest tests/eval/test_records.py tests/generation/test_gemini_generator.py -k "confidence"`.

## The exact `GenerateContentConfig` change (FR-2)

In `generate_with_stats` (`gemini_generator.py:177-184`), the config gains two fields:

```python
config=types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=_GeminiResponseSchema,
    response_logprobs=True,   # NEW — request token-level logprobs
    logprobs=5,               # NEW — top-N candidates per token (margin needs top-2; 5 gives headroom)
    system_instruction=system_prompt,
),
```

**`logprobs=5` justification.** First-token margin needs only the top-2 candidates; `N=5` is a
small, cheap headroom that (i) tolerates ties/degenerate first tokens and (ii) leaves a little
forensic signal in `RawCall.response` without bloating it. **The spike (phase 0) must verify the
exact field names** — `response_logprobs` vs `responseLogprobs`, the `logprobs` int field, and the
response-side `avg_logprobs` / `logprobs_result.top_candidates[].candidates[].log_probability` —
against the installed `google-genai>=1.0,<2.0`. If JSON mode collapses per-token candidates
(RISK-1 branch b), `logprobs=5` is harmless and `_compute_confidence` falls back to `avg_logprobs`.

## Infrastructure Gaps

Deep three-layer check (domain existence / concept coverage / agent alignment). Every code
dependency maps to an existing module and the existing `rag-generation` / `rag-eval` KB domains.
Two **resolved design choices** (the dep gap, the script location) and one **probe-gated risk** are
surfaced below; none blocks implementation.

| Gap Type                               | Area                                                     | Detail                                                                                                                                                                                                                                                                                                                                                   | Recommendation                                                                                                                                                                         |
| -------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Missing dependency (resolved)          | `pyproject.toml` analysis deps                           | `scikit-learn`, `numpy`, `matplotlib` are **absent**; only `pandas` is present. AUROC + separation plot need a decision.                                                                                                                                                                                                                                 | **Resolved in design:** AUROC in pure pandas (Mann–Whitney U, no sklearn/numpy); `matplotlib` added to the **dev** group only (not runtime). No `/new-kb` / `/update-kb` needed. (G-1) |
| Missing location convention (resolved) | off-surface dev script                                   | No `scripts/` dir exists; committed CLIs are `src/.../eval/*_cli.py` on the production surface (NFR-7 forbids polluting it).                                                                                                                                                                                                                             | **Resolved in design:** new top-level `scripts/` dir (committed, not gitignored) for `signal_validation.py`; no `[project.scripts]` entry. (G-2)                                       |
| Probe-gated risk (not a gap)           | Gemini token-level logprobs under structured JSON output | Whether `gemini-2.5-flash-lite` returns usable token-level candidates with `response_mime_type="application/json"` is unverified (RISK-1 / Open Question 1).                                                                                                                                                                                             | **Phase-0 spike (AC-1) confirms it first**, with the documented `avg_logprobs` fallback. A contingency, not a blocker; no infra change. (G-3)                                          |
| Missing domain                         | —                                                        | Every tech area (Gemini logprob API, Pydantic field evolution, JSONL join, AUROC, calibration/test split, ADR) is covered by `rag-generation` (`gemini-structured-output`, `generator-seam`, `raw-payload-serialization`) and `rag-eval` (`stats-capture-seam`, `eval-record-schema`, `failure-taxonomy`, `cassette-replay-eval`, `multi-model-runner`). | none                                                                                                                                                                                   |
| Missing concept                        | —                                                        | A `signal-validation` / `cost-per-correct-answer` concept and the router/cascade pattern are **deferred by the Sprint-Wide Knowledge Plan to after the phase-2 ADR** — explicitly NOT a phase-1 gap (DEFINE Users + Infrastructure Readiness).                                                                                                           | `/update-kb rag-generation` + `/update-kb rag-eval` — **deferred post-phase-2, not now**                                                                                               |
| Missing specialist                     | —                                                        | Neither `generation/` nor `eval/` has an owning specialist (`—` across the DEFINE readiness table); prior phases shipped `direct`. A 1-field add + one helper + a pandas script does not warrant one.                                                                                                                                                    | none                                                                                                                                                                                   |

- **Domain existence:** ✅ `rag-generation` + `rag-eval` cover all areas. No observability work.
- **Concept coverage:** ✅ `stats-capture-seam` covers the `CallStats`/`generate_with_stats` ride;
  `raw-payload-serialization` covers the `_serialize_response` extension; `cassette-replay-eval`
  covers the ADR-0006 test path; `multi-model-runner` covers the `rag-eval` re-run. The
  signal-validation concept is a deferred refresh, not a blocker.
- **Agent alignment:** ✅ N/A — no specialist owns these modules; `kb-architect` owns the deferred
  post-phase-2 `/update-kb`, consistent with the Sprint-Wide Knowledge Plan.

**Deferred KB work (router/cascade, cost-per-correct-answer) is confirmed NOT a phase-1 gap** —
the router does not exist yet; the Sprint-Wide Knowledge Plan lands it after the phase-2 ADR.

## Consistency Check

**Verdict: ✅ CONSISTENT.** Non-trivial multi-module phase (generation + eval + config + scripts +
docs + tests; DEFINE encodes three user-ratified scope forks). Full six-pass cross-check of
DEFINE↔DESIGN against the constitution (AGENTS.md § Engineering Behavior + § Conventions + §
Testing, ADR-0003/0005/0006, the `rag-generation` + `rag-eval` KB). No CRITICAL/HIGH drift.

| ID  | Severity | Pass               | Location                              | Finding                                                                                                                                                                                               | Suggested fix                                                                                                                                                                                                                                                                                                          |
| --- | -------- | ------------------ | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | MEDIUM   | Ambiguity          | DEFINE FR-2 confidence-number formula | DEFINE leaves the `avg_logprobs`→confidence mapping open ("`exp(avg_logprobs)` or the raw average, documented in the ADR"). The two yield different scales, which matters for a cross-call threshold. | DESIGN picks the **raw `avg_logprobs`** (higher = more confident, monotone, no transform) as the fallback value; the ADR (FR-7 item 4) documents it. Either is valid per DEFINE; pinning one removes implementer guesswork. Monotone transforms do not change AUROC (rank-based), so the choice is threshold-cosmetic. |
| C-2 | LOW      | Ambiguity          | DEFINE FR-6 report location           | DEFINE says "e.g. `docs/analysis/` or the ADR body". DESIGN pins `docs/analysis/escalation-signal-validation.md` + PNG, linked from the ADR.                                                          | Implementer choice per DEFINE's "e.g."; the pinned `docs/analysis/` matches the existing `docs/analysis/over-abstention.md` precedent.                                                                                                                                                                                 |
| C-3 | LOW      | Underspecification | DEFINE FR-4 "dev/throwaway driver"    | DEFINE describes FR-4 as a "dev/throwaway driver"; DESIGN resolves it to **reusing `rag-eval`** (no new driver code), accepting the unused judge spend.                                               | Confirmed minimal (no `runner.py` branch). The "throwaway" framing is satisfied by a config file + a one-shot CLI invocation; the judge cost (≪$5) is documented as acceptable in the ADR cost note.                                                                                                                   |
| C-4 | LOW      | Inconsistency      | `run_id` collision risk               | `configs/gemini-only.yaml` uses `run_id: gemini` → `results/gemini.jsonl` (the unclassified existing run). The re-run must NOT clobber it.                                                            | DESIGN sets `run_id: gemini-logprobs` → `results/gemini-logprobs.jsonl`. Flagged so the executor copies-and-renames rather than editing `gemini-only.yaml` in place.                                                                                                                                                   |

- **Duplication:** none. FR-1 (field) and FR-2 (extraction) are sequential, not overlapping;
  FR-5 (analysis) and FR-6 (report) are produced by one script but are distinct outputs.
- **Ambiguity:** C-1 (fallback formula — pinned to raw `avg_logprobs`), C-2 (report location —
  pinned to `docs/analysis/`). No vague descriptors; no unresolved `TODO`/`???`. The AUROC has no
  threshold by design (decision 2), so "discriminative enough" is correctly a human call, not a
  vague AC.
- **Underspecification:** C-3 (FR-4 driver — resolved to `rag-eval` reuse). Every FR maps to a
  named site (`records.py:32` field block, `gemini_generator.py:177-184` config + `:199-205`
  CallStats, `runner.py:175-182` stub left untouched, `baseline.jsonl` filter predicate); every
  code-bearing AC names its mechanism (`model_fields`, `model_dump_json`/`model_validate_json`,
  `FakeGeminiClient`, the VCR cassette, `_auroc`).
- **Constitution alignment:** ✅ **Minimal scope** — one optional field + one helper + two config/
  config-flag lines + a pure-pandas script + an ADR; **no** `RouterGenerator`, **no** threshold
  sweep, **no** Anthropic/OpenAI logprob wiring (all Out-of-Scope). **Clean seam** — the confidence
  number rides the _existing_ `CallStats`/`generate_with_stats` seam (a named, likely phase-2
  change, recorded in ADR-0011); the public `Generator` Protocol is byte-for-byte invariant
  (FR-3/NFR-1/AC-4) — the exact "seam justified by an ADR, not 'in case'" bar. **Surgical edits** —
  no reader touched, abstain stub left untouched. **No stranger-test leak** — ADR-0011, the
  validation report, and `scripts/signal_validation.py` are all public system artifacts (no career/
  budget/private-path content). Conventions: English; YYYY-MM-DD; tests mirror `src/` into
  `tests/eval/` + `tests/generation/` with existing `__init__.py` (no flat `tests/test_*.py`,
  NFR-7); **cassette/replay, never a mocked LLM** (NFR-2/ADR-0006). The new `scripts/` dir +
  dev-group `matplotlib` keep the production package surface clean (NFR-7).
- **Coverage:** ✅ all 8 FR + 7 NFR map to ≥1 manifest entry (FR-1→records.py; FR-2→gemini_generator.py;
  FR-3→no-interfaces-change + generate untouched; FR-4→gemini-logprobs.yaml + rag-eval run;
  FR-5→signal_validation.py; FR-6→docs/analysis/ artifacts + matplotlib dev dep;
  FR-7→0011-escalation-signal.md; FR-8→the two test files). All 11 AC map to a test or a doc/run
  check (AC-1→spike; AC-2→test_records; AC-3/4→test_gemini_generator; AC-5→the re-run;
  AC-6/7/8/9→signal_validation.py + report; AC-10→the ADR; AC-11→`make lint test`). Reverse check:
  every manifest entry references a confirmed component (`CallStats` at `records.py:24-32`,
  `generate_with_stats` at `:164-224`, `_serialize_response` at `:36-108`, the abstain stub at
  `runner.py:175-182`, `baseline.jsonl` filter, the `FakeGeminiClient`/cassette harness — all read
  this session).
- **Inconsistency:** C-4 (`run_id` collision — resolved by `gemini-logprobs`). Terminology is
  identical across DEFINE/DESIGN (`confidence_score`, "first-token margin", "`avg_logprobs`
  fallback", "hybrid-OR", "calibration/test split"); no directive conflicts with ADR-0003 (seam),
  ADR-0005 (provider matrix), or ADR-0006 (cassette).

## Risks & Trade-offs

- **RISK-1 (the one real risk) — token-level logprobs under structured JSON output.** If JSON mode
  collapses per-token candidates, first-token margin is unavailable and the signal degrades to
  response-level `avg_logprobs` (less discriminative). **Mitigated** by making the spike phase 0
  (AC-1) with a documented fallback baked into `_compute_confidence`. The phase still ships —
  `avg_logprobs` is a valid, ADR-recorded signal, and a weak AUROC is itself a publishable finding
  (DEFINE decision 2). The implementer **must not** finalize `_compute_confidence` before the spike.
- **The single most important thing to get right: defensive, never-crash extraction.** Logprob
  payload shape varies by SDK version and is the RISK-1 unknown. `_compute_confidence` MUST mirror
  the existing defensive token-accounting (`gemini_generator.py:193-197`): missing/empty/malformed
  logprobs → `confidence_score = None`, **never an exception** that breaks a 500-question sweep
  mid-run. This is both a correctness (NFR-4) and a cost (a crash wastes the re-run) concern.
- **Unused judge spend on the re-run (accepted).** Reusing `rag-eval` runs the `gpt-5-nano` judge
  whose output we discard (labels come from `baseline.jsonl`). The spend is ≪ $5 and buys zero new
  `runner.py` code — the right trade per minimal-scope. Documented in the ADR cost note.
- **AUROC on ~400 test rows (80% of 500) with a confident-hallucination-skewed positive class.**
  The `correct` base rate and class balance affect AUROC stability; the rank-based `_auroc` is
  exact (no sampling), but the report must state n and the split seed (AC-8) so the number is
  reproducible and not over-read. No threshold is tuned on test (NFR-6).
- **`matplotlib` as a dev dep is a real (if small) footprint add.** Justified by AC-9's committed-
  plot requirement and confined to the dev group. The alternative (ASCII histogram, zero deps) was
  weighed and rejected for ADR legibility — recorded in design decision 2.
- **ADR warranted? Yes — it IS the deliverable (FR-7).** The phase records a signal choice, a
  seam-widening decision, and validation evidence that phase-2 reads at design time. `0011` is the
  next free number. Well above the "ADR only if non-trivial" bar.

## Next Step

→ `/implement sprint-7/phase-1-escalation-signal` — gaps are resolved design choices (none
blocking). Per the cross-tool **Implement Contract** (AGENTS.md), the implement stage may run in
**Antigravity / Gemini** against this `DESIGN.md` as the contract: confirm the branch
`sprint-7/phase-1-escalation-signal`, read this manifest + `DEFINE.md` + the `rag-generation`
(`generator-seam`, `gemini-structured-output`, `raw-payload-serialization`) and `rag-eval`
(`stats-capture-seam`, `cassette-replay-eval`) KB, **run the RISK-1 spike (phase 0) FIRST** to fix
the `_compute_confidence` branch, then implement in phase order, **never mock the genai client**
(ADR-0006), and finish on `make lint test`.
