# DEFINE: sprint-3/phase-8-failure-taxonomy — Rule-Based Failure-Mode Classifier

**Sprint/Phase:** sprint-3/phase-8-failure-taxonomy | **Date:** 2026-05-30

## Resolved Open Questions

The BRAINSTORM's five open questions (Q1–Q5) are **all resolved** — the user reviewed
them and made the calls. They are recorded here as **fixed inputs**; `/design` and
`/implement` treat them as settled — do **not** re-open them. Where a decision conflicts
with the SPRINT.md framing (the `formatting` label name), the decision **supersedes** it.

- **Q1 — Thresholds = empirically grounded + named module constants (fixed).** The
  hallucination (`faithfulness_ratio`) and incomplete (`fact_recall`) cutoffs are **not**
  arbitrary `0.5` placeholders. They are chosen by inspecting the **committed baseline
  JSONL** (`results/baseline.jsonl`, the ~999-record `gpt-5-nano` vs Haiku 4.5 Phase 6
  sweep, committed in Phase 7 / FR-8) `faithfulness_ratio` / `fact_recall` distributions,
  then stored as **named module-level constants** in `failure_taxonomy.py` (e.g.
  `HALLUCINATION_FAITHFULNESS_THRESHOLD`, `INCOMPLETE_RECALL_THRESHOLD`). **ADR-0008
  documents the chosen values AND the empirical rationale** (the distribution they were
  derived from). **Not** config-YAML (over-engineering for a one-time classifier — an
  explicit Could/Won't). The actual number-picking is a `/design` + `/implement` activity;
  DEFINE requires that the values be empirically grounded and documented, **not** that
  DEFINE picks them. (FR-4, FR-7, AC-4, AC-9)
- **Q2 — Label renamed `formatting` → `incomplete` (fixed; supersedes SPRINT.md).** The
  five-label vocabulary is exactly: `abstention_error`, `retrieval_miss`, `hallucination`,
  `incomplete`, `correct`. Rationale: given aggregate-only signal, this mode means
  "retrieved relevant docs, cited them faithfully, but still missed required facts (low
  `fact_recall`)" — an **incomplete** answer, not a structural format fault (which is
  undetectable from aggregates). ADR-0008 states this definition explicitly. This
  **supersedes** the SPRINT.md "formatting" label name. (FR-1, FR-5, AC-1, AC-5, AC-9)
- **Q3 — ADR-0008 owns the `failure_mode` field (fixed).** The additive
  `failure_mode: str | None = None` field on `EvalRecord` is **introduced and owned by
  ADR-0008** (it is part of the taxonomy decision), with a **one-line cross-reference**
  added to ADR-0007 (**not** a full ADR-0007 amendment). Backward-compatible: `None` =
  "not yet classified"; existing untagged records read cleanly via the Pydantic default.
  (FR-6, AC-6, AC-9)
- **Q4 — New `rag-classify` console script (fixed).** A **new** console script
  `rag-classify` (entry `enterprise_rag_ops.eval.classify_cli:main` or similar — `/design`
  pins the exact module path) in `pyproject.toml [project.scripts]`, consistent with the
  per-concern pattern (`rag-ingest` / `rag-index` / `rag-ask` / `rag-eval` /
  `rag-export-traces`). **Not** a `rag-eval` subcommand. (FR-8, AC-8)
- **Q5 — Gold join via `load_questions` at classify time (fixed; network once, then
  committed).** `rag-classify` streams the gold `Question` set via the existing
  `load_questions` (HF, pinned `DATASET_REVISION`), joins on `question_id` to get
  `expected_doc_ids` (the retrieval-hit + `should_abstain` predicates). **Network is
  needed once at classify time**; the classifier runs once and the **tagged baseline
  JSONL is committed**, so the Phase 9 dashboard + the cloneable exit demo stay offline.
  **No** Phase 6 schema change to carry gold into `EvalRecord` (explicit Won't — it would
  require a paid backfill of the committed baseline). A `--questions-revision` override
  may be a Could; default is the pinned SHA. (FR-3, FR-8, NFR-1, AC-3, AC-8)

**Aggregate-granularity precision limitation (fixed constraint).** ADR-0007
**deliberately omits** the raw per-fact / per-citation verdict lists, so the classifier
works off **aggregates + gold only**. Fine-grained "_which_ fact hallucinated / _which_
citation was spurious" is **not derivable** (it needs the deferred `supporting_doc_id`
backlog). This is an explicit NFR and ADR-0008 consequence, **not** a defect of this
phase. (NFR-4, AC-9)

**Backlog (NOT this phase).** (1) Carrying gold (`expected_doc_ids` / `should_abstain`)
into `EvalRecord` at eval time — would make the classifier self-contained from the JSONL
alone but touches the Phase 6 runner + requires a paid baseline backfill (Q5 Won't).
(2) The `supporting_doc_id` per-fact attribution backlog that would unlock fine-grained
modes (NFR-4). (3) `/new-kb observability` capturing the decided taxonomy schema — owned
at sprint-close after ADR-0008 is accepted (per SPRINT.md), not this phase.

## Requirements

### Functional

- **FR-1 (`FailureMode` str-enum — exactly five labels)** —
  `src/enterprise_rag_ops/eval/failure_taxonomy.py` defines a `FailureMode` enum whose
  members are **exactly**: `abstention_error`, `retrieval_miss`, `hallucination`,
  `incomplete`, `correct`. It is a **`str`-valued enum** (`class FailureMode(str, Enum)`)
  so the tag round-trips cleanly through the JSONL via Pydantic with no custom serializer
  (Should, but cheap and adopted in the Must spine). `correct` is a **real positive
  classification**, not a dustbin (Q2).
- **FR-2 (Priority-ordered cascade — `classify`)** — `failure_taxonomy.py` exposes
  `classify(record: EvalRecord, question: Question) -> FailureMode`, a **first-match-wins**
  cascade in the **fixed order** `abstention_error → retrieval_miss → hallucination →
incomplete → correct`, returning **exactly one** label by construction. Pure Python,
  **zero LLM calls**, deterministic. Each branch is a **named predicate function** (e.g.
  `is_abstention_error`, `is_retrieval_miss`, `is_hallucination`, `is_incomplete`) for
  unit-testability.
- **FR-3 (Predicate definitions over `EvalRecord` + `Question`)** — each predicate reads
  **only** the available signal (the persisted `EvalRecord` aggregates + the gold
  `Question` joined on `question_id`):
  - **`abstention_error`** (checked **FIRST**): `should_abstain != did_abstain_e2e`, where
    `should_abstain = (len(question.expected_doc_ids) == 0)` (the existing
    `eval/abstention.py` convention). Covers both false abstention (answerable question,
    model refused) and failure-to-abstain (unanswerable question, model answered). Checked
    first because a false abstention has `0`/`None` `fact_recall` and would mis-fire as
    `hallucination` or `incomplete` otherwise.
  - **`retrieval_miss`**: answerable (`len(question.expected_doc_ids) > 0`) **AND**
    `set(question.expected_doc_ids) ∩ set(record.retrieval_ranked_ids[:record.k]) == ∅` —
    the retriever returned zero gold docs in the top-k. (Binary miss, not a fractional
    recall threshold — matches the doc-level `retrieval_ranked_ids` already persisted.)
  - **`hallucination`**: retrieval hit **AND** `record.faithfulness_ratio is not None`
    **AND** `record.faithfulness_ratio < HALLUCINATION_FAITHFULNESS_THRESHOLD`. A
    **`None` faithfulness must NOT classify as hallucination** (explicit guard — `None`
    means empty-denominator / no sources cited, per ADR-0007).
  - **`incomplete`**: retrieval hit, faithfulness OK (above threshold, **or** `None` due to
    no sources cited on a non-abstaining answer), **AND** `record.fact_recall is not None`
    **AND** `record.fact_recall < INCOMPLETE_RECALL_THRESHOLD`, **AND** not abstaining.
    A `None` `fact_recall` must **not** classify as `incomplete` (guard).
  - **`correct`**: falls through all of the above — a real positive (no abstention error,
    retrieval hit or correct abstention, faithfulness OK, recall OK).
- **FR-4 (Empirically-grounded named threshold constants)** — the hallucination and
  incomplete cutoffs are **module-level named constants** in `failure_taxonomy.py` (e.g.
  `HALLUCINATION_FAITHFULNESS_THRESHOLD`, `INCOMPLETE_RECALL_THRESHOLD`), **not** inline
  magic numbers and **not** a config YAML. Their values are **derived from inspecting the
  committed `results/baseline.jsonl` distributions** of `faithfulness_ratio` /
  `fact_recall` (the number-picking is a `/design` + `/implement` activity); ADR-0008
  records both the chosen values **and** the empirical rationale (Q1).
- **FR-5 (`incomplete` semantics, narrowly defined)** — `incomplete` is defined as
  "retrieved relevant docs, cited them faithfully, but the final answer still missed
  required facts (low `fact_recall`)" — an answer-completeness failure, **not** a
  structural format violation (which is undetectable from aggregates). ADR-0008 states
  this definition explicitly so the Phase 9 dashboard label is unambiguous to a reviewer
  (Q2).
- **FR-6 (`failure_mode` additive field on `EvalRecord`)** —
  `failure_mode: str | None = None` is added to `EvalRecord` in `eval/records.py`. The
  Pydantic default `None` means "not yet classified" — **backward-compatible**: existing
  untagged JSONL reads cleanly. The field is **owned by ADR-0008** with a one-line
  cross-reference in ADR-0007 (Q3). This is the **only** edit to a Phase 6 module
  (NFR-2).
- **FR-7 (`rag-classify` console script + `classify_cli.py`)** — a new
  `enterprise_rag_ops.eval.classify_cli:main` (exact module path pinned at `/design`) is
  wired as the **`rag-classify`** console script in `pyproject.toml [project.scripts]`.
  Flags: `--results <path>` (the JSONL to classify, in), `--output <path>` (tagged
  records out; **default: overwrite the input file**). It reads each line into an
  `EvalRecord`, streams the gold `Question` set via `load_questions` (pinned
  `DATASET_REVISION`), joins on `question_id`, calls `classify`, sets `failure_mode`, and
  writes the tagged records. **Network is used once here** at classify time (Q5).
- **FR-8 (`make classify` target) — Should.** A `make classify` target runs
  `uv run rag-classify --results results/baseline.jsonl`, added to the `.PHONY` list and
  chaining cleanly after the eval / export-traces flow. Absence does not fail the phase.
- **FR-9 (`--dry-run`) — Could.** `rag-classify --dry-run` prints the classification
  **distribution** (count per `FailureMode`) **without writing** the JSONL — useful for
  validating thresholds against the baseline before committing the tagged file. Absence
  does not fail the phase.
- **FR-10 (`--questions-revision` override) — Could.** A `--questions-revision <sha>`
  flag overrides the pinned `DATASET_REVISION` passed to `load_questions`; default is the
  pinned SHA. Absence does not fail the phase.
- **FR-11 (ADR-0008 written + accepted)** — `docs/adr/0008-failure-taxonomy.md` is
  **written and accepted** in this phase, recording: (a) the five-label vocabulary (exact
  strings) and each label's definition over the available signal; (b) the cascade priority
  order and the justification for `abstention_error` first; (c) the formal predicate for
  each label by `EvalRecord` / `Question` field name; (d) the **empirical threshold
  values + the distribution rationale** (Q1); (e) the `incomplete` definition (Q2,
  superseding "formatting"); (f) the **aggregate-granularity precision limitation** (no
  per-fact / per-citation attribution — NFR-4); (g) the `failure_mode` field ownership +
  type + `str`-enum serialization + the one-line ADR-0007 cross-reference (Q3).
- **FR-12 (Offline unit tests, mirrored)** — `tests/eval/test_failure_taxonomy.py`
  (mirroring `src/.../eval/failure_taxonomy.py`, with an `__init__.py` in `tests/eval/`)
  uses **hand-built `EvalRecord` + `Question` fixtures** — **no mocks, no cassette, no
  network**. It covers **one fixture per label** plus the edge cases: (i) `None`
  faithfulness on a **correct abstention** → `abstention_error`/`correct`, never
  `hallucination`; (ii) **retrieval miss with `None` `fact_recall`** → `retrieval_miss`,
  not `incomplete`; (iii) a **full-hit correct** record → `correct`; (iv) a **false
  abstention** (answerable, model abstained, `0`/`None` recall) → `abstention_error`, not
  `hallucination`/`incomplete`; (v) `None` `fact_recall` on a retrieval-hit non-abstaining
  record does not mis-fire `incomplete`.

### Non-functional

- **NFR-1 (Offline `make test` — no LLM API, no cassette, gold mocked/fixture)** — every
  Phase 8 test runs under `make test` with **no network I/O and no API keys**. The
  classifier issues **zero LLM calls** (pure rule logic over persisted aggregates), so
  **no cassette/replay is needed** — unlike Phase 6, there is no LLM-API path to record
  (ADR-0006's cassette rule applies only to LLM-API paths). In tests the gold join is a
  **hand-built `Question` fixture**, never a live `load_questions`; the real network call
  happens **only at runtime** when the maintainer runs `rag-classify`.
- **NFR-2 (Purely additive over the JSONL — one Phase 6 field only)** — Phase 8 adds the
  new `failure_taxonomy.py` module + `classify_cli.py` + the mirrored test + ADR-0008 +
  `pyproject` / Makefile wiring + the one-line ADR-0007 cross-reference. The **only** edit
  to existing Phase 6 code is the single additive `failure_mode` field on `EvalRecord`
  (FR-6). It touches **no** eval runner, **no** judge/retrieval/abstention logic, **no**
  configs, and **no** Phoenix exporter (Phase 7).
- **NFR-3 (No new runtime dependencies)** — the classifier is **pure Python** over the
  existing `datasets` (for `load_questions`) and `pydantic` (`EvalRecord` parsing) deps.
  **No new runtime dependency** is introduced. No specialist agent is warranted.
- **NFR-4 (Aggregate-granularity precision limitation — explicit)** — classification is at
  **aggregate granularity**: `hallucination` means "faithfulness ratio below threshold,"
  **not** "this specific fact was fabricated"; `incomplete` means "fact recall below
  threshold," not "this specific required fact is missing." Fine-grained per-fact /
  per-citation attribution is **not derivable** from the persisted signal (ADR-0007 omits
  the raw verdict lists) and needs the deferred `supporting_doc_id` backlog. ADR-0008
  documents this as a stated consequence (FR-11f).
- **NFR-5 (Offline-after-classify demo)** — the classifier runs **once** with network
  (the gold join), and the **tagged baseline JSONL is committed**, so the Phase 9
  dashboard and the cloneable exit demo read it with **no network and no paid eval
  re-run** (consistent with the Phase 7 NFR-5 bar).
- **NFR-6 (Minimal scope — one module + CLI + ADR)** — the phase is bounded to one
  classifier module, one CLI / console script, one mirrored test file, ADR-0008, the
  single additive `EvalRecord` field, and `pyproject` / Makefile / ADR-0007 cross-ref
  wiring. Shoulds/Coulds (FR-8 `make classify`, FR-9 `--dry-run`, FR-10
  `--questions-revision`) slot in only after the Must spine; their absence does not fail
  the phase. Explicit Won't: config-YAML thresholds, `abstention_error` sublabels,
  multi-label sets, per-fact attribution, any Phase 6 runner / eval-path / Phoenix change,
  dashboard integration (Phase 9), live classification during the eval run.
- **NFR-7 (Conventions + mirrored tests + stranger test)** — English; YYYY-MM-DD dates in
  docs; Conventional Commits; the new module gets its mirrored
  `tests/eval/test_failure_taxonomy.py` (subdir with `__init__.py`, never a flat
  `tests/test_failure_taxonomy.py`); `make lint test` passes with no network/key. No
  career/personal content in any tracked Phase 8 file.

## Acceptance Criteria

1. `failure_taxonomy.py` defines `FailureMode` as a **`str`-valued enum** whose members
   are **exactly** `abstention_error`, `retrieval_miss`, `hallucination`, `incomplete`,
   `correct` (no more, no fewer; `correct` present as a positive label). Verified by a
   unit test asserting the member set and that a member serializes to its plain string
   value through a Pydantic round-trip. (FR-1)
2. `classify(record, question)` returns **exactly one** `FailureMode`, evaluating
   predicates in the fixed order `abstention_error → retrieval_miss → hallucination →
incomplete → correct` (first-match-wins). Verified by unit tests that construct a
   record satisfying multiple predicates and assert the **higher-priority** label wins
   (e.g. a false abstention that also has low recall returns `abstention_error`, not
   `incomplete`). Each branch is a separately-callable named predicate function. (FR-2)
3. Each predicate reads **only** `EvalRecord` aggregates + the gold `Question` joined on
   `question_id`: `abstention_error` = `should_abstain != did_abstain_e2e` with
   `should_abstain = (len(expected_doc_ids) == 0)`; `retrieval_miss` = answerable AND
   `expected_doc_ids ∩ retrieval_ranked_ids[:k] == ∅`; `hallucination` = retrieval hit AND
   `faithfulness_ratio is not None` AND `< HALLUCINATION_FAITHFULNESS_THRESHOLD`;
   `incomplete` = retrieval hit AND faithfulness OK/None AND `fact_recall is not None` AND
   `< INCOMPLETE_RECALL_THRESHOLD` AND not abstaining. Verified by one fixture per label
   asserting the expected label. (FR-3)
4. The hallucination and incomplete cutoffs are **named module-level constants** (not
   inline literals, not a config file), and ADR-0008 records both their **values** and the
   **`results/baseline.jsonl` distribution** they were derived from. Verified by inspecting
   the module (named constants referenced by the predicates) and ADR-0008 (values +
   empirical rationale section). (FR-4, FR-11d, Q1)
5. `incomplete` is documented in ADR-0008 as "retrieved + cited faithfully but missed
   required facts (low `fact_recall`)" — explicitly **not** a structural format fault — and
   the label string is `incomplete` (not `formatting`). Verified by inspecting ADR-0008's
   vocabulary section and the `FailureMode` enum. (FR-5, Q2)
6. `EvalRecord` gains `failure_mode: str | None = None`; an existing untagged JSONL line
   (no `failure_mode` key) parses cleanly with `failure_mode is None`, and a tagged line
   round-trips its label string. Verified by a unit test parsing both a pre-Phase-8 and a
   post-classify JSON line. (FR-6, Q3)
7. `rag-classify` (console script in `pyproject.toml`) accepts `--results` and `--output`
   (default: overwrite input), reads each line into an `EvalRecord`, joins gold via
   `load_questions` on `question_id`, sets `failure_mode`, and writes the tagged records.
   Verified by an offline CLI test driving the entry point over a hand-built 2-record JSONL
   with a **fixture/patched gold loader** (no network), asserting each output record
   carries the expected `failure_mode`. (FR-7, NFR-1)
8. The `rag-classify` console script is a **new** entry in `pyproject.toml [project.scripts]`
   (not a `rag-eval` subcommand), consistent with `rag-ingest` / `rag-index` / `rag-ask` /
   `rag-eval` / `rag-export-traces`. Verified by inspecting `pyproject.toml`. (FR-7, Q4)
9. `docs/adr/0008-failure-taxonomy.md` status reads **accepted** and records: the five-label
   vocabulary + definitions, the cascade order + `abstention_error`-first justification, the
   per-label predicates by field name, the empirical threshold values + rationale, the
   `incomplete` definition, the aggregate-granularity precision limitation, and the
   `failure_mode` field ownership (type + `str`-enum serialization + one-line ADR-0007
   cross-reference). ADR-0007 gains a one-line cross-reference to ADR-0008 (no full
   amendment). Verified by inspecting both ADRs. (FR-11, Q1, Q2, Q3, NFR-4)
10. `tests/eval/test_failure_taxonomy.py` (in a `tests/eval/` subdir with `__init__.py`)
    passes under `make test` with **no network, no API key, and no cassette**, using
    hand-built `EvalRecord` + `Question` fixtures. It covers one fixture per label plus the
    edge cases: `None` faithfulness on a correct abstention is never `hallucination`;
    retrieval miss with `None` `fact_recall` is `retrieval_miss` not `incomplete`; a
    full-hit record is `correct`; a false abstention is `abstention_error` not
    `hallucination`/`incomplete`; `None` `fact_recall` on a retrieval-hit non-abstaining
    record does not mis-fire `incomplete`. Verified in CI on the PR (`make lint test`
    green, offline). (FR-12, NFR-1, NFR-7)
11. **Additive invariant (NFR-2):** the Phase 8 diff touches **no** file under
    `src/enterprise_rag_ops/eval/` **except** the single additive `failure_mode` field on
    `EvalRecord` (and the two new files `failure_taxonomy.py` + `classify_cli.py`), **no**
    `configs/`, **no** `observability/` (Phase 7), and **no** other Phase 6 module — plus
    `pyproject` / Makefile additions and the two ADR edits. Verified by inspecting the PR
    diff file list. (NFR-2, NFR-3)
12. **No new runtime dependency (NFR-3):** the classifier uses only existing `datasets` +
    `pydantic`; `pyproject.toml [project.dependencies]` is unchanged. Verified by inspecting
    the dependency list in the PR diff.
13. (Should) `make classify` (FR-8) runs `uv run rag-classify --results
results/baseline.jsonl` and is listed in `.PHONY`. Verified by inspecting the Makefile.
    Absence does not fail the phase.
14. (Could) `--dry-run` (FR-9) prints the per-`FailureMode` distribution without writing,
    and `--questions-revision` (FR-10) overrides the pinned `DATASET_REVISION`. Verified by
    offline tests asserting no write fires under `--dry-run` and the revision is forwarded
    to the (patched) gold loader. Absence does not fail the phase.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Problem     | 3     | Root cause explicit with evidence: the Phase 6 sweep produces one `EvalRecord` per question per model but gives **no answer to "why did this fail?"** Phase 8 builds a deterministic rule-based classifier that maps each record to exactly one of five failure modes using **only** the aggregate signal ADR-0007 persists — powering the Phase 9 dashboard breakdown and letting a reviewer (with the Phase 7 traces) tell at a glance _where_ the pipeline broke.                                                                             |
| Users       | 2     | Consumers are the **maintainer** (runs `rag-classify`, inspects the tagged JSONL / distribution), the **Phase 9 dashboard** (reads `failure_mode` directly), and the **reviewer/hiring manager** reading the failure-mode breakdown. Internal phase — no external end-user workflow — so workflow-impact is inherently thin, scored honestly and consistently with the Phase 1–7 DEFINEs (which also scored Users 2).                                                                                                                            |
| Success     | 3     | 14 numbered, falsifiable acceptance criteria covering every FR/NFR: the exact five-label `str`-enum, the first-match cascade + priority-wins, each predicate by field name, the empirically-grounded named constants + ADR rationale, the `incomplete` definition, the additive `failure_mode` field + backward-compatible parse, the `rag-classify` console script + offline CLI test, ADR-0008 acceptance, the offline test suite + edge cases, the additive + no-new-dep invariants. Shoulds/Coulds marked "absence does not fail the phase." |
| Scope       | 3     | Full MoSCoW carried from the BRAINSTORM and re-pointed with the resolved decisions: Musts (enum + cascade + predicates + named thresholds + `failure_mode` field + `rag-classify` + mirrored tests + ADR-0008), Should (`make classify`, `str`-enum), Could (`--dry-run`, `--questions-revision`), explicit Won't (config-YAML thresholds, `abstention_error` sublabels, multi-label, per-fact attribution, any Phase 6 runner / eval-path / Phoenix-exporter change, gold-in-`EvalRecord`, dashboard→Phase 9, live classification).             |
| Constraints | 3     | All constraints named as NFRs: offline `make test` with **no LLM API and no cassette** (the positive — there is no LLM path to mock, NFR-1); purely additive over the JSONL with the single `failure_mode` field as the only Phase 6 edit (NFR-2); no new runtime dep (NFR-3); the **aggregate-granularity precision limitation** as an explicit NFR + ADR consequence (NFR-4); offline-after-classify committed-tagged-JSONL demo (NFR-5); minimal scope (NFR-6); conventions + mirrored subdir tests + stranger test (NFR-7).                  |

**Total: 14/15 — PASS (≥12).** Users scored 2 for the same structural reason as Phases
1–7: an internal phase whose "users" are the maintainer, the Phase 9 dashboard, and a
portfolio reviewer, so workflow-impact is inherently thin — acceptable, not a blocker, and
consistent across the whole DEFINE history. **All five BRAINSTORM open questions (Q1–Q5)
were resolved by the user before `/define`** (the `§ Resolved Open Questions` block) — no
design ambiguity remains to invent. No `AskUserQuestion` round was needed; nothing was
passed forward below the gate. (`AskUserQuestion` was available this run; it was not needed.)

## Infrastructure Readiness

| Dependency                                               | KB domain        | Specialist | Status                                                                                                                                                                                                                                                                                                                                                   |
| -------------------------------------------------------- | ---------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EvalRecord` / `CallStats` schema (`eval/records.py`)    | `rag-eval`       | none       | **Ready — read + minimally extended.** The classifier reads every aggregate it needs (`faithfulness_ratio`, `fact_recall`, `retrieval_ranked_ids`, `k`, `did_abstain_e2e`); the only change is the additive `failure_mode: str \| None = None` field (FR-6). `rag-eval` KB (`eval-record-schema`, `none-empty-denominator`) covers it.                   |
| Gold `Question` + `load_questions` (`eval/questions.py`) | `rag-eval`       | none       | **Ready — network at runtime only.** Provides `expected_doc_ids` (retrieval-hit) and `should_abstain` (empty-gold) via the pinned `DATASET_REVISION`. Used once at `rag-classify` time; **mocked/fixture in tests** (NFR-1, Q5). Loader needs no change — joins on `question_id`.                                                                        |
| ADR-0007 (eval-record schema authority)                  | `rag-eval`       | none       | **Cross-referenced, not amended.** ADR-0007 stays the schema authority; ADR-0008 owns the additive `failure_mode` field, with a **one-line** cross-reference added to ADR-0007 (Q3, FR-11g, AC-9). No full amendment.                                                                                                                                    |
| ADR-0008 (failure taxonomy + field ownership)            | `observability`  | none       | **Written + accepted this phase (FR-11, AC-9).** Owns vocabulary, cascade order, predicates, empirical thresholds + rationale, the `incomplete` definition, the aggregate-granularity precision limitation, and the `EvalRecord` field ownership.                                                                                                        |
| `results/baseline.jsonl` (empirical-threshold input)     | none needed      | none       | **Ready — committed in Phase 7 (FR-8/AC-8 there).** The ~999-record `gpt-5-nano` vs Haiku 4.5 sweep is the distribution the threshold constants are derived from (Q1, FR-4); after classify it carries the `failure_mode` tags for Phase 9 + the offline demo (NFR-5).                                                                                   |
| `pydantic` (`EvalRecord` parse + serialize)              | none needed      | none       | Ready — already a runtime dep (`pydantic>=2.6,<3.0`). No new dep; the `str`-enum round-trips natively.                                                                                                                                                                                                                                                   |
| `datasets` (`load_questions` gold stream)                | none needed      | none       | Ready — already a runtime dep (used by the existing `load_questions`). No new dep (NFR-3).                                                                                                                                                                                                                                                               |
| `observability` KB domain                                | `observability`  | none       | **MISSING — deferred, NOT blocking.** SPRINT.md schedules `/new-kb observability` **after** ADR-0008 is accepted (it documents the _decided_ taxonomy schema alongside the Phase 7 tracing pattern). Not in `_index.yaml`. Build at sprint-close, not before `/design`.                                                                                  |
| `rag-generation` KB scaffold                             | `rag-generation` | none       | **Empty scaffold, unregistered — optional, NOT blocking.** SPRINT.md flags it as cheap-but-off-critical-path. The classifier reads the abstention sentinel contract, but the **`rag-eval` `abstention-scoring` concept already covers `should_abstain`** — so the prerequisite is met. `/new-kb rag-generation` is a nice-to-have, not a `/design` gate. |
| Failure-taxonomy specialist agent                        | n/a              | none       | **Not warranted.** One additive pure-Python module + CLI over a well-documented input contract; no recurring specialist context-loading. Revisit only if Phase 9 + future taxonomy work create a loop.                                                                                                                                                   |

**Gaps and recommendations.** **No `/new-kb` or `/new-agent` blocks `/design`.** The
classifier's input contract is fully covered by the `rag-eval` KB + ADR-0007 + the
`Question` loader, and the threshold-distribution input (`results/baseline.jsonl`) is
already committed. Two non-blocking items are logged for the orchestrator: (1)
**`/new-kb observability`** is **deferred to sprint-close** (after ADR-0008 acceptance)
per SPRINT.md — recommend running it at `/review` / sprint-close to capture the decided
taxonomy; (2) **`/new-kb rag-generation`** remains an optional cheap-debt cleanup the
SPRINT.md retro flagged — off the critical path and **not** required for this phase
because `rag-eval`'s `abstention-scoring` concept already documents the `should_abstain`
contract the classifier relies on. No new runtime dependency and no specialist agent are
recommended.

## Sequencing Notes (not requirements)

- **One phase / one PR** on `sprint-3/phase-8-failure-taxonomy`, with a disciplined commit
  sequence: (1) the additive `failure_mode` field on `EvalRecord` (`eval/records.py`) +
  the one-line ADR-0007 cross-reference; (2) `eval/failure_taxonomy.py` (`FailureMode`
  enum, named predicate functions, named threshold constants, the `classify` cascade) +
  `tests/eval/test_failure_taxonomy.py` (fully offline, hand-built fixtures); (3)
  `eval/classify_cli.py` + the `rag-classify` console script in `pyproject.toml` + (Should)
  `make classify`; (4) run `rag-classify` against the committed `results/baseline.jsonl`
  and **commit the tagged JSONL** (the one network step — gold join, then offline
  thereafter); (5) `docs/adr/0008-failure-taxonomy.md` written + accepted. Shoulds/Coulds
  (FR-8 `make classify`, FR-9 `--dry-run`, FR-10 `--questions-revision`) slot in after the
  Must spine; their absence does not fail the phase.
- **One live step only.** The classifier issues **no LLM calls**, so there is no cassette
  to record (unlike Phase 6). The only network touch is `load_questions` (the gold join)
  during the maintainer's one-time `rag-classify` run; the committed tagged JSONL then
  keeps Phase 9 + the exit demo offline.
- **`/design` decisions to pin:** **(sharpest)** the **exact numeric values** of
  `HALLUCINATION_FAITHFULNESS_THRESHOLD` and `INCOMPLETE_RECALL_THRESHOLD`, chosen by
  inspecting the committed `results/baseline.jsonl` `faithfulness_ratio` / `fact_recall`
  distributions, with the rationale written into ADR-0008 — this is the single most
  consequential parameter and DEFINE deliberately leaves the number-picking to
  `/design` + `/implement`. Plus: the exact `classify_cli` module path; the `--output`
  default-overwrite semantics (in-place vs temp-then-rename); how `classify` treats a
  record whose `question_id` is absent from the gold set (raise vs skip-with-warning); and
  whether the retrieval-hit slice uses `record.k` or `len(retrieval_ranked_ids)`. None
  reopen a DEFINE-level question.

## Next Step

→ `/design sprint-3/phase-8-failure-taxonomy`
