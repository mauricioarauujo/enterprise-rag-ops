# DESIGN: sprint-6/phase-18-evalrecord-reasoning — Persist Judge Reasoning + Generation Input (ADR-0010)

**Sprint/Phase:** sprint-6/phase-18-evalrecord-reasoning | **Date:** 2026-06-02

## Architecture

Phase 18 makes the judge's verdict reasoning **persistable in gold** and ratifies the
bronze archive **on paper** (ADR-0010) — without building it. The design is a
**footprint split** of the two un-persisted legibility fields ADR-0007 dropped:

- **Verdict lists → gold (built now).** `per_fact` / `per_citation` are _discrete labels_
  (`present`/`absent`/`contradicted`, `supported`/`unsupported`) keyed by short strings —
  small, high-value, the actual "reasoning" a reviewer reads on a failed trace. They join
  `EvalRecord` as optional, defaulted fields, **reusing the closed `eval/schema.py`
  `FactVerdict` / `CitationVerdict` models verbatim** (no new model). This is the exact
  backward-compat pattern already used for `k` (`records.py:83`), `retrieval_ranked_ids`
  (`records.py:92`), and `failure_mode` (`records.py:95`).
- **Generation prompt + raw payload → bronze (designed only).** The assembled prompt
  embeds the k=10 context chunks — the real bloat ADR-0007 feared. It and the raw API
  response go to a gitignored bronze archive
  (`data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json`), **specified in
  ADR-0010 but built + wired + gitignored in Phase 19** (the re-run is the cheap moment to
  capture). This phase writes no bronze code, no `.gitignore` edit.

### Data flow (gold half — the only code path that changes)

```
runner.process_one(q)
        │
        ▼
verdict, judge_stats = judge.judge_with_stats(...)   # runner.py:187 — ALWAYS runs
        │   verdict.per_fact / verdict.per_citation now live in memory
        ▼
record = EvalRecord(                                  # runner.py:227-246
        ...,
        per_fact=verdict.per_fact,        # NEW — pure in-memory copy, zero API cost
        per_citation=verdict.per_citation # NEW
)
        ▼
with write_lock: f.write(record.model_dump_json() + "\n"); f.flush()   # runner.py:249-252 — unchanged
```

**Why the judge always runs (FR-2 confirmed in source).** The retrieval-abstain branch
(`runner.py:171-181`) only short-circuits _generation_ — it sets an `ABSTAIN_ANSWER` and a
zero-token `gen_stats`, then falls through to the **unconditional** `judge_with_stats` call
at `runner.py:187`. So `verdict` is always bound at the `EvalRecord` build site
(`runner.py:227-246`); the new kwargs never reference an unbound name. On an abstain the
verdict lists are simply short/empty (the judge scores zero facts/citations) — `None` is
never written by the runner, but the field default `None` covers any future path that skips
the judge.

### Why no reader changes (FR-3 / AC-3 / Out-of-Scope)

Backward-compat is achieved by the **optional-default contract alone**. The seven JSONL
readers (`dashboard/{app,data}.py`, `eval/{report,classify_cli,inspect_cli,triage}.py`,
`observability/exporter.py`) call `EvalRecord.model_validate*`; Pydantic supplies the
default for absent keys, so a pre-change line loads with both fields `None`, and a
post-change line carries them — no reader reads or asserts the new keys. **No reader is
edited this phase.**

### Import-cycle safety (FR-1)

`records.py` does **not** currently import from `eval/schema.py`. The new line
`from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict` is **acyclic**:
`schema.py` imports only `pydantic` + `typing` (verified — no import of `records.py`), so
`records.py → schema.py` introduces no cycle. (`stub_judge.py` already imports both modules
the same way, confirming the direction is safe.)

### ADR-0010 (the phase deliverable)

A _scoped_ amendment to ADR-0007 — not a reversal. It narrows ADR-0007 §1's exclusion
("explicitly **exclude the raw verdict checklists** … Only python-derived aggregate metrics
are persisted") to admit the small discrete verdict lists into gold while keeping the bulky
prompt + raw payload out (→ bronze). It carries the full bronze contract so Phase 19 builds
against a ratified spec. ADR-0007 gains a one-line Consequences pointer to ADR-0010,
mirroring its existing ADR-0008 pointer (`0007:102`).

## File Manifest

Prescriptive — an executor (Antigravity / Gemini) needs no extra context. All `direct`
(no specialist owns `eval/`; the Infrastructure Readiness table lists `—` throughout).

| File                                                   | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Owner  | Phase order |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------- |
| `src/enterprise_rag_ops/eval/records.py`               | (1) Add import `from enterprise_rag_ops.eval.schema import CitationVerdict, FactVerdict` (top, with the other imports). (2) In `EvalRecord`, after `failure_mode: str \| None = None` (`records.py:95`), add `per_fact: list[FactVerdict] \| None = None` and `per_citation: list[CitationVerdict] \| None = None`. (3) Amend the class docstring (`records.py:75-77`): it currently says it _excludes_ `per_fact`/`per_citation` — rewrite to state the **verdict lists are now persisted in gold** (per ADR-0010), and only the bulky generation prompt / raw payload remain excluded (→ bronze). No other field touched.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | direct | 1           |
| `src/enterprise_rag_ops/eval/runner.py`                | In the `EvalRecord(...)` constructor (`runner.py:227-246`), add two kwargs `per_fact=verdict.per_fact,` and `per_citation=verdict.per_citation,` (placed near `fact_recall`/`fact_precision`/`faithfulness_ratio`, which already read from the same `verdict`). `verdict` is already bound at `runner.py:187`. **No** new import, **no** signature change, **no** change to the concurrency / `write_lock` / `f.flush` model (`runner.py:249-252`). Zero extra LLM call.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | direct | 2           |
| `docs/adr/0010-persist-judge-reasoning-bronze-gold.md` | **New.** ADR-0010, `Status: accepted`, `Date: 2026-06-02`. Headings match the repo ADR format (Status / Date / Context / Decision / Consequences — see ADR-0008/0009). Body must satisfy AC-5 (a–f): (a) scoped amendment quoting the ADR-0007 §1 verdict-checklist exclusion it narrows; (b) bronze key scheme `data/raw_eval/{run_id}/{question_id}__{model}__{gen\|judge}.json`, overwrite-by-key idempotency, opt-in flag default-off, thread-safe + per-record-flush matching the runner, "designed here, built + wired + gitignored in Phase 19" statement; (c) footprint numbers — gold delta small/discrete (order of `sources`/`retrieval_ranked_ids`), bronze ~25–30 MB raw / ~5–8 MB gz for ~1500 records × 2 calls; (d) privacy / no-secrets note (model id + messages + sampling params only; auth in headers / client object, never serialized in the body); (e) cassette/ADR-0006 overlap — bronze is a distinct production artifact keyed by `question_id`, vcrpy cassettes are test fixtures keyed by request hash; the response-serialization _shape_ may be shared, lifecycles are not; (f) B2-gold-only fallback (verdicts in gold, no bronze ever, generation prompt simply not persisted this sprint). Also record FR-6: `data/raw_eval/` is **not** covered by the existing `data/raw/` (`.gitignore:57`) / `results/*` (`.gitignore:61`) entries → an explicit `data/raw_eval/` line is added **when Phase 19 builds the writer**. | direct | 3           |
| `docs/adr/0007-eval-record-schema.md`                  | Append one line to the **Consequences** list (`0007:96-102`), mirroring the existing ADR-0008 pointer at line 102: `- **Verdict-list persistence (scoped amendment):** See [ADR 0010](0010-persist-judge-reasoning-bronze-gold.md), which narrows the verdict-checklist exclusion above to admit the small discrete \`per*fact\` / \`per_citation\` lists into gold (bulky prompt + raw payload stay out → bronze).` No other change to ADR-0007 (the §1 exclusion text stays — ADR-0010 \_narrows* it, the pointer records that).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | direct | 3           |
| `tests/eval/test_records.py`                           | **Extend** (exists). (1) **Invert the stale exclusion assertions** in `test_eval_record_roundtrip_and_exclusions` (`test_records.py:66-72`): they currently assert `per_fact`/`per_citation` are **absent** from `model_fields` / `model_json_schema` — that now contradicts the schema and **will fail**. Replace with presence assertions (or split into a new test and drop the exclusion block). (2) Add AC-1 test: `EvalRecord.model_fields["per_fact"]` / `["per_citation"]` exist, are optional with default `None`, annotated `list[FactVerdict] \| None` / `list[CitationVerdict] \| None`; assert `FactVerdict`/`CitationVerdict` are imported from `eval.schema` (no new model defined in `records.py`). (3) Add AC-2 lossless round-trip: build `EvalRecord` with `per_fact=[FactVerdict(fact="X", verdict="present")]`, `per_citation=[CitationVerdict(doc_id="d1", verdict="supported")]`; assert `EvalRecord.model_validate_json(rec.model_dump_json()) == rec` and the JSON contains the `per_fact`/`per_citation` keys + label values. (4) Add AC-3 backward-compat: a JSONL line dict with **no** `per_fact`/`per_citation` keys (reuse the existing `record_dict` shape) parses via `model_validate_json` with both `== None`, no `ValidationError`. All in-memory, no LLM, no network.                                                                                                                                                 | direct | 4           |
| `tests/eval/test_runner.py`                            | **Extend** (exists). Add AC-4 population test reusing the existing `run_config` fixture, `MockRetriever`, `StubGenerator`, `StubJudge` harness (see `test_runner_loads_retriever_once`, `test_records.py` patterns): run `run_evaluation` with one model + one question whose `answer_facts` are known; read the written JSONL record and assert `record["per_fact"]` carries the verdict labels for those facts (StubJudge marks each `present`) and `record["per_citation"]` matches the answer's sources. Assert **no extra** generator/judge call beyond the existing two (population is a pure in-memory copy — e.g. a call-counter on the stub, or rely on the StubJudge/StubGenerator which make no network call). Offline; StubJudge/StubGenerator only (no live LLM → cassette/replay not needed; if any test ever touches the live path it uses ADR-0006 cassette, never a mock).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | direct | 4           |

No `eval/bronze.py`, no `.gitignore` edit, no `observability/exporter.py` change, no
reader edit, no eval-sweep invocation appears in this manifest — by AC-7 / Out-of-Scope.

## Implementation Phases

Standard order (schema → core → docs/ADR → tests → gate); collapsed here because there is
no dataset/config change and the only `src/` touches are the schema field add and the
runner population.

1. **Schema field add + docstring** — `records.py`. Add the `schema` import, the two
   optional-defaulted fields after `failure_mode`, and amend the docstring. _No dependency._
   Satisfies FR-1, NFR-2, NFR-5, NFR-6; checkable by AC-1, AC-2, AC-3.
2. **Runner population** — `runner.py`. Add the two kwargs at the build site. **Depends on
   step 1** (the fields must exist or `EvalRecord(...)` raises). Satisfies FR-2, NFR-1,
   NFR-3; checkable by AC-4.
3. **ADR-0010 + ADR-0007 pointer** — write `docs/adr/0010-*.md`; append the one-line
   pointer to `docs/adr/0007-eval-record-schema.md` Consequences. Independent of steps 1–2
   (doc-only) but conceptually records the decision they implement. Satisfies FR-4, FR-5,
   FR-6, FR-7, NFR-4, NFR-5; checkable by AC-5, AC-6.
4. **Tests** — extend `tests/eval/test_records.py` (invert the stale exclusion assertions
   first, then add AC-1/AC-2/AC-3) and `tests/eval/test_runner.py` (AC-4). **Depends on
   steps 1–2.** Satisfies FR-3, NFR-7.
5. **Quality pass** — `make lint test` (the real gate, also CI). Targeted first:
   `uv run pytest tests/eval/test_records.py tests/eval/test_runner.py -k "per_fact or per_citation or roundtrip or population or backward"`.

## Test Plan (AC → check)

| AC                                                                   | Check                                                                                                                                                                               | Where                                       |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **AC-1** Fields optional + defaulted + reuse models                  | `model_fields["per_fact"]`/`["per_citation"]` exist, default `None`, correct annotation; `FactVerdict`/`CitationVerdict` imported from `eval.schema`, no new model in `records.py`. | `tests/eval/test_records.py`                |
| **AC-2** Lossless round-trip                                         | `model_validate_json(model_dump_json(rec)) == rec` for a populated record; JSON contains the keys + label values.                                                                   | `tests/eval/test_records.py`                |
| **AC-3** Backward-compat load                                        | Pre-change JSONL line (no new keys) parses with both `== None`, no `ValidationError`. Optional-default contract covers all 7 readers (no reader edited).                            | `tests/eval/test_records.py`                |
| **AC-4** Runner populates, zero extra call                           | Record written by `run_evaluation` (StubJudge/StubGenerator) carries the verdict labels; assert no LLM call beyond the existing two.                                                | `tests/eval/test_runner.py`                 |
| **AC-5** ADR-0010 complete                                           | Keyword / section presence check on `docs/adr/0010-*.md`: `Status: accepted` + sub-parts (a)–(f). Doc review (not a unit test).                                                     | `docs/adr/0010-*.md` (review)               |
| **AC-6** ADR-0007 pointer + docstring de-drift                       | ADR-0007 Consequences has the ADR-0010 pointer; `EvalRecord` docstring no longer claims the verdict lists are excluded. Doc/source review.                                          | `docs/adr/0007-*.md`, `records.py` (review) |
| **AC-7** No bronze code / no `.gitignore` / no re-run / no hydration | Diff / file-absence check at review: no `eval/bronze.py`, no runner bronze write, no `.gitignore` change, no `observability/exporter.py` change, no sweep invoked.                  | git diff (review)                           |

## Infrastructure Gaps

Deep three-layer check — **clean**. Every dependency maps to an existing module and the
existing `rag-eval` KB domain; no new domain, concept, or specialist is needed.

| Gap Type           | Area | Detail                                                                                                                                                                                                                                                                                                                                                                                 | Recommendation                                  |
| ------------------ | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Missing domain     | —    | All tech areas (Pydantic schema evolution, the runner build site, JSONL backward-compat, the bronze/gold data-layering convention, ADR amendment) are covered by the existing `rag-eval` KB domain in `_index.yaml`.                                                                                                                                                                   | none                                            |
| Missing concept    | —    | `rag-eval` already carries `eval-record-schema` (the amended schema), `stats-capture-seam` (the runner build site / future bronze ride), and `cassette-replay-eval` (the ADR-0006 overlap call) — exactly the concepts this phase exercises. The new-field documentation is a _refresh_ deferred post-ADR per the Sprint-Wide Knowledge Plan, **not** a missing concept blocking impl. | `/update-kb rag-eval` — **deferred, not a gap** |
| Missing specialist | —    | `eval/` has no owning specialist (`—` across the Infrastructure Readiness table); prior eval phases shipped `direct`. No new agent warranted for a 2-line schema add + ADR.                                                                                                                                                                                                            | none                                            |

- **Domain existence:** ✅ `rag-eval` covers `EvalRecord`/`schema`/`runner`; the bronze
  path is a designed-only artifact under the same domain. No observability-domain work this
  phase (Phoenix hydration is Phase 19).
- **Concept coverage:** ✅ `eval-record-schema` covers the backward-compat optional-default
  pattern; `cassette-replay-eval` covers the ADR-0006 overlap resolution recorded in
  ADR-0010.
- **Agent alignment:** ✅ N/A — no specialist owns `eval/`; `kb-architect` owns the
  (deferred) post-ADR `/update-kb rag-eval` refresh, consistent with the Sprint-Wide
  Knowledge Plan.

## Consistency Check

**Verdict: ✅ CONSISTENT.** Non-trivial phase (2 source modules + 2 ADR docs + 2 test
files; DEFINE went through a ratified scope fork on RQ-3). Full six-pass cross-check of
DEFINE↔DESIGN against the constitution (AGENTS.md § Engineering Behavior + § Conventions +
§ Testing, ADR-0007, ADR-0006, the `rag-eval` KB). No CRITICAL/HIGH drift.

| ID  | Severity | Pass               | Location                           | Finding                                                                                                                                                                                                                                                                                                                                                                                                    | Suggested fix                                                                                                                                                                                                                 |
| --- | -------- | ------------------ | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | MEDIUM   | Inconsistency      | `tests/eval/test_records.py:66-72` | **Code-reality conflict the DEFINE does not call out.** `test_eval_record_roundtrip_and_exclusions` currently **asserts** `per_fact`/`per_citation` are _absent_ from `model_fields` and `model_json_schema`. FR-1 adds those exact fields → this existing test **will fail** after step 1 if left intact. DEFINE's AC-1/AC-2/AC-3 assume new/extended tests but don't name the stale assertion to invert. | Manifest step 4 makes inverting these assertions the **first** test edit. Flagged so the executor doesn't read the existing test as the spec.                                                                                 |
| C-2 | LOW      | Underspecification | AC-4 (`per_citation` assertion)    | StubJudge derives `per_citation` from `answer_with_sources.sources`; if the test's StubGenerator returns no sources, `per_citation` is `[]` (still a valid copy, but a weak assertion). `per_fact` (keyed on the question's `answer_facts`) is the reliable signal.                                                                                                                                        | AC-4 asserts on `per_fact` as the primary check; assert `per_citation == verdict.per_citation` for exactness. Either is offline; implementer ensures the stub answer carries ≥1 source if asserting non-empty `per_citation`. |
| C-3 | LOW      | Ambiguity          | ADR-0010 filename slug             | DEFINE writes `docs/adr/0010-*.md` (glob). DESIGN pins `0010-persist-judge-reasoning-bronze-gold.md`.                                                                                                                                                                                                                                                                                                      | Slug is the implementer's choice as long as it is `0010-<slug>.md` and AC-5's keyword checks pass; the pinned name matches the repo's descriptive-slug convention (cf. `0009-triage-to-issues.md`).                           |

- **Duplication:** none. FR-1 (gold fields) and FR-2 (runner population) are sequential,
  not overlapping; FR-5/FR-6/FR-7 are all _designed-only_ bronze concerns recorded solely
  in ADR-0010 (FR-4) — no double build.
- **Ambiguity:** only C-3 (filename slug, glob-permitted by DEFINE). No vague descriptors;
  RQ-1..RQ-6 all resolved, RQ-3 **ratified** by the user.
- **Underspecification:** only C-2 (a weak-vs-strong AC-4 assertion choice). Every FR maps
  to a concrete named site (`records.py:95` field block, `runner.py:227-246` kwargs,
  `0007:102` pointer); every code-bearing AC names its mechanism (`model_fields`,
  `model_dump_json`/`model_validate_json`, the StubJudge harness).
- **Constitution alignment:** ✅ Minimal scope — a 2-line schema add + 2-line runner copy +
  an ADR; the bronze writer is explicitly **not** built (no speculative/dead module —
  AGENTS.md § Engineering Behavior "no premature implementation"). No new
  `Protocol`/abstraction. The bronze contract is a _named, likely_ future change (Phase 19
  is scheduled), recorded in an ADR — the exact "seam justified by an ADR, not 'in case'"
  bar. No stranger-test / private-path leak (ADR-0010 is a public system-design doc).
  Conventions honoured: English; YYYY-MM-DD; tests mirror `src/` into `tests/eval/` with
  the existing `__init__.py` (no flat `tests/test_*.py`); cassette/replay applies only to
  live-LLM paths (none here — StubJudge/StubGenerator, no network).
- **Coverage:** ✅ all 7 FR + 7 NFR map to ≥1 manifest entry; all 7 AC map to a manifest
  test or a doc/diff review. Reverse check: every manifest entry references a confirmed
  component (`FactVerdict`/`CitationVerdict` at `schema.py:24-57`, `verdict` at
  `runner.py:187`, the build site at `runner.py:227-246`, the `0007:102` pointer precedent,
  the StubJudge/StubGenerator harness — all read this session). FR-5/FR-6/FR-7 (designed-
  only) map to ADR-0010 prose, not code, per the ratified scope.
- **Inconsistency:** only C-1 (the stale test assertion — a code-reality conflict, now the
  first manifest test edit). Terminology is identical across DEFINE/DESIGN (`per_fact`,
  `per_citation`, "gold", "bronze", "scoped amendment", "overwrite-by-key"); no directive
  conflicts with ADR-0007 (narrowed, not reversed) or ADR-0006 (distinct artifact).

## Risks & Trade-offs

- **Stale exclusion test (C-1) — the one real trap.** `test_records.py:66-72` asserts the
  _old_ behavior and **breaks** the moment FR-1 lands. The manifest makes inverting it the
  first test edit; if an executor adds new tests but leaves the old block, `make test`
  fails at step 5. This is a code-reality contradiction DEFINE did not surface — flagged
  here and in C-1.
- **`per_citation` may be empty on abstain / no-source answers.** The runner copies
  whatever the judge produced; on a retrieval-abstain the answer has no sources, so
  `per_citation` is `[]` (not `None`). This is correct (a real empty list, not "missing").
  AC-4 should not assume a non-empty `per_citation` unless the test fixture guarantees a
  cited source — see C-2.
- **Gold growth is bounded but non-zero (NFR-5 / the ADR-0007 concern).** Every record now
  carries the verdict lists — discrete labels, order of the existing `sources` /
  `retrieval_ranked_ids` lists, not prose. ADR-0010 must state this delta is small and
  distinct from the prompt bloat that stays in bronze; this is the _scoped_-amendment
  justification, not a reversal.
- **Bronze is designed but un-exercised.** ADR-0010 specifies a writer no code calls until
  Phase 19. The risk is the spec drifting from the Phase 19 build — mitigated by ADR-0010
  being the ratified contract Phase 19 implements against (the explicit RQ-3 decision).
- **KB stays stale until the deferred refresh.** The new `per_fact`/`per_citation` fields
  won't appear in `rag-eval`'s `eval-record-schema` concept until the post-ADR
  `/update-kb rag-eval`. Deferred by the Sprint-Wide Knowledge Plan — acceptable, not a
  gap.
- **ADR warranted? Yes — and it is the deliverable.** Unlike Phase 17 (no ADR), this phase
  _is_ an ADR: it amends a prior accepted decision (ADR-0007) and ratifies a data-layering
  contract (bronze/gold). FR-4 makes ADR-0010 the central artifact — correctly above the
  "ADR only if non-trivial" bar.

## Next Step

→ `/implement sprint-6/phase-18-evalrecord-reasoning` — gaps are clean (none blocking).
Per the cross-tool **Implement Contract** (AGENTS.md), the implement stage may run in
**Antigravity / Gemini** against this `DESIGN.md` as the contract: confirm the branch
`sprint-6/phase-18-evalrecord-reasoning`, read this manifest + `DEFINE.md` (acceptance
criteria) + the `rag-eval` KB (`eval-record-schema`, `stats-capture-seam`,
`cassette-replay-eval`), implement in phase order (schema → runner → ADR-0010 + ADR-0007
pointer → tests), **invert the stale exclusion assertions in `test_records.py:66-72`
first**, then `make lint test`.
