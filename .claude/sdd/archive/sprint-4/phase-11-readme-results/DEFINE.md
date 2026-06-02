# DEFINE: phase-11-readme-results — README Pass + Published Results + rag-inspect

**Sprint/Phase:** sprint-4/phase-11-readme-results | **Date:** 2026-06-01

This phase turns the eval + observability substrate into a public, reviewable artifact:
it (1) publishes the canonical three-way baseline, (2) ships a thin read-only
`rag-inspect` CLI, (3) **uses that CLI to verify the headline over-abstention finding is
genuine model behaviour — not the 0.45 retrieval gate firing — before the finding is
written into the README**, and (4) rewrites the README results-first. The verification
gate is the spine: it is what makes the README a credible portfolio artifact rather than
an over-claimed one.

All three brainstorm forks are resolved (BRAINSTORM § Fork Resolution):
Fork 1 = Replace; Fork 2 = `rag-inspect`, JSONL+gold only; Fork 3 = results-first README.
This DEFINE does not re-open them.

---

## Requirements

### Functional

Each is testable and MoSCoW-tagged. "Gold overlap" everywhere means: the intersection
of `EvalRecord.retrieval_ranked_ids` with the gold `Question.expected_doc_ids` for that
`question_id` (both fields confirmed present in `eval/records.py` and `eval/questions.py`).

- **FR-1 (Must) — Replace the published baseline JSONL.** Overwrite the git-tracked
  `results/baseline.jsonl` with the three-way data currently on disk at
  `results/baseline-3way.jsonl` (gitignored): 1499 records across 3 models
  (`gpt-5-nano`, `claude-haiku`, `gemini-2.5-flash-lite`). No `.gitignore` change is
  needed — `results/baseline.{html,md,jsonl}` are already negated by name (BRAINSTORM F2).
  Heterogeneous `run_id`s (`baseline` / `baseline-anthropic` / `gemini`) are preserved
  as honest provenance and covered by a README note (FR-5f); the data is not rewritten.

- **FR-2 (Must) — Regenerate the published reports.** Re-render `results/baseline.html`
  and `results/baseline.md` from the replaced JSONL via
  `rag-eval report --results results/baseline.jsonl` (the `report` subcommand exists in
  `eval/cli.py`; there is **no** `rag-report`). Both reports must reflect all three
  models. Regeneration is deterministic (`render_report` is pure over the JSONL).

- **FR-3 (Must) — `rag-inspect` CLI: join EvalRecord + gold Question.** A new
  `rag-inspect` console script (confirmed free; current scripts are
  rag-ingest/index/ask/eval/export-traces/classify). For a given `--question-id`, it
  joins the matching `EvalRecord`(s) from a results JSONL with the gold `Question` from
  `load_questions(question_ids=[...])` and prints:
  - the **question text** (`Question.question`) and gold **answer_facts**
    (`Question.answer_facts`);
  - the gold **expected_doc_ids**;
  - per model: `answer`, `sources`, `retrieval_ranked_ids` with **gold overlap
    highlighted**, `failure_mode`, `fact_recall`, `faithfulness_ratio`, and the **three
    abstention flags** `did_abstain_retrieval` / `did_abstain_e2e` (and, by overlap, the
    "retrieval succeeded" signal).
    Optional `--results` (default `results/baseline.jsonl`) and `--model` (filter to one
    model). **JSONL + gold only — no corpus/doc-content hydration** (`--enrich-from-index`
    is a Should, deferred to Phase 12). Read-only: `rag-inspect` never writes results.

- **FR-3a (Must) — Testability seam for the join/format logic.** The join + gold-overlap
  - per-model structuring logic lives in a **pure, importable function** (e.g.
    `inspect_question(records, question, ...) -> structured result`) that takes already-loaded
    records + the gold `Question` and returns a plain data structure (no I/O, no
    `argparse`, no `print`). The CLI shell (`argv` parse → load JSONL → `load_questions`
    → call the pure function → format/print → exit code) wraps it. This mirrors the
    pure-data/thin-CLI split in `dashboard/data.py` and `classify_cli.py` — the load +
    atomic boundary pattern of `classify_cli.py`, minus the write (inspect is read-only).

- **FR-4 (Must) — Finding-before-evidence verification using `rag-inspect`.** Before the
  README finding section (FR-5d) is written, `rag-inspect` must be used to confirm the
  over-abstention is **generator behaviour**, not the `ABSTENTION_THRESHOLD=0.45`
  retrieval gate (`retrieval/config.py`) firing. The genuine pattern, per record, is:
  `did_abstain_retrieval == False` **AND** gold IDs present in `retrieval_ranked_ids`
  (retrieval succeeded — gold overlap non-empty) **AND** `did_abstain_e2e == True`
  (the generator abstained anyway). FR-3 exists partly to make this pattern checkable
  from `rag-inspect` output. This FR is gated by the verification AC (AC-8) and feeds
  NFR-2. If the pattern does **not** dominate the inspected sample, FR-5d's finding must
  be re-worded to what the evidence supports.

- **FR-5 (Must) — Results-first README rewrite.** Replace the current 36-line README
  with a skimmable ~150–200-line results-first README. Each section is a sub-requirement:
  - **FR-5a — Architecture:** an ASCII pipeline diagram (no binary asset) plus a
    component table (ingest → retrieval → generation → eval → observability) and an
    **ADR index** (ADR-0001…0008 — table of ADR · title · decision; nine ADR files
    confirmed in `docs/adr/`).
  - **FR-5b — Three-way results table:** the published per-model numbers (correctness /
    fact recall / faithfulness / abstention errors / cost), sourced from the regenerated
    `baseline.md` (FR-2).
  - **FR-5c — What-it-is / what-it-is-not:** retained from the current README (the
    differentiator framing: eval + observability, not the RAG).
  - **FR-5d — The finding (evidence-backed):** the abstention↔hallucination tradeoff
    (claude-haiku over-abstains / most faithful / fewest hallucinations; gemini-flash-lite
    under-abstains / most hallucinations / cheapest; gpt-5-nano in between). This section
    is **gated by FR-4 / AC-8** — it may assert "retrieval succeeds, the model
    over-abstains" only if the verification confirms the genuine pattern dominates.
  - **FR-5e — Quickstart / reproduce:** a `git clone` → `make dash` path that reads the
    published results in ~15 minutes with no infra spin-up (ADR-0004 cloneable principle),
    plus the reproduce path for re-running.
  - **FR-5f — Provenance note:** one note explaining the three `run_id` values are three
    merged sweep runs.
  - **FR-5g — License:** retained.

### Should (in-scope-if-time, not gating)

- **FR-6 (Should) — Dashboard screenshot.** A committed dashboard screenshot embedded in
  the README (path/convention is an open question for `/design`).
- **FR-7 (Should) — `rag-inspect --enrich-from-index`.** Optional corpus doc-content
  hydration. Deferred to Phase 12 unless time permits; not required for FR-4.

### Could

- **FR-8 (Could) — `make reproduce`.** A make target documenting the full end-to-end
  sweep path for a reader who wants to re-run rather than just read.

### Won't (explicit — guards the polish-is-bottomless risk)

- Re-run any eval sweeps or change eval logic / metrics / generators.
- New eval features, new metrics, new judges.
- A web frontend or interactive dashboard beyond `make dash`.
- Chase SOTA scores or tune the RAG pipeline.
- The Phase-12 written analysis (~1500-word post).
- The Phase-13 leaderboard submission.

### Non-functional

- **NFR-1 — Clone reproducibility (ADR-0004).** From a fresh `git clone`, `make dash`
  shows the three-way numbers and a reviewer can read real results with no API keys or
  infra spin-up. The single canonical `baseline.jsonl` means `discover_results_paths()`
  loads exactly one tracked JSONL — no dashboard double-load (BRAINSTORM Risk 3).
- **NFR-2 — Evidence-backed finding.** No published claim exceeds what the JSONL
  supports. The FR-4 verification gate (and AC-8) is the enforcement mechanism: the
  README finding tracks the inspected evidence, not the desired narrative.
- **NFR-3 — Minimal scope.** README stays skimmable (~150–200 lines, no padding);
  `rag-inspect` is a thin, read-only tool reusing existing loaders/schema; no new eval
  logic is introduced.
- **NFR-4 — Repo size acceptable.** The ~1.5 MB three-way JSONL (vs ~1 MB prior) is
  portfolio-acceptable; no Git LFS (BRAINSTORM Risk 2).
- **NFR-5 — Testability seam.** `rag-inspect`'s join/format logic is pure and
  unit-testable offline without invoking the CLI or the network (see FR-3a, AC-6/AC-7).
- **NFR-6 — Determinism.** Report regeneration (FR-2) and the pure inspect function
  (FR-3a) produce identical output for identical inputs (no wall-clock, no network).

---

## Acceptance Criteria

Offline-checkable ACs are favoured; README content is a manual reviewer checklist (AC-9).
Per the tests-mirror-src convention, new tests live at
`tests/eval/test_inspect_cli.py` with an `__init__.py` in `tests/eval/`.

1. **AC-1 (FR-1) — JSONL replaced.** After replacement, `results/baseline.jsonl` parses
   to **1499** `EvalRecord`s and exactly **3** distinct `gen_ai.request.model` values
   (`gpt-5-nano`, `claude-haiku`, `gemini-2.5-flash-lite`). Offline-checkable by parsing
   the file.

2. **AC-2 (FR-2) — Reports regenerated, all three models.** `results/baseline.md` and
   `results/baseline.html` are regenerated via `rag-eval report` and each contains a
   summary row for all three models. Offline-checkable (string contains each model name).

3. **AC-3 (FR-3) — `rag-inspect` registered + the per-model story.** `rag-inspect` is a
   registered console script. For a real `question_id` present in `baseline.jsonl`, its
   output contains: the question text, gold `answer_facts`, gold `expected_doc_ids`, and
   per model the `answer`, `retrieval_ranked_ids` with gold overlap marked, the three
   abstention flags (`did_abstain_retrieval`, `did_abstain_e2e`), `failure_mode`,
   `fact_recall`, and `faithfulness_ratio`.

4. **AC-4 (FR-3) — No collision / no corpus dependency.** `rag-inspect` adds no new
   third-party dependency and reads only the results JSONL + the gold questions config —
   it does **not** require `data/processed/corpus.jsonl` or a built index.

5. **AC-5 (FR-3) — Read-only.** `rag-inspect` writes no files (no results mutation,
   distinguishing it from `rag-classify`'s atomic write).

6. **AC-6 (FR-3a, NFR-5) — Pure join/format unit-tested.** The pure inspect function,
   given a `question_id` (or pre-loaded records + gold `Question`), returns the gold +
   per-model structure with **gold overlap computed correctly** (intersection of
   `retrieval_ranked_ids` and `expected_doc_ids`) and the three abstention flags
   surfaced. Unit-tested against `results/baseline.jsonl` (real records), no network.

7. **AC-7 (FR-3) — CLI smoke.** `rag-inspect --question-id <real id>` imports and runs
   on a real `question_id` from `baseline.jsonl` and exits 0. Offline.

8. **AC-8 (FR-4, NFR-2) — Verification AC that GATES the finding (quantified,
   falsifiable).** From the **claude-haiku** `abstention_error` records in
   `baseline.jsonl` (≈262), draw a sample of **n ≥ 30** (proposed; exact n/threshold
   confirmed at `/design`). The **genuine pattern**
   (`did_abstain_retrieval == False` AND gold overlap non-empty AND
   `did_abstain_e2e == True`) must hold for **≥ 70%** of the sampled records (proposed
   threshold). This check is computed from the same fields `rag-inspect` surfaces and is
   offline-checkable over the JSONL.
   - **If the threshold holds:** FR-5d may assert "retrieval succeeds, the model
     over-abstains."
   - **If it does NOT hold:** FR-5d must be re-worded to what the evidence supports
     (e.g. "abstention is partly gate-forced"). The README must not over-claim.

9. **AC-9 (FR-5) — README section checklist (manual, reviewer-checkable).** The README
   contains, in order: what-it-is / what-it-is-not; architecture (ASCII diagram +
   component table + ADR index covering ADR-0001…0008); the three-way results table; the
   evidence-backed finding (consistent with AC-8); quickstart/reproduce; the provenance
   note; license. Length ~150–200 lines.

10. **AC-10 (FR-5e, NFR-1) — Reproduce path documented and works from a clean clone.**
    The README documents a `git clone` → `make dash` path that reads the published
    three-way results with no API keys / infra spin-up, in ~15 minutes.

---

## Clarity Score

| Dimension       | Score | Note                                                                                                                                                                                                                                                  |
| --------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**     | 3     | Root cause with evidence: the 36-line README hides the differentiator, and the over-abstention finding risks being a `0.45`-gate artifact, not model behaviour. The verification gate (FR-4/AC-8) addresses the named risk with code-grounded fields. |
| **Users**       | 3     | Named role + workflow: a hiring-manager-level reviewer who must grasp the eval+observability differentiator in ~2 minutes from a fresh clone (`make dash`); the secondary user is the Phase-12 writeup author who reuses `rag-inspect` evidence.      |
| **Success**     | 3     | Measurable + falsifiable: AC-1 (1499/3), AC-2 (3 models in reports), AC-6/AC-7 (unit + smoke), AC-8 (quantified ≥70% over n≥30, gates the finding), AC-10 (clone→dash ~15 min).                                                                       |
| **Scope**       | 3     | Full MoSCoW from BRAINSTORM, with an explicit Won't list (no re-runs, no new metrics, no web frontend, no Phase-12/13 work).                                                                                                                          |
| **Constraints** | 3     | All named: no `.gitignore` change (F2), `rag-eval report` not `rag-report`, JSONL+gold only (no corpus), ~1.5 MB no-LFS, single-file no double-load, read-only CLI, tech-agnostic README (no new KB), pure-function testability seam.                 |

**Total: 15/15 — PASS (≥12).** No clarifying questions required; all three forks were
resolved in BRAINSTORM and the load-bearing field names/CLI were confirmed against code.

---

## Infrastructure Readiness

| Dependency                                                                     | KB domain                                          | Specialist   | Status                                          |
| ------------------------------------------------------------------------------ | -------------------------------------------------- | ------------ | ----------------------------------------------- |
| `EvalRecord` schema (flags, `retrieval_ranked_ids`, `failure_mode`)            | `rag-eval` (eval-record-schema)                    | kb-architect | Ready — confirmed in `eval/records.py`          |
| `load_questions` / `Question` (`question`, `answer_facts`, `expected_doc_ids`) | `rag-eval` (questions loader)                      | kb-architect | Ready — confirmed in `eval/questions.py`        |
| JSONL+gold join + load boundary pattern (read-only variant)                    | `rag-eval`                                         | kb-architect | Ready — `eval/classify_cli.py` is the reference |
| `rag-eval report` subcommand (report regeneration)                             | `rag-eval` (eval-report-render)                    | kb-architect | Ready — `eval/cli.py` + `eval/report.py`        |
| Pure-data / thin-CLI testability seam                                          | `rag-eval` / dashboard                             | kb-architect | Ready — `dashboard/data.py` is the reference    |
| Failure-mode semantics (`abstention_error`) for the finding                    | `observability` (failure-taxonomy)                 | kb-architect | Ready — `observability` KB registered           |
| Abstention gate mechanics (`ABSTENTION_THRESHOLD=0.45`)                        | `rag-generation` / `rag-eval` (abstention-scoring) | kb-architect | Ready — `retrieval/config.py` + KB              |
| README / results / ASCII diagram / ADR index                                   | none (tech-agnostic writing)                       | —            | N/A — no KB needed                              |

**No `/new-kb` or `/new-agent` is required before `/design`.** The three relevant KB
domains (`rag-eval`, `observability`, `rag-generation`) all exist and are registered in
`.claude/kb/_index.yaml`; the README/results work is tech-agnostic writing.

---

## Open Questions (for `/design` only — thin)

These do not block the Clarity gate (all default to BRAINSTORM/SPRINT-aligned positions);
`/design` confirms the exact values.

1. **`rag-inspect` output format.** Plain text default vs. an optional `--format md` for
   pasting into the Phase-12 writeup. _Default: plain text; `--format md` deferred._
2. **Verification sample size + threshold (AC-8).** Proposed **n ≥ 30**, **≥ 70%**
   genuine-pattern. Confirm or tighten at `/design` (the full 262 population could be
   used instead of a sample, making it exhaustive rather than sampled).
3. **Dashboard screenshot (FR-6).** Path/filename convention (e.g. `docs/assets/…`) and
   whether it is in scope this phase.
4. **ASCII diagram exact shape (FR-5a).** Pipeline boxes/labels — a `/design` detail.
5. **`make reproduce` (FR-8, Could).** Whether the Could lands this phase.

---

## Next Step

→ `/design sprint-4/phase-11-readme-results`
