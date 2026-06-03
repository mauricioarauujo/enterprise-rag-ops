# DEFINE: sprint-6/phase-18-evalrecord-reasoning — Persist Judge Reasoning + Generation Input (ADR-0010)

**Sprint/Phase:** sprint-6/phase-18-evalrecord-reasoning | **Date:** 2026-06-02
**Approach:** Split by footprint, scoped amendment to ADR-0007 (BRAINSTORM Approach C, lighter
end). The **judge verdict lists** (`per_fact` / `per_citation`) are _discrete labels_ — small,
high-value, the actual "reasoning" a reviewer reads on a failed trace — so they go to **gold**
as optional, defaulted `EvalRecord` fields (backward-compatible exactly like `k` /
`failure_mode` / `retrieval_ranked_ids`), reusing the existing closed `eval/schema.py`
`FactVerdict` / `CitationVerdict` models. They are **already in memory** at the runner's
`EvalRecord` build site (`runner.py:227-246`; `verdict.per_fact` / `verdict.per_citation` from
the `judge_with_stats` call at `runner.py:187`) → populating them costs **zero extra API
calls**. The bulky parts (full generation input prompt embedding k=10 chunks, raw response
objects) are the bloat ADR-0007 feared → they go to a **gitignored bronze** archive
(`data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json`), which is **designed in
ADR-0010 and built-and-activated in Phase 19's re-run** (the cheap moment to capture, per the
planning note). This phase makes the data **persistable**; it does not re-run, does not hydrate
Phoenix, and does not build the bronze writer's wiring.

**Crisp scope call (the central decision this DEFINE owes /design + the user).** Phase 18 ships
**(a) the gold schema change** (`EvalRecord.per_fact` / `per_citation`, optional + defaulted),
**(b) the runner populating them** from the in-memory `verdict`, **(c) backward-compat tests**
(old JSONL loads; all 7 readers unaffected), and **(d) ADR-0010**. The **bronze writer is
DESIGNED in ADR-0010 (key scheme, idempotency, thread-safety, privacy, cassette-overlap call,
`.gitignore` entry) but NOT built here** — it is built and wired into the sweep in Phase 19,
where the raw response objects are already in memory and the re-run is being paid for anyway.
Rationale: a new thread-safe write path + its tests is pure scope creep
in a phase whose deliverable is a decision (the ADR). Building bronze now would also mean a
**dead** module (nothing calls it until Phase 19's re-run) — it cannot even be integration-
tested without the re-run it depends on. The gold verdicts are the higher-value, near-zero-cost
half of the legibility goal and they make the schema _complete for the re-run_; bronze is
future-proofing whose natural home is the re-run itself. ADR-0010 records the full bronze
design so Phase 19 implements against a ratified contract, not a fresh decision.

## Problem

After Phase 17, a failed Phoenix trace shows the **question**, the **retrieved-doc content**
(Phase 16), and the **generated answer** — but two legibility fields the sprint goal names are
still un-persisted, so they can never reach a span:

- **Judge verdict reasoning** (`per_fact` / `per_citation`). `JudgeVerdict` carries these lists
  in memory at runner time (`schema.py:79-100`; bound at `runner.py:187` as `verdict`), but
  `EvalRecord` **deliberately excludes them** — its own docstring says so (`records.py:75-77`),
  per ADR-0007 (`records.py` / ADR-0007 §1: "explicitly exclude the raw verdict checklists …
  Only python-derived aggregates persisted"). Only the three derived floats survive
  (`fact_recall` / `fact_precision` / `faithfulness_ratio`, `records.py:89-91`).
- **Generation input prompt** (the assembled system+user messages the generator saw). Built
  inside `generate_with_stats` (`generation/openai_generator.py` and its anthropic / gemini
  mirrors), used for the API call, then discarded with the raw response object — never stored.

This is the **decision/data phase**: decide _what to persist and where_, make the high-value
half **persistable in gold**, and write **ADR-0010** (a _scoped_ amendment to ADR-0007). The
ADR-0007 exclusion was a real, deliberate decision (clone footprint); reversing it wholesale
(full prompts in gold) would re-add the exact bloat it excluded. The resolution is to separate
the two missing fields by footprint — small discrete verdicts to gold, bulky prompt + raw
payload to gitignored bronze — and amend ADR-0007 only for the small half. **No hydration, no
re-run** here (Phase 19 owns both; the verdicts on old `results/*.jsonl` will be absent →
defaulted `None` until that re-run populates them).

The decisive facts (all confirmed in source this session):

- **The verdict lists already exist at the build site.** `judge.judge_with_stats(...)` returns
  `(verdict, judge_stats)` (`runner.py:187`); `verdict.per_fact` / `verdict.per_citation` are
  live `list[FactVerdict]` / `list[CitationVerdict]` right where `EvalRecord` is constructed
  (`runner.py:227-246`). Populating the new fields is a two-line addition with **zero** extra
  API cost.
- **The models to reuse are closed and already imported in the eval layer.** `FactVerdict`
  (`fact: str`, `verdict: Literal["present","absent","contradicted"]`) and `CitationVerdict`
  (`doc_id: str`, `verdict: Literal["supported","unsupported"]`), both `extra="forbid"`
  (`schema.py:24-57`). No new model is needed.
- **Backward-compat is the established pattern.** `EvalRecord` already carries optional +
  defaulted fields added after the fact: `k: int = 10` (`records.py:83`), `failure_mode:
str | None = None` (`records.py:95`), `retrieval_ranked_ids: list[...] = Field(default_factory=
list)` (`records.py:92`). The two new fields follow it verbatim → old JSONL keep loading
  (Pydantic supplies the default for absent keys).
- **Seven readers consume the JSONL** and must be unaffected: `dashboard/app.py`,
  `dashboard/data.py`, `eval/report.py`, `eval/classify_cli.py`, `eval/inspect_cli.py`,
  `eval/triage.py`, `observability/exporter.py`. Pydantic ignore-or-default of absent fields
  is what protects them — but an _added_ field can break a reader only if that reader
  round-trips and asserts an exact key set, or re-serializes to a fixed schema. The backward-
  compat AC names them explicitly.
- **`.gitignore` does NOT already cover the bronze path.** It lists `data/raw/` (line 57),
  `data/processed/` (line 58), `results/*` (line 61) — but `data/raw_eval/` ≠ `data/raw/`, so
  ADR-0010 must specify an explicit `data/raw_eval/` entry (added when Phase 19 builds the
  writer; this phase records the requirement in the ADR).
- **The runner is concurrent + crash-safe.** `run_evaluation` uses a `ThreadPoolExecutor`
  (`runner.py:255-261`), a `retrieve_lock` (BGE-M3 not thread-safe), a `cost_lock`, and a
  `write_lock` guarding per-record `f.write(...) + f.flush()` (`runner.py:249-252`), output
  opened in `w` mode at `{output_dir}/{run_id}.jsonl`. The gold change rides this untouched
  (the new fields serialize inside the same `record.model_dump_json()`). Any _future_ bronze
  writer (Phase 19) must be thread-safe and honour the same per-record-flush model —
  ADR-0010 records that constraint.

## Users / Stakeholders

- **Maintainer (Mauricio) running the Phase 19 re-run** — the direct beneficiary. After this
  phase, the schema _can hold_ the judge verdicts, so the Phase 19 sweep populates them with no
  further schema work and no second decision. Needs the change to cost zero extra API calls
  (it does — `verdict` is already in memory) and to not perturb the concurrent / crash-safe
  write path.
- **Maintainer debugging in Phoenix (Phase 19 onward)** — once Phase 19 hydrates the gold
  verdicts onto the judge span, a failed trace reads question → evidence → answer → **judge
  verdict reasoning** inline. This phase is the prerequisite that makes that data exist.
- **The 7 JSONL readers (backward-compat constraint)** — `dashboard/{app,data}.py`,
  `eval/{report,classify_cli,inspect_cli,triage}.py`, `observability/exporter.py`. They must
  load both pre-change `results/*.jsonl` (no new keys) and post-change records (new keys
  present) without error or behavior change. The constraint to protect (NFR-2 / AC-3).
- **ADR-0007 (the amended decision)** — its clone-footprint rationale is honoured, not
  reversed: the small discrete verdicts join gold; the bulky prompt + raw payload are exiled to
  gitignored bronze. ADR-0010 must state the amendment is _scoped_ and quote the original
  exclusion it narrows.
- **ADR-0006 (cassette/replay)** — vcrpy records raw HTTP responses for the **offline test**
  path, keyed by request hash. Bronze is a **production-sweep** artifact keyed by
  `question_id`. ADR-0010 must resolve the overlap (reuse serialization vs. distinct artifact)
  so Phase 19 doesn't duplicate infra (Q5).
- **Phase 19 (downstream)** — owns the costly re-run + Phoenix hydration **and** the bronze
  writer's build+wiring. It depends on this phase landing the gold schema (so the re-run
  populates it) and on ADR-0010 specifying the bronze contract (so it builds, not re-decides).
- **`/update-kb rag-eval` (`eval-record-schema`)** — refreshes the KB to record the new fields
  **after** ADR-0010 lands (Sprint-Wide Knowledge Plan, SPRINT.md) — deferred by design, not a
  gap.

## Requirements

### Functional

- **FR-1 Gold schema — add the two verdict fields, optional + defaulted.** `EvalRecord`
  (`eval/records.py`) gains `per_fact: list[FactVerdict] | None = None` and `per_citation:
list[CitationVerdict] | None = None`, importing the existing models from `eval/schema.py`.
  Both default `None` (the established backward-compat pattern, like `failure_mode`). **No new
  model is created**; the closed `FactVerdict` / `CitationVerdict` are reused verbatim. The
  `EvalRecord` docstring is updated to reflect that the _verdict lists are now persisted in
  gold_ (the bulky prompt / raw payload remain excluded → bronze), so it no longer contradicts
  ADR-0010.
- **FR-2 Runner populates the new fields from the in-memory verdict.** In `run_evaluation`'s
  `EvalRecord` construction (`runner.py:227-246`), `per_fact=verdict.per_fact` and
  `per_citation=verdict.per_citation` are added — `verdict` is already bound from the
  `judge_with_stats` call (`runner.py:187`). **Zero extra API calls.** On the retrieval-
  abstain path (`runner.py:171-181`) the judge still runs (`runner.py:187` is outside the
  abstain branch), so `verdict` is always bound; if a future path could leave them empty, the
  fields default to `None`/empty-list safely.
- **FR-3 Backward-compat: old JSONL loads; the 7 readers are unaffected.** A pre-change
  `results/*.jsonl` line (no `per_fact` / `per_citation` keys) parses into `EvalRecord` with
  both fields defaulting to `None`. None of the 7 readers (`dashboard/app.py`,
  `dashboard/data.py`, `eval/report.py`, `eval/classify_cli.py`, `eval/inspect_cli.py`,
  `eval/triage.py`, `observability/exporter.py`) raise, change output, or assume the fields'
  presence. A post-change record round-trips (`model_dump_json` → `model_validate_json`)
  losslessly with the new fields populated.
- **FR-4 Write ADR-0010 (the phase deliverable).** `docs/adr/0010-*.md` records: (1) the
  **scoped amendment** to ADR-0007 — small discrete verdicts to gold, bulky prompt + raw
  payload to gitignored bronze, quoting the ADR-0007 exclusion it narrows; (2) the **bronze
  design** (key scheme, idempotency, thread-safety, gitignored path) — _designed here, built in
  Phase 19_; (3) **footprint numbers** (~25–30 MB raw / ~5–8 MB gz for ~1500 records × 2 calls;
  the gold verdict-list growth is small — discrete label enums, not prose); (4) the **privacy
  note** (no secrets / API keys in payloads — request params are model + messages, auth is in
  headers, never serialized); (5) the **cassette/ADR-0006 overlap** resolution (Q5); (6) the
  **B2-gold-only fallback** (verdicts in gold, no bronze ever) if the Phase 19 bronze writer is
  over budget. ADR-0010's status is `accepted`; ADR-0007 gains a Consequences pointer to it
  (one-line, like its existing ADR-0008 pointer).
- **FR-5 Bronze is DESIGNED, not built, in this phase.** ADR-0010 fully specifies the bronze
  writer (path `data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json`; one JSON per
  call; overwrite-by-key idempotency; thread-safe + per-record flush matching the runner; opt-
  in flag default-off; gitignored). **No `eval/bronze.py` module, no runner wiring, no
  `.gitignore` edit is shipped this phase** — they land in Phase 19 alongside the re-run that
  fills them. (Scope call above; Q3 resolved.)
- **FR-6 `.gitignore` requirement recorded (not yet applied).** ADR-0010 states that
  `data/raw_eval/` is **not** covered by the existing `data/raw/` (line 57) / `results/*`
  (line 61) entries and must get an explicit `data/raw_eval/` line **when Phase 19 builds the
  writer**. This phase records the requirement; it does not edit `.gitignore` (nothing writes
  bronze yet).
- **FR-7 Generation input prompt — bronze-only, never gold (decision recorded).** ADR-0010
  records that the generation input prompt (embedding k=10 context chunks) is **excluded from
  gold** permanently (it is the bloat ADR-0007 feared) and captured **only** in bronze, if at
  all. Phase 19's bronze writer captures it; if bronze is descoped (B2 fallback), the prompt is
  simply not persisted this sprint (a later phase may add it). Phase 17 already shipped the
  generation-span `output.value` (the answer); the _input_ prompt is the deferred half. (Q2
  resolved.)

### Non-functional

- **NFR-1 Zero extra API cost / zero re-run / zero hydration.** The gold change adds no LLM
  call, no retrieval run, no sweep, and no Phoenix write — it only persists data already in
  memory at `runner.py:227-246`. The sprint no-re-runs guard holds; the costly sweep is
  quarantined to Phase 19.
- **NFR-2 Backward-compatibility (sprint risk control).** New fields are optional + defaulted
  (`| None = None`), so every prior `results/*.jsonl` and every one of the 7 readers keeps
  working with no migration. This mirrors the `k` / `failure_mode` / `retrieval_ranked_ids`
  precedent exactly (`records.py:83,92,95`). No reader is edited this phase.
- **NFR-3 Concurrency + crash-safety preserved.** The gold change rides inside the existing
  `record.model_dump_json()` under `write_lock` + `f.flush()` (`runner.py:249-252`) — the
  ThreadPoolExecutor / `retrieve_lock` / `cost_lock` / per-record-flush model
  (`runner.py:163-261`) is untouched. (Any bronze writer's thread-safety is a _Phase 19_
  obligation recorded in ADR-0010, not exercised here.)
- **NFR-4 Privacy — no secrets in any persisted payload.** Recorded in ADR-0010: bronze
  request payloads serialize model id + messages + sampling params only; API keys live in
  request _headers_ / the client object, never in the body, so they cannot land in a bronze
  file. The gold verdicts are label enums + short strings (fact text, doc_id) — no secrets.
- **NFR-5 Footprint discipline (the ADR-0007 concern, honoured).** The gold growth is bounded:
  `per_fact` / `per_citation` are lists of `{str, Literal}` pairs — discrete labels, typically
  a few-to-low-dozens per record, not prose. ADR-0010 states the per-record gold delta is small
  (order of the existing `sources` / `retrieval_ranked_ids` lists), distinct from the prompt
  bloat that stays in bronze. This is the _scoped_-amendment justification.
- **NFR-6 Determinism / lossless round-trip.** For a given `verdict`, the populated `EvalRecord`
  serializes deterministically and `model_validate_json(model_dump_json(rec)) == rec` (the
  closed `extra="forbid"` verdict models guarantee no field drift).
- **NFR-7 Test mirror + house structure.** Tests land in `tests/eval/test_records.py`
  (mirroring `src/.../eval/records.py`; package dir has `__init__.py`); the runner-population
  assertion lands in `tests/eval/test_runner.py`. No flat `tests/test_*.py`. `make lint test`
  is the gate. Eval-path tests touching the LLM use the cassette/replay pattern (ADR-0006), not
  a mocked API — but the gold-schema + population tests need **no** LLM at all (they construct a
  `JudgeVerdict` / `EvalRecord` in memory).

## Acceptance Criteria

Each AC is checkable offline — no LLM call, no HF, no Phoenix, no network. Schema /
round-trip / population ACs construct `FactVerdict` / `CitationVerdict` / `JudgeVerdict` /
`EvalRecord` in memory; the runner-population AC asserts on a constructed `EvalRecord` from a
stubbed verdict; the ADR ACs are document checks; backward-compat ACs use a fixture JSONL line.

- **AC-1 New fields exist, optional, defaulted, reuse the existing models.** `EvalRecord` has
  fields `per_fact` and `per_citation` with annotation `list[FactVerdict] | None` /
  `list[CitationVerdict] | None` and default `None` (assert via `EvalRecord.model_fields` /
  `inspect`). `FactVerdict` / `CitationVerdict` are imported from `eval.schema` (no new model
  defined in `records.py`).
- **AC-2 A populated record round-trips losslessly.** Given an `EvalRecord` built with
  `per_fact=[FactVerdict(fact="X", verdict="present")]` and
  `per_citation=[CitationVerdict(doc_id="d1", verdict="supported")]`,
  `EvalRecord.model_validate_json(rec.model_dump_json())` equals `rec` (both lists, all
  pre-existing fields). Serialized JSON contains the `per_fact` / `per_citation` keys with the
  label values.
- **AC-3 Backward-compat — pre-change JSONL loads; readers unaffected.** A fixture JSONL line
  with **no** `per_fact` / `per_citation` keys (e.g. a copy of a real pre-change record)
  parses via `EvalRecord.model_validate_json(line)` with both fields `== None` and **no**
  validation error. A representative reader path (`eval/report.py` or `dashboard/data.py`
  loader) consumes the pre-change line and produces its prior output unchanged (assert no raise
  - behavior parity on the loaded record). The other readers are covered by the optional-
    default contract; this AC names the load + at least one reader-path assertion.
- **AC-4 Runner populates the fields from the in-memory verdict (zero extra call).** With a
  stubbed judge returning a `JudgeVerdict` whose `per_fact` / `per_citation` are known, the
  `EvalRecord` written by `run_evaluation` (or the record-build code path under test) carries
  `record.per_fact == verdict.per_fact` and `record.per_citation == verdict.per_citation`. The
  test asserts **no additional** generator/judge call beyond the existing two (population is a
  pure in-memory copy). Eval-path LLM interaction, if exercised, uses the cassette/replay
  pattern (ADR-0006), never a mocked API.
- **AC-5 ADR-0010 exists and is complete.** `docs/adr/0010-*.md` exists with `Status:
accepted`, and its body contains: (a) the scoped amendment to ADR-0007 (quoting the verdict-
  checklist exclusion it narrows), (b) the bronze key scheme
  `data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json` + overwrite-by-key
  idempotency + designed-here-built-in-Phase-19 statement, (c) footprint numbers (gold delta
  small; bronze ~25–30 MB raw / ~5–8 MB gz), (d) the privacy / no-secrets note, (e) the
  cassette/ADR-0006 overlap resolution, (f) the B2-gold-only fallback. (Checked by section /
  keyword assertions on the ADR file.)
- **AC-6 ADR-0007 points to ADR-0010.** ADR-0007's Consequences gains a one-line pointer to
  ADR-0010 as its amendment (mirroring its existing ADR-0008 pointer at line 102). The
  `EvalRecord` docstring (`records.py:75-77`) no longer claims `per_fact` / `per_citation` are
  excluded from the record — it states the verdict lists are now persisted (prompt / raw
  payload remain out → bronze), so code and ADR no longer drift.
- **AC-7 No bronze code, no `.gitignore` edit, no re-run, no hydration this phase.** The diff
  for Phase 18 contains **no** new `eval/bronze.py` (or equivalent) module, **no** runner
  bronze-writing code, **no** `.gitignore` change, **no** eval-sweep invocation, and **no**
  `observability/exporter.py` / span change. (Asserted by diff review / file-absence check at
  review; the bronze design lives only in ADR-0010 prose.) This guards the scope decision and
  the sprint no-re-runs / no-hydration guards.

## Resolved Open Questions

`AskUserQuestion` is unavailable to this subagent, so the BRAINSTORM's 6 open questions are
resolved to their SPRINT / planning-note-aligned defaults below and flagged as **unconfirmed
assumptions** for the orchestrator to ratify before `/design`. RQ-1–RQ-6 map 1:1 to BRAINSTORM
Open Questions 1–6. None changes the MUST surface; the highest-leverage one to confirm is RQ-3
(bronze built-vs-designed), which sets the phase's size.

- **RQ-1 Gold field shape — full verdict lists, not a compact summary (BRAINSTORM Q1).**
  **Resolved: full `per_fact` / `per_citation` lists**, reusing the existing closed
  `FactVerdict` / `CitationVerdict` models. Rationale: the models already exist and are small
  (label enums); a compact summary needs a _new_ shape (a new model + a derivation), which is
  more surface for a tighter result and discards the per-item structure Phase 19 wants on the
  judge span. The lists are the higher-value half and are genuinely small. Encoded as FR-1 +
  AC-1/AC-2. _Unconfirmed assumption — low risk; matches BRAINSTORM lean._
- **RQ-2 Generation input prompt — bronze-only, never gold; deferred to Phase 19 capture
  (BRAINSTORM Q2).** **Resolved: prompt is gold-excluded permanently and captured only in
  bronze** (built Phase 19). If bronze is descoped (B2 fallback), the prompt is simply not
  persisted this sprint — the answer (`output.value`, shipped Phase 17) + the gold verdicts are
  enough to "explain a failed trace" for the sprint goal; the generation _input_ is the
  nice-to-have. Encoded as FR-7 + AC-5(f). _Unconfirmed assumption — low risk; matches BRAINSTORM
  hybrid + the planning note's bulk argument._
- **RQ-3 Bronze DESIGNED here, BUILT in Phase 19 (BRAINSTORM Q3) — the scope call.**
  **Resolved: design bronze fully in ADR-0010; build + wire it in Phase 19's re-run.** The
  planning note's own cost argument is "capture is cheap _during_ the re-run" — so the writer's
  natural home is the re-run. Building it here yields a dead, un-integration-testable module
  (nothing writes bronze until the sweep) — pure scope creep in a decision phase. Encoded as
  FR-5/FR-6 + AC-7. **✅ Ratified by the user (2026-06-02): design
  bronze in ADR-0010, build + wire it in Phase 19.** This is the settled scope contract for
  `/design` — the gold schema change + ADR are the phase; no bronze writer, no `.gitignore` edit.
- **RQ-4 Bronze idempotency — overwrite-by-key (BRAINSTORM Q4).** **Resolved: overwrite-by-key**
  (same `{run_id}/{question_id}__{model}__{call}` path overwrites), matching the runner's
  `w`-mode JSONL semantics (output reopened fresh per `run_id`, `runner.py` output path).
  Recorded in ADR-0010 (FR-4); enforced when Phase 19 builds the writer. _Unconfirmed
  assumption — low risk; consistent with existing runner semantics._
- **RQ-5 Cassette/ADR-0006 overlap — distinct artifact, shared serialization shape (BRAINSTORM
  Q5).** **Resolved: bronze is a distinct production-sweep artifact** (keyed by `question_id`,
  written during real sweeps) from vcrpy cassettes (keyed by request hash, test-only fixtures);
  ADR-0010 notes the _response-serialization_ shape may be shared/reused but the artifacts and
  lifecycles are separate (no coupling of test fixtures to production output). Encoded as FR-4 +
  AC-5(e). _Unconfirmed assumption — low risk; matches BRAINSTORM rationale 5._
- **RQ-6 Fresh-clone legibility — verdicts travel with the clone (gold); generation prompt is
  author-machine-only (bronze) (BRAINSTORM Q6).** **Resolved: accepted.** The high-value
  verdicts are committed to gold → a fresh clone's traces (after Phase 19 hydration) show the
  judge reasoning; the bulky generation prompt lives only in gitignored bronze on the author's
  machine. This keeps the sprint's "a failed trace explains itself" win cloneable for the
  verdict half while honouring ADR-0007's footprint concern for the prompt. Recorded in
  ADR-0010. _Unconfirmed assumption — low risk; the recommended yes._

## Infrastructure Readiness

| Dependency                                                                                                          | Type     | KB domain                                | Specialist   | Status                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `eval/records.py::EvalRecord` (add `per_fact` / `per_citation`, optional + defaulted)                               | module   | rag-eval (`eval-record-schema`)          | —            | Ready — backward-compat pattern confirmed (`k`/`failure_mode`/`retrieval_ranked_ids` at `records.py:83,92,95`); docstring (`records.py:75-77`) needs the amend |
| `eval/schema.py::FactVerdict` / `CitationVerdict` (reused gold models)                                              | module   | rag-eval (`eval-record-schema`)          | —            | Ready — closed `extra="forbid"` models exist (`schema.py:24-57`); imported into `records.py`, no new model                                                     |
| `eval/runner.py::run_evaluation` (populate from in-memory `verdict`)                                                | module   | rag-eval (`stats-capture-seam`)          | —            | Ready — `verdict` bound at `runner.py:187`, `EvalRecord` built at `runner.py:227-246`; concurrency/flush model (`runner.py:163-261`) untouched                 |
| 7 JSONL readers (`dashboard/{app,data}`, `eval/{report,classify_cli,inspect_cli,triage}`, `observability/exporter`) | modules  | rag-eval / observability                 | —            | Ready — backward-compat via Pydantic optional-default; **none edited** this phase (FR-3/AC-3 name them)                                                        |
| `docs/adr/0010-*.md` (ADR-0010, amends ADR-0007) + ADR-0007 pointer                                                 | doc      | rag-eval (`eval-record-schema`)          | —            | Ready — ADR-0007 read this session; amendment-pointer precedent is ADR-0007→ADR-0008 (line 102)                                                                |
| ADR-0006 (cassette/replay) overlap call                                                                             | doc      | rag-eval (`cassette-replay-eval`)        | —            | Ready — overlap resolvable in ADR-0010 prose (RQ-5); no infra needed now                                                                                       |
| Bronze writer + `data/raw_eval/` + `.gitignore` entry                                                               | module   | rag-eval (`stats-capture-seam`)          | —            | **Designed-only this phase** (FR-5/FR-6) — built + gitignored in Phase 19; `.gitignore` confirmed not to cover `data/raw_eval/` (lists `data/raw/` line 57)    |
| `tests/eval/` (`test_records.py`, `test_runner.py`, `__init__.py`)                                                  | tests    | —                                        | —            | Ready — existing package; schema/round-trip/backward-compat/population tests mirror here (no flat test file); LLM-touching paths use cassette (ADR-0006)       |
| Phoenix span hydration of the verdicts                                                                              | deferred | observability (`span-attribute-mapping`) | —            | **Phase 19 concern** — not this phase (BRAINSTORM coverage table; SPRINT.md phase 19)                                                                          |
| `/update-kb rag-eval` (refresh `eval-record-schema` for the new fields)                                             | KB       | rag-eval                                 | kb-architect | **Correctly deferred (not a Phase-18 gap)** — Sprint-Wide Knowledge Plan lands it **after** ADR-0010 (SPRINT.md)                                               |

**No new KB, agent, command, or `--deep-research` needed for this phase.** Every dependency maps
to an existing module + existing `rag-eval` KB domain (`eval-record-schema`, `stats-capture-seam`,
`cassette-replay-eval`); the BRAINSTORM coverage table confirms "Sufficient" across the board and
"no `--deep-research` needed." The post-ADR `/update-kb rag-eval` refresh is **deliberately
deferred** per the Sprint-Wide Knowledge Plan — its absence today is expected, not a readiness
gap. Observability KB / span hydration is a Phase-19 concern.

## Out of Scope (Won't — Phase 18)

- **Any eval re-run / retrieval run / classify / triage re-run** — the costly sweep is
  quarantined to Phase 19 (sprint no-re-runs guard).
- **Any Phoenix hydration** of the new verdict fields onto spans — Phase 19 (`exporter.py` /
  span attrs untouched this phase; FR/AC-7).
- **Building the bronze writer** (`eval/bronze.py` or equivalent) or wiring it into the runner —
  designed in ADR-0010, built + activated in Phase 19 (RQ-3; FR-5).
- **Editing `.gitignore`** (the `data/raw_eval/` line) — added when Phase 19 builds the writer
  that needs it (FR-6).
- **Persisting the generation input prompt into gold JSONL** — bulky (embeds k=10 chunks); the
  bloat ADR-0007 feared; bronze-only if captured at all (FR-7; RQ-2).
- **A bronze→derived consumer / replay pipeline that _reads_ bronze** — Phase 19 builds the
  consumer; this phase neither writes nor reads bronze (BRAINSTORM Won't).
- **Parquet / DB storage for bronze** — JSON-per-call is sufficient at ~1500-record scale
  (BRAINSTORM Won't; revisit only if the dataset grows).
- **A compact rationale-summary model** instead of the full verdict lists — full lists reuse the
  existing models and are small (RQ-1).
- **Editing any of the 7 readers** — backward-compat is achieved by the optional-default
  contract alone; no reader change is needed or made (FR-3).

## Clarity Score

| Dimension        | Score          | Note                                                                                                                                                                                                                                             |
| ---------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Problem          | 3              | Root cause + evidence: `per_fact`/`per_citation` excluded by ADR-0007 (`records.py:75-77`) yet live at the build site (`verdict` at `runner.py:187`, record at `runner.py:227-246`); prompt discarded in generators; `.gitignore` gap confirmed. |
| Users            | 3              | Named roles with workflow impact: Phase-19 re-runner (direct), Phoenix debugger (downstream), the 7 readers (constraint), ADR-0007 / ADR-0006, Phase 19, deferred `/update-kb`.                                                                  |
| Success          | 3              | 7 falsifiable, offline ACs: fields-optional-defaulted, lossless round-trip, backward-compat load + reader-path, runner population (zero extra call), ADR-0010 complete, ADR-0007 pointer + docstring de-drift, no-bronze/no-re-run guard.        |
| Scope            | 3              | MoSCoW inherited from BRAINSTORM with an explicit Won't list; the crisp build-vs-design scope call is made and justified; the 6 open questions all resolved (defaults flagged for orchestrator ratify).                                          |
| Constraints      | 3              | All named: backward-compat (optional+default), zero extra cost / no re-run / no hydration, concurrency + crash-safe flush preserved, no-secrets privacy, footprint discipline (scoped amendment), determinism, test mirror + cassette.           |
| **Total: 15/15** | **PASS (≥12)** | Gate passed. RQ-1–RQ-6 resolved to BRAINSTORM/SPRINT-aligned defaults and flagged as **unconfirmed assumptions** (RQ-3, the build-vs-design scope call, is the one to ratify before `/design`); no `AskUserQuestion` available as subagent.      |

## Next Step

→ `/design sprint-6/phase-18-evalrecord-reasoning`
