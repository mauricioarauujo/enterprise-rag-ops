# DEFINE: sprint-6/phase-17-qa-legibility — Question + Answer Legibility (No Re-run)

**Sprint/Phase:** sprint-6/phase-17-qa-legibility | **Date:** 2026-06-02
**Approach:** Split by data origin. The **answer** (in-record, zero I/O) is mapped always-on
in the pure mapper (`build_span_attrs` adds `output.value` from `record.answer`). The
**question** (external gold read) is a Phase-16-mirrored boundary enrichment: the gold-question
join lives at the CLI/exporter boundary (`cli.py` builds a `{question_id: text}` `Mapping`;
`exporter.py` consumes it and mutates `span_attrs["chain"]` in place), exactly as
`--enrich-from-index` does the corpus join. `observability/attributes.py` stays a **pure
mapper** (no new imports — `record.answer` is already the param). **No ADR** — the coupling is
a stdlib `Mapping[str, str]` passed at the boundary (the sprint "ADR only if non-trivial" bar
is not met; same call as Phase 16 OQ-5).

**Resolved fork (CONFIRMED by orchestrator + user, 2026-06-02 — see Resolved Open Questions
RQ-1):** **answer hydration is always-on in the pure mapper; question hydration is opt-in via
`--enrich-from-questions` at the boundary** (the BRAINSTORM's Approach C). Rationale:
`build_span_attrs` already maps **every** in-record `EvalRecord` field unconditionally
(`question_id`, `category`, tokens, cost, model); `record.answer` is just another in-record
field, so mapping it to `output.value` always-on is the **consistent** choice — gating it
behind a flag would make it the sole conditional in-record field. The opt-in discipline
exists for **external reads** (corpus in Phase 16, gold here); its real purpose is "no
surprise I/O on the default path," not "frozen output bytes." The answer needs **zero** I/O,
so it rides the default path like every other in-record field; only the question (a real gold
read) is gated. Net effect on the default export: it gains exactly one key —
`output.value`/`output.mime_type` (the answer) on the generation span — and nothing else.

## Problem

A failed Phoenix trace today shows metadata (IDs, metrics, model names) and — since
Phase 16's `--enrich-from-index` — the retrieved-doc **content**. But the **question text**
and the **generated answer** are still invisible in Phoenix's **Info** tab: a reviewer must
leave Phoenix and grep the raw `results/*.jsonl`. This is the exact symptom Sprint 6 exists
to close ("a failed trace explains itself"), and it is half-answerable visually today.

The decisive facts (all confirmed in source this session):

- **The answer is already persisted.** `EvalRecord.answer: str` exists
  (`eval/records.py:87`) — the plain text field of `AnswerWithSources`, no deserialization
  needed. Writing it to a span attribute needs **zero** I/O.
- **The question text is external.** It is **not** on `EvalRecord`; it is joined from gold
  via `load_questions()` (`eval/questions.py:60`) keyed by `question_id` — exactly the
  pattern `rag-triage`/`rag-classify` use (`triage_cli.py:47-50,69-70` with a
  `--questions-revision` default of `config.DATASET_REVISION`). `load_questions()` hits HF
  (or a local cache): a real external read, so it belongs at the boundary, opt-in.
- **The right OpenInference keys are known.** Phoenix's **Info** tab renders from
  `input.value` (+ `input.mime_type`, e.g. `"text/plain"`) on the chain (root) span and
  `output.value` (+ `output.mime_type`) on the generation span. These keys are unset today
  → the Info tab is empty (confirmed via Context7 `/arize-ai/openinference` this session).
  So: **question → chain span `input.value`; answer → generation span `output.value`**.
- **The span tree already has the right shape.** `exporter.py` opens a chain root span and
  a `generation` child (`span-tree-shape` KB); `build_span_attrs` returns a
  `{role: attrs}` dict (`attributes.py:11`) that the exporter already mutates in place for
  the Phase 16 retriever-content path (`exporter.py:83-95`). Phase 17 adds the
  generation-`output.value` in the mapper (always-on) and the chain-`input.value` at the
  boundary under `--enrich-from-questions`.

The Phase 16 discipline this phase inherits and refines: `attributes.py` is a **pure mapper**
(imports only `typing` + `EvalRecord`); **external reads** (the gold join) live at the
CLI/exporter boundary and are **opt-in, default-off** (no surprise I/O on the default path).
The refinement: **in-record** data (`record.answer`) is mapped always-on like every other
in-record field — the opt-in gate is for external reads, not in-record values. So the default
export equals the prior result **plus** the answer `output.value`; only the gold-derived
question is gated. Phase 17 reuses the Phase 16 boundary shape for the question rather than
inventing a new one.

## Users / Stakeholders

- **Maintainer (Mauricio) debugging in Phoenix** — the primary actor. Even on a default
  export the **generated answer** is now visible on the generation span Info tab (always-on);
  running `rag-export-traces --enrich-from-questions` additionally surfaces the **question**
  on the chain span Info tab — so a failed trace reads question → evidence → answer inline,
  without grepping raw JSONL. Needs the default path to do no surprise external I/O (the gold
  read stays opt-in).
- **Public-repo reviewer / hiring signal** — sees that a single failed trace is becoming
  legible end-to-end in Phoenix (the Sprint 6 headline) and that activating it did **not**
  pollute the pure attribute mapper (the observability-coupling discipline holds).
- **`observability/attributes.py` (the pure mapper, NFR-1)** — the constraint to protect.
  It must keep its `build_span_attrs(record) -> dict[...]` signature and import only
  `typing` + `EvalRecord`. The gold join must **not** be pulled into it.
- **`eval/questions.py::load_questions` + `Question.question` (shipped)** — the upstream
  question-text source, consumed read-only via the gold join at the boundary;
  `Question.question_id` → key, `Question.question` → value.
- **Downstream phases 18/19** — depend on Phase 17 landing the no-re-run half so the costly
  re-run is quarantined to Phase 19. Generation-span **input** (the assembled prompt) and
  judge-span reasoning are not persisted today and are hard out of scope here.
- **Sprint-Wide Knowledge Plan / future maintainers** — `/update-kb observability`
  (`span-attribute-mapping` + `span-tree-shape`) lands **after** this impl to record the
  now-live `input.value`/`output.value` keys — deferred by design, not a gap.

## Requirements

### Functional

- **FR-1 Opt-in question flag (answer is not gated).** `rag-export-traces`
  (`observability/cli.py`, `_build_parser`) gains `--enrich-from-questions`
  (`action="store_true"`, default off), parallel to the existing `--enrich-from-index`. It
  gates **only** question hydration (gold join → chain `input.value`). When **absent**, no
  gold load happens and the chain span carries **no** `input.value`. **Answer hydration
  (`record.answer` → generation `output.value`) is always-on (FR-4), independent of this
  flag** — so the default export (no flag) equals today's output **plus** the generation
  `output.value`, and nothing else. (Fork RQ-1: answer always-on in the mapper, question
  opt-in at the boundary.)
- **FR-2 Gold map built once at the boundary.** When `--enrich-from-questions` is set (and
  not `--dry-run`, see FR-7), the CLI builds a `{question_id: question_text}` map **exactly
  once** before the replay loop via
  `{q.question_id: q.question for q in load_questions(revision=args.questions_revision)}`
  (`from enterprise_rag_ops.eval.questions import load_questions`). No per-record gold load.
  No `EvalRecord` schema change.
- **FR-3 `question_lookup` param on `replay_jsonl`.** `exporter.py::replay_jsonl` gains a
  new keyword-only parameter `question_lookup: Mapping[str, str] | None = None` (default
  `None` → question hydration skipped). `Mapping` is a `collections.abc` stdlib type already
  imported in `exporter.py` (line 4) — **no `datasets`/HF/Phoenix import is added to
  `exporter.py`**.
- **FR-4 Answer hydration (generation span `output.value`) — always-on in the mapper.**
  `build_span_attrs` sets `output.value = record.answer` and `output.mime_type = "text/plain"`
  on the generation attrs **unconditionally** (no flag, no lookup) — `record.answer` is
  already a `str` field on the `EvalRecord` parameter (the `AnswerWithSources` text), mapped
  like every other in-record field the mapper already emits. Both `output.value` and
  `output.mime_type` are written **together** at the same site (RQ-3). This adds **no** import
  to `attributes.py` (`record` is already the param), so purity (FR-10/NFR-1) is preserved.
- **FR-5 Question hydration (chain span `input.value`).** When `question_lookup is not
None`, inside the per-record loop in `replay_jsonl` — after `span_attrs =
build_span_attrs(record)` returns and **before** the chain span is opened — the exporter
  post-processes `span_attrs["chain"]` in place: if `record.question_id` is in
  `question_lookup`, it sets `span_attrs["chain"]["input.value"] =
question_lookup[record.question_id]` and `span_attrs["chain"]["input.mime_type"] =
"text/plain"` (both together, RQ-3). The existing chain keys (`question_id`, `category`,
  etc.) are preserved untouched.
- **FR-6 Missing-question-id → omit + warn (no crash).** If `record.question_id` is absent
  from `question_lookup`, the exporter **omits** `input.value`/`input.mime_type` for that
  record entirely (no empty string, no placeholder), logs a `logging.warning` naming the
  missing `question_id`, and continues — mirroring the Phase 16 missing-doc behavior
  (`exporter.py:89-95`). The path never raises on a missing id.
- **FR-7 Dry-run skips the gold load.** `--enrich-from-questions --dry-run` parses
  successfully and **does not** call `load_questions()` (no HF hit on dry-run) — mirroring
  the Phase 16 guard where `--enrich-from-index --dry-run` skips the corpus read
  (`cli.py:116`, `... and not args.dry_run`). Dry-run validates only the JSONL parse, as
  today. (RQ-2: resolved to the Phase 16 default — no HF cost on dry-run.)
- **FR-8 `--questions-revision` pinning (Should).** `rag-export-traces` gains an optional
  `--questions-revision` (default `config.DATASET_REVISION`,
  `from enterprise_rag_ops.ingest import config`), so a caller can pin the same gold SHA that
  produced the results — identical to `triage_cli.py:47-50`. A **Should**; if it complicates
  the diff, the `DATASET_REVISION` default-only path is the acceptable v1.
- **FR-9 In-place mutation, one enrichment shape.** Question hydration mutates
  `span_attrs["chain"]` in place in `exporter.py` after `build_span_attrs` returns — it does
  **not** introduce a new `build_span_attrs` overload or signature. This keeps a single
  enrichment shape in `exporter.py` (the same post-process-the-dict pattern as the Phase 16
  `doc_lookup` path), so the two enrichments read identically. (RQ-4: resolved to mirror
  Phase 16 exactly.)
- **FR-10 `attributes.py` purity preserved.** `build_span_attrs` keeps its exact signature
  `build_span_attrs(record: EvalRecord) -> dict[str, dict[str, Any]]` and its current
  imports (`typing.Any`, `EvalRecord`) — **no new import, no new parameter**. The mapper now
  additionally emits the answer's `output.value`/`output.mime_type` from `record.answer` (an
  existing field — no new import; FR-4). The **question's** `input.value` is the only piece
  written at the exporter boundary (FR-5), since it alone needs an external read — keeping the
  mapper trivially testable with a bare `EvalRecord`. Purity is about imports, not which
  in-record keys the mapper emits.

### Non-functional

- **NFR-1 `attributes.py` purity (sprint coupling-regression control).** Post-change,
  `observability/attributes.py` imports nothing from `eval/questions`, `datasets`/HF,
  `ingest/`, `retrieval/`, Phoenix, or OTel — exactly as today (only `typing` + `eval.records`).
  The pure mapper stays fully unit-testable offline with a bare `EvalRecord`.
- **NFR-2 Question opt-in / default-off / read-only (external read only).** The **gold read**
  is never the default: the gold set is loaded **once, read-only**, only when
  `--enrich-from-questions` is set (and not `--dry-run`), and the chain `input.value` is
  written only then. No eval sweep, no retrieval run, no classify/triage re-run is triggered
  (sprint no-re-runs guard). The default path performs **zero gold I/O**. The answer's
  `output.value` **is** written on the default path — but it is an in-record field read
  (`record.answer`), zero external I/O, mapped like every other in-record attribute; the
  opt-in discipline governs external reads, which the answer is not.
- **NFR-3 Offline, no-HF test path.** Both enrichments are exercised by injecting a fake
  in-memory `{question_id: text}` dict directly into
  `replay_jsonl(..., question_lookup=...)` — no `load_questions()` call, no HF/network, no
  Phoenix. Tests use the existing `NoOpScoreSink` / a fake sink (mirroring
  `tests/observability/test_exporter.py`). The CLI-wiring test patches `load_questions`.
- **NFR-4 House structure + boundary rule.** The heavy/external read (`load_questions`,
  `DATASET_REVISION`) lives at the CLI boundary (`cli.py` builds the map); `exporter.py`
  consumes a plain `Mapping`; the pure mapper is untouched. argparse + `logging` patterns
  inherit from the existing `cli.py`.
- **NFR-5 Test mirror.** Enrichment tests land in `tests/observability/test_exporter.py`
  (existing file, package has `__init__.py`); CLI-flag/dry-run wiring may add a focused test
  there or in `tests/observability/test_cli.py`. No flat `tests/test_*.py`. `make lint test`
  is the gate.
- **NFR-6 Determinism.** Same JSONL + same `question_lookup` + same `record.answer` →
  identical chain/generation-span `attributes` dicts across runs and hosts (the lookup is a
  positional `Mapping` access keyed by `question_id`; the answer is a direct field read).
- **NFR-7 Convention correctness (sprint "convention drift" risk).** The keys written are
  exactly `input.value` + `input.mime_type` (chain span) and `output.value` +
  `output.mime_type` (generation span) — the minimal OpenInference convention that makes the
  Info tab render. `mime_type` is `"text/plain"` for both (plain question string, plain
  answer string). The richer `llm.input_messages`/`llm.output_messages` format is **not**
  used (Won't — no visible benefit for plain strings).

## Acceptance Criteria

Each AC is checkable by a unit test in `tests/observability/test_exporter.py` (or
`tests/observability/test_cli.py`); FR-10/NFR-1 are checkable by a source/import assertion.
All use a fake in-memory lookup — no HF, no `load_questions()`, no Phoenix, no network.

- **AC-1 Default = today + answer only (no question key).** Calling `replay_jsonl(path, sink,
project=...)` **without** `question_lookup` (default `None`) produces chain-span attributes
  with **no** `input.value` / `input.mime_type` key, and generation-span attributes that
  **do** carry `output.value == record.answer` + `output.mime_type == "text/plain"` (answer
  always-on) and are otherwise byte-identical to the pre-change output. (Asserts the chosen
  fork RQ-1: answer always-on, question only under the flag.)
- **AC-2 Question hydration with a fake lookup.** Given a record with
  `question_id = "qst_0001"` and `question_lookup = {"qst_0001": "What is X?"}`,
  `replay_jsonl(..., question_lookup=...)` yields chain-span attributes where
  `input.value == "What is X?"` and `input.mime_type == "text/plain"`, while the existing
  chain keys (`question_id`, `category`, …) remain present and unchanged. No HF/file I/O occurs.
- **AC-3 Answer hydration is always-on (no lookup needed).** Even **without** `question_lookup`
  (default call), the generation-span attributes contain `output.value == record.answer` and
  `output.mime_type == "text/plain"`, while the existing generation keys
  (`gen_ai.request.model`, token counts, `latency_s`, …) remain unchanged. (Distinct from
  AC-2: the answer rides the default path; the question does not.)
- **AC-4 Missing-question-id → omit + warn (no crash).** Given a record with
  `question_id = "qst_missing"` and `question_lookup = {"qst_0001": "..."}`, the run
  completes without raising; the chain-span attributes contain **no** `input.value` /
  `input.mime_type` key, and a `logging.warning` naming `"qst_missing"` is logged (assert via
  `caplog`). (Answer hydration, which needs no lookup, is unaffected — `output.value` is
  still written for that record.)
- **AC-5 `attributes.py` purity + unchanged signature.** `build_span_attrs` keeps the
  signature `build_span_attrs(record: EvalRecord)` (assert via `inspect.signature` — one
  positional param, no `question_lookup`), and `observability.attributes` imports nothing
  from `eval.questions`, `datasets`, `ingest`, `retrieval`, `phoenix`, or
  `opentelemetry`/`otel` (assert by scanning module imports / `inspect.getsource`). The mapper
  **does** emit `output.value`/`output.mime_type` from `record.answer` (always-on, in-record),
  but **not** `input.value` — the question is boundary-only. (Purity = imports unchanged, not
  key count.)
- **AC-6 Offline guarantee — no HF / no Phoenix.** The full enrichment test path runs with a
  fake in-memory `question_lookup` and a no-op/fake sink: `load_questions()` is **not**
  called, no HF dataset is streamed, no Phoenix endpoint is contacted, no network access
  occurs.
- **AC-7 CLI flag wires the gold map.** `rag-export-traces --enrich-from-questions` (not
  dry-run) triggers a single `load_questions(revision=...)` →
  `{q.question_id: q.question}` build before replay (assert via a patched `load_questions` /
  call-count, no real HF needed); **without** the flag, `load_questions` is **not** called.
  `rag-export-traces --help` exits 0 and lists `--enrich-from-questions` (and, if FR-8 is in,
  `--questions-revision`).
- **AC-8 Dry-run skips the gold load.** `rag-export-traces --enrich-from-questions --dry-run`
  parses successfully and does **not** call `load_questions()` (assert via patched
  `load_questions` call-count == 0) — mirroring the Phase 16 dry-run corpus-skip guard.

## Resolved Open Questions

RQ-1 was the one genuine product fork; it is now **confirmed by the orchestrator + user
(2026-06-02)**. RQ-2–RQ-5 mirror Phase 16 precedent and are low-risk.

- **RQ-1 The fork — one opt-in flag vs answer-always-on. CONFIRMED: answer always-on,
  question opt-in (BRAINSTORM Approach C).** The answer's `output.value` is set in the pure
  mapper for every export; the question's `input.value` is gated behind
  `--enrich-from-questions` at the boundary. Rationale (orchestrator + user): the mapper
  already emits **every** in-record `EvalRecord` field unconditionally, so `record.answer` —
  an in-record `str`, zero external I/O — belongs in that always-on set; gating it would make
  it the sole conditional in-record field, and a flag named `--enrich-from-questions` that
  also toggled the answer is a semantics smell. The opt-in discipline governs **external
  reads** (the gold question load), whose purpose is "no surprise I/O on the default path" —
  satisfied here because only the question is gated. The default export gains exactly one
  key (the answer `output.value`) over the pre-Phase-17 output. Encoded as FR-1/FR-4 +
  AC-1/AC-3.
- **RQ-2 Dry-run behavior (Q2).** **Resolved: `--enrich-from-questions --dry-run` skips the
  gold load** (no HF hit on dry-run), mirroring Phase 16's `--enrich-from-index --dry-run`
  corpus-skip (`cli.py:116`). Encoded as FR-7 + AC-8. Low-risk; matches established precedent.
- **RQ-3 `mime_type` placement (Q3).** **Resolved: the exporter sets `input.value` +
  `input.mime_type` together (chain) and `output.value` + `output.mime_type` together
  (generation) at the boundary.** The pure mapper does **not** pre-set lone placeholder keys
  it does not fill. Encoded as FR-4/FR-5. Low-risk.
- **RQ-4 In-place mutation vs new overload (Q4).** **Resolved: `exporter.py` mutates
  `span_attrs["chain"]` (and writes the generation `output.value`) in place after
  `build_span_attrs` returns — no new `build_span_attrs` overload.** Keeps one enrichment
  shape in `exporter.py`, identical to the Phase 16 `doc_lookup` post-process. Encoded as
  FR-9. Low-risk.
- **RQ-5 Flag naming (Q1) — `--enrich-from-questions` vs umbrella `--enrich-from-gold`.**
  **Resolved: `--enrich-from-questions`** (parallels the existing `--enrich-from-index`,
  preserves independent control of each enrichment, and does not change the Phase 16 UX). The
  umbrella `--enrich-from-gold` (Could) is deferred — it would make the two enrichments
  inseparable and re-flavor the Phase 16 flag. Encoded as FR-1. Confirm alongside RQ-1 if the
  orchestrator has a naming preference.

**No ADR for this phase.** The coupling is a stdlib `Mapping[str, str]` passed at the
boundary — the sprint "ADR only if non-trivial" bar is not met (same call as Phase 16 OQ-5).

## Infrastructure Readiness

| Dependency                                                                                       | Type     | KB domain                                    | Specialist   | Status                                                                                                                                                |
| ------------------------------------------------------------------------------------------------ | -------- | -------------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `observability/attributes.py` (`build_span_attrs`, chain + generation attr dicts)                | module   | observability (`span-attribute-mapping`)     | —            | Ready — signature + chain/generation key sets confirmed (`attributes.py:11,19-27,45-52`); **no change** (purity, FR-10)                               |
| `observability/exporter.py` (`replay_jsonl`, `build_span_attrs(record)` call site line 82)       | module   | observability (`dashboard-phoenix-boundary`) | —            | Ready — gains `question_lookup` kw-param + chain/generation boundary enrich; the Phase 16 `doc_lookup` mutation site is the template                  |
| `observability/cli.py` (`rag-export-traces` parser, `_build_parser`, gold map build)             | module   | observability                                | —            | Ready — append `--enrich-from-questions` (+ Should `--questions-revision`) alongside `--enrich-from-index`; dry-run guard at line 116 is the template |
| `eval/questions.py::load_questions` + `Question.question` / `.question_id`                       | module   | rag-eval (`eval-record-schema`)              | —            | Ready — `load_questions(revision=...) -> Iterator[Question]`; gold join keyed on `question_id` confirmed (`questions.py:60-96`); read-only            |
| `eval/records.py::EvalRecord.answer` (`str`), `.question_id` (`str`)                             | module   | rag-eval (`eval-record-schema`)              | —            | Ready — `answer: str` at `records.py:87` (AnswerWithSources text); no deserialization, no schema change                                               |
| `ingest/config.py::DATASET_REVISION` (gold SHA pin)                                              | config   | rag-ingest                                   | —            | Ready — `--questions-revision` default; identical precedent in `triage_cli.py:47-50`, `classify_cli.py:47-49`                                         |
| OpenInference Info-tab keys (`input.value`/`input.mime_type`, `output.value`/`output.mime_type`) | research | observability (`span-attribute-mapping`)     | —            | Ready — confirmed via Context7 `/arize-ai/openinference` this session; no `--deep-research` needed                                                    |
| `tests/observability/` (`test_exporter.py`, `test_cli.py`, `__init__.py`)                        | tests    | —                                            | —            | Ready — existing package; enrichment/CLI/dry-run tests mirror here (no flat test file)                                                                |
| `/update-kb observability` (refresh `span-attribute-mapping` + `span-tree-shape`)                | KB       | observability                                | kb-architect | **Correctly deferred (not a Phase-17 gap)** — Sprint-Wide Knowledge Plan lands it **after** this impl                                                 |

**No new KB, agent, command, or `--deep-research` needed for this phase.** Every dependency
maps to an existing module/config + an existing KB domain, and the entire enrichment shape is
a direct mirror of the shipped Phase 16 `--enrich-from-index` precedent
(`sprint-5/phase-16-phoenix-enrichment`). The post-impl `/update-kb observability` refresh is
**deliberately deferred** per the Sprint-Wide Knowledge Plan — so the absence of an
"`input.value`/`output.value` activated" KB note today is expected, not a readiness gap.

## Out of Scope (Won't — Phase 17)

- **Generation span `input.value` (the assembled prompt)** — not persisted in `EvalRecord`;
  requires an `EvalRecord` schema change + a re-run (Phase 18 ADR-0010 / Phase 19 hydration).
- **Judge span `output.value` (verdict reasoning, `per_fact`/`per_citation`)** — deliberately
  excluded from `EvalRecord` by ADR-0007 (`eval-record-schema`); persisting it is the Phase 18
  decision, hydrating it the Phase 19 re-run.
- **Any `EvalRecord` schema change** — this phase consumes only already-published artifacts
  (results JSONL + gold).
- **Any eval re-run / retrieval run / classify / triage re-run** — sprint no-re-runs guard;
  the costly re-run is quarantined to Phase 19.
- **Bronze / raw-payload capture** — a Phase 18 decision
  (`docs/planning/sprint-6-raw-payload-note.md`); Phase 17 is decoupled from it (uses the gold
  join + `record.answer` regardless of bronze).
- **`llm.input_messages` / `llm.output_messages` richer format** — `input.value` +
  `output.value` is the minimal convention that makes the Info tab render; the messages format
  adds no visible benefit for a plain question string and a plain answer string (NFR-7).
- **Answer serialized as JSON (full `AnswerWithSources` object)** — `record.answer` is already
  a `str`; citations are already on `record.sources`; the plain string is more readable in
  Phoenix.
- **A single `--enrich-from-gold` umbrella flag** (Could) — deferred; would make the two
  enrichments inseparable and re-flavor the Phase 16 `--enrich-from-index` UX (RQ-5).
- **A `QuestionLookup` Protocol or any added abstraction** — a stdlib `Mapping[str, str]` is
  sufficient (same call as Phase 16; no Protocol).
- **A signature/parameter change to `build_span_attrs`** — the mapper stays pure; enrichment
  is a boundary mutation in `exporter.py` (FR-9/FR-10).
- **An ADR for this phase** — the coupling is a trivial boundary `Mapping` (RQ-1 note; same as
  Phase 16 OQ-5).

## Clarity Score

| Dimension        | Score          | Note                                                                                                                                                                                                                                |
| ---------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem          | 3              | Root cause + evidence: `input.value`/`output.value` unset → Info tab empty (Context7-confirmed); `record.answer` at `records.py:87`, question via `load_questions` (`questions.py:60`); the Phase 16 mutation site is the template. |
| Users            | 3              | Named roles with workflow impact: maintainer debugging in Phoenix (primary), repo reviewer, the pure mapper as constraint, upstream gold source, phases 18/19, post-impl KB.                                                        |
| Success          | 3              | 8 falsifiable, unit-testable ACs: byte-identical default (chosen fork), question hydration, answer hydration, missing-id omit+warn, purity/unchanged-signature, offline no-HF/no-Phoenix, CLI wiring, dry-run skip.                 |
| Scope            | 3              | MoSCoW inherited from BRAINSTORM with an explicit Won't list; the 5 open questions all resolved (RQ-1 the genuine fork, RQ-2–RQ-5 mirror Phase 16).                                                                                 |
| Constraints      | 3              | All named: `attributes.py` purity (no new import / unchanged signature), opt-in/default-off/read-only, no-re-run, boundary-only heavy read, offline test path, determinism, convention correctness (NFR-7).                         |
| **Total: 15/15** | **PASS (≥12)** | RQ-1 (the answer-always-on vs all-opt-in fork) is **confirmed** by orchestrator + user; the remaining open questions mirror Phase 16. No unconfirmed assumptions remain.                                                            |

## Next Step

→ `/design sprint-6/phase-17-qa-legibility`
