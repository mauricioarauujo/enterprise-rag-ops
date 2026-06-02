# BRAINSTORM: phase-11-readme-results — README Pass + Published Results + rag-inspect

**Sprint/Phase:** sprint-4/phase-11-readme-results | **Date:** 2026-06-01

---

## Problem Statement

The current `README.md` is 36 lines and generic — it has no architecture, no numbers,
and no finding. The entire point of Sprint 4 is to make the eval + observability
differentiator legible to a hiring-manager-level reviewer in two minutes. The README
is that front door. This phase must also resolve a concrete publication decision (which
artifact to commit as the canonical 3-way baseline) and ship a minimal `rag-inspect`
CLI that both grounds the writeup with a real example and verifies that the
over-abstention finding is model behaviour, not a harness gate artifact — the
finding-before-evidence risk flagged in SPRINT.md.

---

## Suggested Research & KB Work

| Topic                                                                                                 | Coverage                                                                       | Action |
| ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------ |
| README structure, portfolio framing                                                                   | Sufficient — no KB needed; this is writing, not engineering                    | None   |
| Abstention gate mechanics (`ABSTENTION_THRESHOLD=0.45`, `did_abstain_retrieval` vs `did_abstain_e2e`) | Sufficient — code read in this session                                         | None   |
| `rag-inspect` CLI pattern                                                                             | Sufficient — `classify_cli.py` establishes the JSONL+gold join pattern exactly | None   |
| `failure_taxonomy.classify` cascade                                                                   | Sufficient — `failure_taxonomy.py` fully read                                  | None   |
| `.gitignore` negation rules for `results/`                                                            | Confirmed — `results/*` with negations only for `baseline.{html,md,jsonl}`     | None   |

None — coverage is sufficient. This is a Polish phase; no new KB or deep research is needed.

---

## Fork Resolution: Key Facts from File Reads

Before approaches, three concrete facts ground the decisions:

**F1 — run_id provenance.** `baseline-3way.jsonl` (1499 records) mixes three `run_id`
values: `baseline` (gpt-5-nano, 999 records of the original 2-way file), then
`baseline-anthropic` (claude-haiku, 500 records), then `gemini` (gemini-2.5-flash-lite,
500 records). These were produced by separate sweep runs and merged. The heterogeneous
`run_id` is honest — it records provenance accurately — but it needs a note in the
README if published.

**F2 — .gitignore state.** `results/*` catches everything in `results/`; only three
files are re-included: `baseline.html`, `baseline.md`, `baseline.jsonl`. A file named
`baseline-3way.jsonl` is NOT negated and is currently gitignored. To publish it,
the `.gitignore` must be amended.

**F3 — abstention finding verifiability without corpus hydration.** An
`abstention_error` on an answerable question looks like: `retrieval_ranked_ids` is
non-empty (retrieval succeeded, the gate did NOT fire), `did_abstain_e2e=True` (the
generator refused anyway), `expected_doc_ids` non-empty (question was answerable), and
`failure_mode="abstention_error"`. All of these fields are present in `EvalRecord` and
`Question`. No doc content is needed to confirm the finding — the fact that retrieval
succeeded (`retrieval_ranked_ids` contains gold doc IDs) but the model abstained is
the whole story. Doc content adds colour, not proof.

---

## Approaches Considered

### Fork 1: Publish strategy for the 3-way artifact

| Approach                                            | Description                                                                                                                                                              | Pros                                                                                                                                                          | Cons                                                                                                                                                                                                                                                                                                                                                                                             | Effort |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A — Replace committed baseline                      | Rename current `baseline.{jsonl,html,md}` to the 3-way file (update `.gitignore` negations, regenerate HTML/MD with `rag-report`). The published baseline becomes 3-way. | Single canonical artifact; `make dash` works immediately on a fresh clone; cloneable principle fully met; reviewers see 3-way numbers from first `git clone`. | The `baseline` `run_id` is misleading (two of three runs have different IDs: `baseline-anthropic`, `gemini`). The file size jumps from ~1 MB (999 records) to ~1.5 MB (1499 records) — acceptable for a portfolio repo. Rewrites git-tracked artifact.                                                                                                                                           | S      |
| B — Commit new `baseline-3way.*` alongside existing | Add `baseline-3way.{jsonl,html,md}` as new tracked files by amending `.gitignore`; keep `baseline.jsonl` as the legacy 2-way artifact.                                   | No breakage of the existing tracked file; provenance is explicit in the name.                                                                                 | Two parallel baselines confuse reviewers; `make dash` (reads `results/*.jsonl`) loads both and double-counts gpt-5-nano (it appears in both files). Dashboard logic uses `gen_ai.request.model` as group key — two files with overlapping models means merged aggregates, not separate runs. Must patch `discover_results_paths` to exclude the old 2-way, or the dashboard shows wrong numbers. | M      |
| C — Keep gitignored, static table + screenshot only | Do not commit any 3-way JSONL. Embed the results table directly in the README as markdown and include a dashboard screenshot.                                            | Zero repo-size impact; no `.gitignore` edit.                                                                                                                  | Reviewer cannot reproduce numbers from a fresh clone — violates the clone-reproducibility principle (SPRINT.md success criterion: "fresh clone can run the dashboard and read real results"). The finding is asserted but not verifiable. A portfolio claim without a verifiable artifact is weaker than one with one.                                                                           | S      |

**Recommendation for Fork 1:** Approach A. Replace `baseline.{jsonl,html,md}` with
the 3-way version. Add a one-line provenance note in the README (the three `run_id`
values reflect three sweep runs merged post-hoc). The ADR-0004 cloneable principle is
fully met; the 1.5 MB size is portfolio-acceptable; and a single canonical file means
the dashboard works correctly without any code changes.

---

### Fork 2: rag-inspect scope

| Approach                                           | Description                                                                                                                                                                                                                                                                                                                                        | Pros                                                                                                                                                                                                                                                          | Cons                                                                                                                                                                                                                                                                                                                             | Effort |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A — JSONL+gold only (text + metrics)               | `rag-inspect <question_id> [--results path] [--model model]`: streams gold from `load_questions`, loads the matching `EvalRecord(s)` from JSONL, prints question text, gold answer_facts, each model's answer, retrieval_ranked_ids (with gold doc IDs highlighted), failure_mode, key metrics (fact_recall, faithfulness_ratio, did_abstain_e2e). | Directly verifies the finding: shows retrieval_ranked_ids contains gold doc IDs (retrieval succeeded) while did_abstain_e2e=True (model abstained). Reuses existing patterns exactly (classify_cli.py join pattern). No new dependencies. One focused module. | Does not show the text of the retrieved docs — a reviewer cannot read what the model saw in context. Sufficient for verification but not for full story-telling in the writeup.                                                                                                                                                  | S      |
| B — JSONL+gold + `--enrich-from-index` doc content | Add optional flag: if set, loads `data/processed/corpus.jsonl` and hydrates each retrieved chunk ID into readable text.                                                                                                                                                                                                                            | Full story: reviewer sees question → retrieved context → model answer → failure mode. Makes the writeup's concrete example richer.                                                                                                                            | Corpus is gitignored (900 KB–90 MB depending on DOCS_PER_SOURCE); requires a prior `make download-data` + `make build-index`. Adds a Path argument and corpus-parsing logic. The verification of the finding does not require this — it is scope creep for Phase 11. Phase 12 (writeup) can add `--enrich-from-index` if needed. | M      |

**Recommendation for Fork 2:** Approach A (JSONL+gold only). The verification of the
finding requires showing that retrieval succeeded (gold IDs are in `retrieval_ranked_ids`)
while the model abstained — all available without corpus hydration. `--enrich-from-index`
is explicitly flagged as a Should (not Must) and deferred to Phase 12 if the writeup
needs it.

---

### Fork 3: README structure

| Approach                                                  | Description                                                                                                                                                                                                                                                                                                 | Pros                                                                                                                                | Cons                                                                                                                                                          | Effort |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A — Results-first, skimmable sections                     | Headline (what + why differentiated), architecture (ASCII diagram + component table), the 3-way results table + the finding (abstention↔hallucination tradeoff), quickstart/reproduce (make targets, ~15 min), ADR index, dashboard screenshot. Finding is the hook; architecture is the credibility layer. | Matches the 2-minute reviewer pattern. Numbers first, then "how." ASCII diagram is repo-native (no binary blob, renders in GitHub). | Requires care to keep it skimmable at ~150–200 lines without padding.                                                                                         | S      |
| B — Standard README order (what, install, usage, results) | Classic README: overview → setup → commands → results → contributing                                                                                                                                                                                                                                        | Familiar structure; easier to write.                                                                                                | Buries the differentiator (eval + numbers) below setup boilerplate — a skimmer who stops at line 30 misses the point entirely. Wrong for a portfolio project. | S      |

**Recommendation for Fork 3:** Approach A. Results-first, finding as the hook, ASCII
diagram for architecture, ADR index as the decision trail.

---

## Recommended Approach

Execute all three forks as recommended:

1. **Publish strategy (Fork 1-A):** Replace `baseline.{jsonl,html,md}` with the 3-way
   artifact (1499 records, three models). Update `.gitignore` — the negations stay the
   same filenames so no change is needed. Regenerate `baseline.html` and `baseline.md`
   by running `rag-report` (or equivalent) against the new JSONL. Add a provenance note
   in the README.

2. **rag-inspect scope (Fork 2-A):** JSONL+gold only. One new module
   `src/enterprise_rag_ops/eval/inspect_cli.py` with an `rag-inspect` entry point.
   Accepts `--results`, `--question-id`, optional `--model`. Streams gold from
   `load_questions(question_ids=[...])`, loads matching records from the JSONL, prints
   the full story in plain text (question → gold facts → per-model: answer,
   retrieval_ranked_ids with gold overlap highlighted, failure_mode, metrics). Registers
   as a `pyproject.toml` console script.

3. **README (Fork 3-A):** Rewrite as results-first with the finding as the hook. Sections:
   What it is / What it is not (existing, keep) → Architecture (ASCII diagram + components
   - ADR index) → Results (3-way table + the finding: abstention↔hallucination tradeoff)
     → Quickstart (make targets, ~15 min path from `git clone` to `make dash`) → Reproduce
     → License.

**Verification gate (non-negotiable):** Before finalising the README's "finding" section,
run `rag-inspect` on 3–5 representative `abstention_error` cases from the 3-way JSONL.
Confirm that `retrieval_ranked_ids` contains gold doc IDs (retrieval succeeded) and
`did_abstain_e2e=True` (generator decided to abstain). This confirms the finding is
model behaviour, not the 0.45 dense-cosine gate. The gate fires `did_abstain_retrieval=True`
(empty ranked list) — those records would be `retrieval_miss` or `abstention_error` for
a different reason. The actual pattern to look for: `did_abstain_retrieval=False` AND
`retrieval_ranked_ids` contains gold IDs AND `did_abstain_e2e=True` AND
`expected_doc_ids` is non-empty. If that pattern is prevalent in the claude-haiku
abstention_error cases (262 of 500), the finding is real.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                 |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | Replace committed `baseline.{jsonl,html,md}` with the 3-way version (1499 records, 3 models)                                                                         |
| **Must**   | Regenerate `baseline.html` and `baseline.md` from the 3-way JSONL                                                                                                    |
| **Must**   | `rag-inspect <question_id>` CLI: JSONL+gold join, prints question text, gold facts, per-model answer + retrieval_ranked_ids + failure_mode + metrics                 |
| **Must**   | Verify the over-abstention finding is model behaviour (not the 0.45 gate) using rag-inspect on representative cases before writing the finding into the README       |
| **Must**   | README rewrite: what-it-is + architecture (ASCII diagram) + 3-way results table + the finding (abstention↔hallucination tradeoff) + quickstart/reproduce + ADR index |
| **Should** | Dashboard screenshot committed to `docs/` and embedded in the README                                                                                                 |
| **Should** | `rag-inspect --enrich-from-index` flag for corpus-level doc-content hydration (deferred to Phase 12 if writeup needs it)                                             |
| **Could**  | A `make reproduce` script that documents the full end-to-end sweep path (for a reader who wants to re-run, not just read results)                                    |
| **Won't**  | Re-run any eval sweeps or change eval logic                                                                                                                          |
| **Won't**  | New eval features, new metrics, new generators                                                                                                                       |
| **Won't**  | Fancy web frontend, interactive dashboard beyond `make dash`                                                                                                         |
| **Won't**  | Chase SOTA scores or tune the RAG pipeline                                                                                                                           |
| **Won't**  | Leaderboard submission (Phase 13)                                                                                                                                    |
| **Won't**  | Written analysis / writeup (Phase 12)                                                                                                                                |

---

## Infrastructure / Risk Flags

**Risk 1 (HIGH — blocks publication): Finding-before-evidence.** The over-abstention
finding must be confirmed as model behaviour before it is published. The abstention
gate (`ABSTENTION_THRESHOLD=0.45` on top-1 dense cosine) controls `did_abstain_retrieval`
— when it fires, `retrieval_ranked_ids` is empty and the generator receives no context,
making abstention unsurprising. The interesting finding is generator abstention on
_good_ retrieval: `did_abstain_retrieval=False` AND gold IDs present in
`retrieval_ranked_ids` AND `did_abstain_e2e=True`. `rag-inspect` must confirm this
pattern is prevalent in the claude-haiku 262 abstention_error cases before the finding
is stated in the README. If the finding is mostly gate-forced (poor retrieval + model
abstains), the claim "retrieval succeeds, model over-abstains" is unsupported.

**Risk 2 (LOW): Repo size.** Replacing the committed `baseline.jsonl` (~1 MB, 999
records) with the 3-way version (~1.5 MB, 1499 records) adds ~0.5 MB to the tracked
tree. For a portfolio repo this is acceptable; no LFS needed. If HTML/MD are also
regenerated and committed, total tracked results size stays well under 5 MB.

**Risk 3 (LOW): Dashboard double-load.** `discover_results_paths()` in `dashboard/data.py`
discovers all `results/*.jsonl`. After the replacement, there will be exactly one tracked
JSONL (`baseline.jsonl`, now 3-way), so the dashboard loads all three models from a single
file — correct and no code change needed. Risk only materialises if Approach B (two files)
had been chosen.

**Risk 4 (LOW): run_id heterogeneity.** The three `run_id` values (`baseline`,
`baseline-anthropic`, `gemini`) are accurate records of provenance but look inconsistent.
A one-sentence README note — "Results were produced in three separate sweep runs and
merged; `run_id` records each run's origin" — is sufficient. No data change is needed.

---

## Open Questions

1. **`rag-inspect` output format.** Plain text (human-readable terminal output) or
   structured Markdown (suitable for pasting into the writeup)? The minimal path is plain
   text with clearly labelled sections; Markdown formatting can be added as a `--format
md` flag. Recommend plain text as default, `--format md` as optional — but the
   decision affects the module's output logic and the pyproject.toml entry point signature.

2. **Dashboard screenshot workflow.** Should the screenshot be committed as a static
   image in `docs/assets/` (zero setup, always current at commit time, binary in git),
   or generated/linked programmatically? Given the "minimal scope" guard, a one-time
   committed PNG is simplest — but it requires a local `make dash` run and a manual
   screenshot during phase implementation. Is there a preferred image path and filename
   convention?

3. **`baseline.html` and `baseline.md` regeneration.** The committed `baseline.md` and
   `baseline.html` are the 2-way reports (gpt-5-nano only). After replacing `baseline.jsonl`
   with the 3-way version, they must be regenerated via `rag-report` (if that CLI exists)
   or `render_report()` directly. Confirm: is `rag-report` a registered console script in
   `pyproject.toml`, or does regeneration need a one-off Python invocation?

4. **ADR index format in README.** Should the ADR index in the README be a simple table
   (| ADR | Title | Decision |) or brief inline bullets? The table is more scannable for
   a reviewer who wants to quickly understand the decision trail; bullets are lighter.
   Both are equivalent in effort; the table is more professional for a portfolio context.

5. **`rag-inspect` entry-point name collision check.** The `pyproject.toml` currently
   registers `rag-ingest`, `rag-index`, `rag-ask`, `rag-eval`, `rag-classify`. Confirm
   `rag-inspect` is not already registered and that the naming is consistent with the
   existing pattern before wiring the console script.

---

## Next Step

→ `/define sprint-4/phase-11-readme-results`
