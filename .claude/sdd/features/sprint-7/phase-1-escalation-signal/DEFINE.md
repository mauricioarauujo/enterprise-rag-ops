# DEFINE: sprint-7/phase-1-escalation-signal — Inference-Time Escalation Signal

**Sprint/Phase:** sprint-7/phase-1-escalation-signal | **Date:** 2026-06-04
**Approach:** BRAINSTORM Approach C (hybrid: abstention OR low cheap-model logprob margin),
**production-seam variant** (chosen by the user over probe-only). Phase-1 both (a) **commits
the production wiring** of the confidence signal into `GeminiGenerator.generate_with_stats` /
`CallStats`, and (b) **validates the signal's discriminativeness** against the existing
baseline labels, reporting the evidence (AUROC + separation plot) that the phase-2 go/no-go
human judgment call will read at design time. There is **no hard AUROC acceptance bar** — a
weak signal is a valid, ADR-recorded finding, not a phase failure.

**Crisp scope call (the three decisions this DEFINE encodes as fixed, already resolved by the
user — not re-asked).**

1. **Phase-1 ships the production seam wiring, not a throwaway probe.** The confidence number
   is persisted via a new optional `CallStats.confidence_score: float | None = None` field
   (`eval/records.py`), populated **only** by the Gemini path; every other generator leaves it
   `None`. It threads through `EvalRecord.generation` for forensics/replay. The logprob
   extraction lives in `GeminiGenerator.generate_with_stats` (`generation/gemini_generator.py`).
   A throwaway/dev probe to confirm API behavior is allowed, but the **deliverable** is the
   committed, tested wiring. (Phase-2's `RouterGenerator` reads the field off
   `generate_with_stats` — the public `Generator.generate()` seam is untouched.)
2. **No hard AUROC greenlight bar.** Phase-1 **reports** the discrimination evidence (AUROC for
   logprob-alone vs abstention-alone vs hybrid-OR, plus a separation plot of the confidence
   distribution for correct vs incorrect answers). The phase-2 go/no-go is a **human judgment
   call made at design time** from that evidence, not a fixed numeric AC. No AUROC threshold is
   invented here.
3. **Validation runs on the full 500 Gemini questions, not the dev-20 subset.** Cost is ~$0.64
   (well under the $5 ceiling); 20 questions give a statistically meaningless AUROC.

## Problem

Sprint 7 builds a cost-aware router that answers with `gemini-2.5-flash-lite` by default and
escalates to `claude-haiku-4-5` when an **inference-time** confidence signal indicates the cheap
model is likely wrong. The core design risk (SPRINT.md): the eval judge is **offline and
post-hoc**, so it cannot be that signal — the router needs a number observable at generation
time. Phase-1's job is to (a) pick that signal, (b) **wire it into the cheap-model generation
path** so phase-2 has a real field to read, and (c) **prove it statistically separates** correct
cheap-model answers from incorrect ones, recording the evidence in an ADR before phase-2 commits
to building on it.

The baseline finding (`docs/analysis/over-abstention.md`) sharpens the constraint: Gemini's
dominant failure mode is **confident hallucination** (46 hallucinations vs 10 for Claude Haiku;
faithfulness 78.6% vs 92.1%; abstain recall only 70.0%). A router that fired **only** on Gemini
abstention would (i) trigger at most ~30% of the time and (ii) be blind to Gemini's actual
failure class. So the signal must address confident wrongness — hence Approach C pairs the
research-backed first-token logprob margin (the discriminative signal) with the free abstention
sentinel (a free orthogonal trigger).

The decisive facts (confirmed in source this session):

- **The seam is `generate_with_stats`, and it returns `CallStats` today.** `GeminiGenerator.
generate_with_stats` (`gemini_generator.py:164-224`) already returns
  `(AnswerWithSources, CallStats, RawCall)` and is the method the runner calls
  (`runner.py:187`). `CallStats` (`records.py:24-32`) has no confidence field yet. The public
  `Generator` Protocol (`interfaces.py:17-31`) exposes only `generate(context_chunks, question)
-> AnswerWithSources` — the confidence number must NOT touch it.
- **Gemini runs in structured-JSON mode.** The call sets `response_mime_type="application/json"`
  - `response_schema=_GeminiResponseSchema` (`gemini_generator.py:177-184`). This is the heart of
    Open Question 1: whether token-level logprobs are populated (and first-token margin meaningful)
    when generation is constrained to a JSON blob. Logprobs are **not** requested today — the
    config carries no `response_logprobs`/`logprobs` flag.
- **Ground-truth labels exist and are NOT in `results/gemini.jsonl`.** `results/baseline.jsonl`
  (1500 rows = 3 models × 500 questions) is classified — each row has `failure_mode`,
  `did_abstain_e2e`, `fact_recall`, `faithfulness_ratio`, `question_id`, and the model under
  `gen_ai.request.model`. `results/gemini.jsonl` (500 rows) is the Gemini run but has
  `failure_mode: None` (unclassified). So validation must JOIN a fresh logprob re-run against
  `baseline.jsonl` **filtered to `gen_ai.request.model == "gemini-2.5-flash-lite"`**, on
  `question_id`, to attach the label.
- **The `correct` label is exact.** `correct = (failure_mode == "correct")`, where `"correct"`
  is `FailureMode.CORRECT` (`failure_taxonomy.py:27`, the terminal branch of the
  abstention→retrieval_miss→hallucination→incomplete→correct cascade, `classify`,
  `failure_taxonomy.py:92-106`).
- **The re-run config exists.** `configs/gemini-only.yaml` (model `gemini-2.5-flash-lite`, judge
  `gpt-5-nano`, prices set, `cost_ceiling_usd: 5.0`, `limit: null` → all 500). The logprob re-run
  needs logprobs enabled; the **judge is not needed** for logprob extraction (labels come from
  `baseline.jsonl`).
- **The cassette/replay pattern is established for Gemini.** `tests/generation/test_gemini_
generator.py` already carries a `@pytest.mark.vcr` `test_live_replay` against
  `tests/eval/cassettes/gemini_generator.yaml`, plus an injected-`FakeGeminiClient` offline path.
  The confidence-extraction test reuses both — never a mocked LLM API (ADR-0006).

## Users / Stakeholders

- **Phase-2 `RouterGenerator` author (Mauricio)** — the direct downstream beneficiary. After this
  phase, the cheap-model call surfaces a real `confidence_score` on `CallStats` that the router's
  escalation logic reads off `generate_with_stats` — no second wiring decision, no seam change.
  Needs: the field populated only by Gemini (other generators `None`), the public `generate()`
  contract untouched, and the validation evidence (AUROC + separation plot) to make the phase-2
  go/no-go judgment call.
- **The phase-2 go/no-go reviewer (Mauricio, at `/design` time)** — reads the phase-1 report and
  ADR and decides, by **human judgment** (not a fixed threshold), whether the signal is
  discriminative enough to build the router on, or whether to pivot (e.g. abstention-only, or
  re-scope). The honest-NULL-result framing (SPRINT.md success criterion 4) means "the signal is
  weak" is a publishable finding, not a failed phase.
- **The runner / `CallStats` consumers** — `EvalRecord.generation` carries `CallStats`
  (`records.py:88`), serialized to JSONL and read by the dashboard / report / inspect / triage
  paths. The new field is **optional + defaulted** (`float | None = None`), so every prior
  `results/*.jsonl` and every reader keeps loading (the established `cost_usd: float | None`
  precedent, `records.py:32`). No reader is edited this phase.
- **ADR-0006 (cassette/replay)** — the confidence-extraction test on the Gemini path must use a
  VCR cassette (or the injected fake client), never a mocked API. The re-run that produces
  logprobs is a real (cheap) sweep, not a test.
- **ADR author (this phase's deliverable)** — a new ADR records the signal choice, the
  seam-widening decision (confidence rides `CallStats`, not the Protocol), the validation
  evidence, and the calibration-procedure-not-magic-number convention.
- **`/update-kb rag-generation` (router/cascade pattern)** — deferred by design to **after the
  phase-2 ADR lands** (Sprint-Wide Knowledge Plan, SPRINT.md). Its absence today is **not** a
  phase-1 gap.

## Requirements

### Functional

- **FR-1 Confidence field on `CallStats` (the persisted seam).** `CallStats` (`eval/records.py`)
  gains `confidence_score: float | None = None` — optional + defaulted, mirroring the existing
  `cost_usd: float | None` field (`records.py:32`). It carries the cheap-model confidence number
  (higher = more confident). It is populated **only** by the Gemini path (FR-2); every other
  generator and the retrieval-abstain stub (`runner.py:175-182`) leave it `None`. Because
  `EvalRecord.generation` is a `CallStats` (`records.py:88`), the field persists into the JSONL
  for forensics and replay with no `EvalRecord` change.
- **FR-2 Logprob extraction in `GeminiGenerator.generate_with_stats`.** The Gemini call requests
  token-level logprobs (set the `response_logprobs`/`logprobs` flag in
  `GenerateContentConfig`, `gemini_generator.py:177-184`), reads them off the response, and
  computes a single confidence number: **first-token margin** `P(top-1) − P(top-2)` when
  token-level top-candidate logprobs are available; **`avg_logprobs`** (response-level average,
  mapped to a confidence number — e.g. `exp(avg_logprobs)` or the raw average, documented in the
  ADR) as the explicit fallback when the structured-output path does not expose usable
  per-token candidates (Open Question 1 / RISK-1). The number is written to
  `CallStats.confidence_score`. Extraction is **defensive** (missing/empty logprobs →
  `confidence_score = None`, never a crash — matching the existing defensive token-accounting at
  `gemini_generator.py:193-197`). The serialized `RawCall.response` includes the logprob payload
  for forensic inspection.
- **FR-3 Public `Generator` Protocol seam unchanged.** No change to `Generator.generate(
context_chunks, question) -> AnswerWithSources` (`interfaces.py:17-31`). The confidence number
  rides **only** on `generate_with_stats` / `CallStats`. `GeminiGenerator.generate` continues to
  delegate to `generate_with_stats` and return only the `AnswerWithSources`
  (`gemini_generator.py:159-162`).
- **FR-4 Validation re-run (logprobs on, full 500, no judge needed).** A dev/throwaway driver
  re-runs Gemini over the full 500-question set with logprobs enabled, basing config on
  `configs/gemini-only.yaml` (`gemini-2.5-flash-lite`, `cost_ceiling_usd: 5.0`). It captures, per
  `question_id`, the computed `confidence_score`. The judge is **not** run for this extraction
  (labels come from `baseline.jsonl`). The run honours the $5 ceiling (actual ≈ $0.64).
- **FR-5 Label join + signal-validation analysis.** A committed analysis script JOINs the re-run
  `(question_id → confidence_score, did_abstain_e2e)` against `results/baseline.jsonl` **filtered
  to `gen_ai.request.model == "gemini-2.5-flash-lite"`** on `question_id`, attaching
  `correct = (failure_mode == "correct")`. It computes **AUROC for three signals predicting
  `correct`**: (a) logprob/confidence alone, (b) abstention sentinel alone (`did_abstain_e2e`),
  (c) hybrid-OR (escalate if abstain OR confidence below a calibration-set threshold). It applies
  **held-out calibration/test split discipline** (calibration ~20% sets any reported threshold;
  test ~80% reports the discrimination metrics; never tune on test). The script is deterministic
  given the cached re-run + baseline inputs (no live API call at analysis time).
- **FR-6 Report artifact (AUROC table + separation plot).** A committed report (the ADR's
  supporting evidence, e.g. `docs/analysis/` or the ADR body) presents: the three-way AUROC table
  (logprob-alone / abstain-alone / hybrid-OR), the **escalation rate** the chosen operating point
  implies (to bound phase-2's cost estimate), and a **separation plot** of the confidence
  distribution for correct vs incorrect answers. The report frames the result honestly and
  **states no greenlight bar** — it presents evidence for a human phase-2 judgment call.
- **FR-7 ADR (the phase deliverable).** A new `docs/adr/00NN-*.md` (next free number) records:
  (1) the **signal choice** — hybrid abstention-OR-logprob, with first-token margin primary and
  `avg_logprobs` fallback, citing `docs/planning/research/sprint-7-escalation-signal-research.md`;
  (2) the **seam-widening decision** — confidence lives on `CallStats.confidence_score`,
  populated by the Gemini path only, the public `Generator` Protocol untouched; (3) the
  **validation evidence** (the FR-6 AUROC table + separation plot + escalation rate); (4) the
  **calibration-procedure-not-magic-number** convention (record the procedure, e.g. "threshold at
  the Nth percentile of the calibration split", not a brittle hard number); (5) the **logprob-
  availability outcome** under structured output (RISK-1) and which signal (first-token margin or
  `avg_logprobs`) was actually used; (6) the explicit **"no hard AUROC bar; phase-2 go/no-go is a
  human judgment call"** framing. ADR status `accepted`.
- **FR-8 Mirrored tests for both code changes.** `tests/eval/test_records.py` asserts the
  `CallStats.confidence_score` field (optional, defaulted `None`, round-trips). The Gemini
  extraction is tested in `tests/generation/test_gemini_generator.py` via the injected
  `FakeGeminiClient` (fake response carrying a logprob payload → asserts the computed
  `confidence_score`; missing logprobs → `None`) **and** the VCR cassette / replay path
  (ADR-0006) — never a mocked LLM API. Tests mirror `src/` (`tests/<pkg>/test_<module>.py`, each
  dir with `__init__.py`); no flat `tests/test_*.py`.

### Non-functional

- **NFR-1 Public seam contract is invariant.** The `Generator` Protocol
  (`generate(context_chunks, question) -> AnswerWithSources`) is byte-for-byte unchanged; the
  confidence number never appears on it. SPRINT.md success criterion 1 (no seam-contract change)
  is honoured at phase-1, before the router exists.
- **NFR-2 Cassette/replay testing — no mocked LLM API (ADR-0006).** Every test touching the
  Gemini API uses either the injected `FakeGeminiClient` (offline, deterministic) or a recorded
  VCR cassette under `tests/eval/cassettes/`. No `unittest.mock` of the genai client.
- **NFR-3 Backward-compatibility.** `CallStats.confidence_score` is `float | None = None`, so
  every prior `results/*.jsonl` line and every `CallStats`/`EvalRecord` reader (dashboard,
  report, inspect, triage, exporter) loads unchanged — Pydantic supplies the default for the
  absent key. Mirrors the `cost_usd: float | None` precedent (`records.py:32`). No reader is
  edited.
- **NFR-4 Determinism / lossless round-trip.** For a given `CallStats`, serialization is
  deterministic and `CallStats.model_validate_json(stats.model_dump_json()) == stats` with the
  new field. The analysis script is deterministic given the cached re-run + baseline inputs (it
  performs no live API call). Logprob extraction is defensive: absent/empty logprobs yield
  `confidence_score = None`, never a crash.
- **NFR-5 Cost ceiling ≤ $5.** The validation re-run honours `configs/gemini-only.yaml`'s
  `cost_ceiling_usd: 5.0` (the runner halts past it, `runner.py:158-227`); the actual Gemini
  500-question cost is ≈ $0.64. No baseline re-run, no Claude/OpenAI spend, no judge spend for the
  logprob extraction.
- **NFR-6 Held-out calibration/test split discipline.** Any threshold the report names is set on
  a calibration split and **never** tuned on the test split that reports the discrimination
  metric (UCCI / research Q6 protocol). The split is fixed by a documented seed before any
  threshold inspection.
- **NFR-7 Test mirror + house structure.** Tests live in `tests/eval/test_records.py` and
  `tests/generation/test_gemini_generator.py` (existing mirrored files, each package dir with
  `__init__.py`). `make lint test` is the gate. The dev re-run driver and the analysis script
  live where they don't pollute the production package surface (a `scripts/`-style or
  clearly-marked dev location, resolved at `/design`).

## Acceptance Criteria

Offline-checkable except where a real (cheap, capped) re-run is the deliverable. The schema /
round-trip / extraction ACs need no network (constructed `CallStats`, `FakeGeminiClient`, or VCR
cassette). The re-run AC (AC-5) and the analysis ACs (AC-6/7/8) consume the cached re-run +
`baseline.jsonl` — no live API at analysis time.

- **AC-1 (spike, gate on the approach) — logprob availability under structured output is
  confirmed FIRST.** Before the extraction code is finalized, a throwaway probe (or the first
  re-run sample) confirms whether `gemini-2.5-flash-lite` returns usable **token-level** logprobs
  with `response_mime_type="application/json"` active. The outcome is recorded: either (a)
  first-token margin is usable → it is the primary signal; or (b) JSON mode collapses per-token
  candidates → the documented `avg_logprobs` fallback is used. The ADR (FR-7 item 5) records
  which path was taken. This AC has **no numeric bar** — it gates the _implementation choice_,
  not the phase outcome.
- **AC-2 `CallStats.confidence_score` exists, optional, defaulted.** `CallStats` has a field
  `confidence_score` annotated `float | None` with default `None` (assert via
  `CallStats.model_fields`). A `CallStats` built without it round-trips
  (`model_validate_json(model_dump_json())` equals it) with `confidence_score is None`; one built
  with `confidence_score=0.42` round-trips losslessly and the key appears in the JSON.
- **AC-3 Gemini path populates `confidence_score`; others leave it `None`.** With a
  `FakeGeminiClient` returning a response carrying a logprob payload, `GeminiGenerator.
generate_with_stats` returns a `CallStats` whose `confidence_score` equals the value computed by
  the documented formula (first-token margin, or `avg_logprobs` fallback). With a fake response
  carrying **no** logprob payload, `confidence_score is None` (no crash). A non-Gemini generator's
  `CallStats` (and the retrieval-abstain stub, `runner.py:175-182`) has `confidence_score is None`.
- **AC-4 Public `Generator` seam unchanged.** `Generator.generate`'s signature is unchanged
  (`generate(context_chunks, question) -> AnswerWithSources`); `GeminiGenerator.generate` returns
  an `AnswerWithSources` (no confidence on it). Asserted by signature/return-type check and a
  test that `generate(...)` returns the bare answer. (Diff review confirms no `interfaces.py`
  contract change.)
- **AC-5 Validation re-run produces per-question confidence on the full 500, under the ceiling.**
  The re-run (logprobs on, `configs/gemini-only.yaml` basis, `limit: null` → 500) yields a cached
  artifact with one `confidence_score` per `question_id`, total cost ≤ $5 (≈ $0.64 actual), and
  the judge not invoked for the extraction. (Checked by artifact row count ≈ 500 and the run's
  cost log.)
- **AC-6 Label join is correct.** The analysis JOINs the re-run on `question_id` against
  `results/baseline.jsonl` **filtered to `gen_ai.request.model == "gemini-2.5-flash-lite"`**,
  attaching `correct = (failure_mode == "correct")`. (Checked: joined row count matches the
  Gemini-filtered baseline slice; spot-checked `correct` labels match `failure_mode`.)
- **AC-7 Three-way AUROC is computed and reported.** The script computes and the report presents
  AUROC for **(a) logprob/confidence alone, (b) abstention sentinel alone, (c) hybrid-OR**,
  predicting `correct`, on the held-out **test** split. The numbers are reported as evidence;
  **no AC asserts a minimum AUROC** (decision 2). (Checked: three AUROC values present in the
  report/ADR, computed on the test split.)
- **AC-8 Calibration/test split discipline is applied.** The split (≈20% calibration / ≈80%
  test) is fixed by a documented seed before threshold inspection; any reported threshold is set
  on calibration and the AUROC/escalation-rate is reported on test. (Checked: the script never
  fits the threshold on the test rows; the seed/split is recorded.)
- **AC-9 Separation plot + escalation rate are in the report.** The report/ADR contains a
  separation plot of the confidence distribution for correct vs incorrect answers and states the
  escalation rate at the chosen operating point. (Checked: plot artifact committed; escalation-
  rate figure present.)
- **AC-10 ADR exists and is complete.** `docs/adr/00NN-*.md` exists, `Status: accepted`, and its
  body contains: the signal choice (+ research citation), the seam-widening decision (confidence
  on `CallStats`, Protocol untouched), the validation evidence (AC-7/9), the calibration-
  procedure-not-magic-number convention, the RISK-1 logprob-availability outcome, and the
  explicit "no hard AUROC bar; phase-2 go/no-go is a human judgment call" framing. (Checked by
  section/keyword assertions.)
- **AC-11 Tests pass and use no mocked LLM API.** `make lint test` is green. The Gemini
  extraction tests use the injected `FakeGeminiClient` and/or a VCR cassette (ADR-0006), never
  `mock`ing the genai client. Tests are in the mirrored `tests/eval/test_records.py` /
  `tests/generation/test_gemini_generator.py` (no flat `tests/test_*.py`).

## Resolved Open Questions

`AskUserQuestion` is unavailable to this subagent. The BRAINSTORM's 5 open questions are resolved
below; **OQ-2, OQ-3, OQ-4 are already ratified by the user** (the three fixed scope decisions in
the header — not re-asked). OQ-1 and OQ-5 are resolved to research-aligned defaults and flagged as
**unconfirmed assumptions** for the orchestrator to skim before `/design`; neither changes the
MUST surface.

- **OQ-1 (BRAINSTORM Q1) Do logprobs work under structured JSON output? → RISK-1, with
  `avg_logprobs` fallback.** **Resolved: this is the first thing the phase confirms (AC-1), not a
  blocker resolved now.** First-token margin is the primary signal _if_ JSON mode exposes
  per-token candidates; if it collapses to a single JSON-blob token, the documented fallback is
  response-level `avg_logprobs`. The extraction (FR-2) handles both; the ADR (FR-7 item 5) records
  which was used. _Unconfirmed until the probe runs — carried as RISK-1, the top risk into
  `/design`._
- **OQ-2 (BRAINSTORM Q2) Where does the confidence number live? → `CallStats.confidence_score`,
  persisted.** **Resolved (user-ratified): option (a) — add the optional field to `CallStats`**,
  so it persists into `EvalRecord.generation` for forensics/replay, rather than a side-channel
  return. Encoded as FR-1 / AC-2. _Fixed scope decision 1._
- **OQ-3 (BRAINSTORM Q3) What AUROC bar greenlights phase-2? → no hard bar; report only.**
  **Resolved (user-ratified): no numeric bar.** Phase-1 reports the three-way AUROC + separation
  plot as evidence; the phase-2 go/no-go is a human judgment call at `/design`. Encoded across
  FR-6/FR-7 and AC-7 (which asserts the numbers exist, not that they clear a threshold). _Fixed
  scope decision 2._
- **OQ-4 (BRAINSTORM Q4) Dev-20 or full 500 for validation? → full 500.** **Resolved
  (user-ratified): full 500** (≈ $0.64, under the $5 ceiling; 20 questions give a meaningless
  AUROC). Encoded as FR-4 / AC-5, with the ≈20/80 calibration/test split (FR-5 / AC-8). _Fixed
  scope decision 3._
- **OQ-5 (BRAINSTORM Q5) ADR records a threshold value or a calibration procedure? →
  procedure.** **Resolved: record the calibration _procedure_** (e.g. "threshold at the Nth
  percentile of the calibration-split confidence"), not a brittle dataset-specific number, since
  the question set may drift. Encoded as FR-7 item 4 / AC-10. _Unconfirmed assumption — low risk;
  matches the UCCI/research-Q6 durability argument and the BRAINSTORM lean._

## Infrastructure Readiness

| Dependency                                                                                                              | Type         | KB domain                                   | Specialist   | Status                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gemini token-level logprob API (`response_logprobs`/`logprobs` in `GenerateContentConfig`) under structured JSON output | external API | rag-generation (`gemini-structured-output`) | —            | **Probe-gated (RISK-1)** — research confirms `avg_logprobs`/`response_logprobs` exist on the response; token-level availability **under `response_mime_type="application/json"`** is unverified → AC-1 confirms it first; `avg_logprobs` fallback documented (FR-2) |
| `eval/records.py::CallStats` (add `confidence_score: float \| None = None`)                                             | module       | rag-eval (`stats-capture-seam`)             | —            | Ready — optional-default precedent is `cost_usd: float \| None` (`records.py:32`); persists into `EvalRecord.generation` (`records.py:88`) with no `EvalRecord` change                                                                                              |
| `generation/gemini_generator.py::generate_with_stats` (read logprobs → confidence)                                      | module       | rag-generation (`gemini-structured-output`) | —            | Ready — seam method already returns `CallStats` (`gemini_generator.py:164-224`); defensive read pattern exists (token accounting, `:193-197`); only the Gemini path is touched                                                                                      |
| `generation/interfaces.py::Generator` (public seam — must stay unchanged)                                               | module       | rag-generation (`generator-seam`)           | —            | Ready — invariant; confidence rides `generate_with_stats`/`CallStats` only (FR-3 / AC-4)                                                                                                                                                                            |
| `results/baseline.jsonl` (label source; filter to `gemini-2.5-flash-lite`, join on `question_id`)                       | data         | rag-eval (`eval-record-schema`)             | —            | Ready — verified 1500 rows (3×500), classified; `failure_mode`/`did_abstain_e2e`/`question_id` present; `correct = failure_mode == "correct"`                                                                                                                       |
| `eval/failure_taxonomy.py::FailureMode.CORRECT` (`correct` label definition)                                            | module       | rag-eval (`failure-taxonomy`)               | —            | Ready — `CORRECT == "correct"` (`failure_taxonomy.py:27`); terminal cascade branch (`:92-106`)                                                                                                                                                                      |
| `configs/gemini-only.yaml` (re-run config basis; logprobs on)                                                           | config       | rag-eval (`eval-config`)                    | —            | Ready — `gemini-2.5-flash-lite`, `limit: null` (500), `cost_ceiling_usd: 5.0`, prices set; needs a logprobs-on variant for the re-run driver (judge not needed for extraction)                                                                                      |
| Cassette/replay test pattern (ADR-0006) for the Gemini extraction test                                                  | tests        | rag-eval (`cassette-replay-eval`)           | —            | Ready — `@pytest.mark.vcr` `test_live_replay` + `FakeGeminiClient` exist in `tests/generation/test_gemini_generator.py`; cassette dir `tests/eval/cassettes/`                                                                                                       |
| AUROC / separation-plot analysis (sklearn `roc_auc_score`, matplotlib)                                                  | dep          | rag-eval (`signal-validation`, new concept) | —            | Confirm libs present at `/design` (likely already via existing report tooling); no new KB blocks phase-1                                                                                                                                                            |
| `/update-kb rag-generation` (router/cascade `RouterGenerator` pattern)                                                  | KB           | rag-generation                              | kb-architect | **Correctly deferred (not a phase-1 gap)** — Sprint-Wide Knowledge Plan lands it **after the phase-2 ADR**; the router does not exist yet                                                                                                                           |
| `/update-kb rag-eval` (`cost-per-correct-answer` metric)                                                                | KB           | rag-eval                                    | kb-architect | **Deferred to ≈ phase-3** (Sprint-Wide Knowledge Plan) — not a phase-1 concern                                                                                                                                                                                      |

**No new KB, agent, command, or `--deep-research` needed for phase-1.** The signal research is
already done (`docs/planning/research/sprint-7-escalation-signal-research.md`, "Sufficient" per the
BRAINSTORM coverage table). Every code dependency maps to an existing module + existing
`rag-generation` / `rag-eval` domain. The **only readiness flag is RISK-1** (Gemini token-level
logprob availability under structured output), which is _deliberately_ the phase's first
acceptance criterion (AC-1) with a documented `avg_logprobs` fallback — a contingency, not a
blocker. The router/cascade KB work is deferred by the sprint plan to after phase-2, so no KB work
blocks phase-1.

## Out of Scope (Won't — Phase 1)

- **Implementing `RouterGenerator`** — phase-2; phase-1 produces the signal + the validated
  contract only (BRAINSTORM Won't; SPRINT.md phase 2).
- **A threshold sweep / Pareto frontier** — phase-3; phase-1 reports one operating point as
  evidence, not a full sweep (BRAINSTORM Won't; SPRINT.md phase 3).
- **Wiring logprobs for the Anthropic or OpenAI generators** — Anthropic exposes no token
  logprobs; OpenAI is not the cheap model. Phase-1 is Gemini-only; other generators leave
  `confidence_score = None` (FR-1).
- **Any change to the public `Generator` Protocol contract** — invariant (NFR-1 / FR-3 / AC-4).
- **Self-consistency / semantic-agreement signal** — cost math fails at our 2.7× price ratio
  (BRAINSTORM Approach D, ruled out).
- **Retrieval-score gating as a standalone signal** — raw RRF is not query-comparable (research
  Q4); not pursued when logprob is available.
- **Setting a numeric AUROC greenlight bar** — explicitly excluded (decision 2); the phase-2
  go/no-go is a human judgment call at `/design`.
- **Re-running the baseline (Claude/OpenAI) or the judge for label generation** — labels come
  from the existing `results/baseline.jsonl`; only Gemini is re-run, logprobs-only, no judge.
- **`/update-kb` for the router/cascade or cost-per-correct-answer pattern** — deferred to after
  phase-2 / ≈ phase-3 by the Sprint-Wide Knowledge Plan.

## Clarity Score

| Dimension        | Score          | Note                                                                                                                                                                                                                                                                                                                                                 |
| ---------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem          | 3              | Root cause + evidence: offline judge can't be the inference-time signal (SPRINT.md core risk); Gemini's dominant failure is confident hallucination (46 vs 10; faithfulness 78.6%; abstain recall 70.0% — `over-abstention.md`); seam confirmed at `generate_with_stats`/`CallStats`; label source + join + `correct` definition verified in source. |
| Users            | 3              | Named roles with workflow impact: phase-2 `RouterGenerator` author (direct), the phase-2 go/no-go reviewer, `CallStats`/JSONL readers (backward-compat constraint), ADR-0006 (cassette), the ADR author, deferred `/update-kb`.                                                                                                                      |
| Success          | 3              | 11 falsifiable ACs: logprob-availability spike (AC-1), field optional/defaulted + round-trip, Gemini-only population, public-seam-unchanged, 500-question capped re-run, correct label join, three-way AUROC reported (no bar), split discipline, separation plot + escalation rate, ADR complete, no-mocked-LLM tests.                              |
| Scope            | 3              | MoSCoW inherited from BRAINSTORM with an explicit Won't list; the three big scope ambiguities are user-ratified and encoded as fixed FRs (seam-wiring, no-AUROC-bar, full-500); OQ-1/OQ-5 resolved to research-aligned defaults and flagged.                                                                                                         |
| Constraints      | 3              | All named: public seam invariant, cassette/replay (no mocked LLM, ADR-0006), backward-compat (optional+default), determinism + defensive extraction, ≤$5 ceiling, held-out calibration/test split (no tuning on test), calibration-procedure-not-magic-number, test mirror.                                                                          |
| **Total: 15/15** | **PASS (≥12)** | Gate passed. The three central ambiguities were pre-resolved by the user; OQ-1 (logprob availability under structured output) is carried forward as **RISK-1 / AC-1**, not a clarity gap. OQ-5 (procedure-not-number) is a low-risk unconfirmed assumption. No `AskUserQuestion` needed.                                                             |

## Next Step

→ `/design sprint-7/phase-1-escalation-signal`
