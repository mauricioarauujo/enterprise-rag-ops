# DESIGN: sprint-6/phase-17-qa-legibility — Question + Answer Legibility (No Re-run)

**Sprint/Phase:** sprint-6/phase-17-qa-legibility | **Date:** 2026-06-02

## Architecture

Phase 17 makes a failed Phoenix trace self-explanatory by lighting up the two
OpenInference **Info-tab** keys that are unset today: `output.value` on the generation
span (the generated answer) and `input.value` on the chain root span (the question text).
It is a direct mirror of the shipped Phase 16 `--enrich-from-index` precedent — same three
modules, same boundary-mutation shape — split by **data origin**:

- **Answer = in-record, zero I/O → always-on in the pure mapper.** `record.answer` is
  already a `str` field on the `EvalRecord` parameter (`records.py:87`). The pure mapper
  `build_span_attrs` emits it as `output.value`/`output.mime_type` on the generation attrs,
  unconditionally, like every other in-record field it already maps. No import, no signature
  change → purity (FR-10/NFR-1) preserved.
- **Question = external gold read → opt-in at the boundary.** The question text is **not**
  on `EvalRecord`; it is joined from gold via `load_questions()` keyed by `question_id`.
  That external read lives at the CLI boundary under `--enrich-from-questions`: `cli.py`
  builds a `{question_id: question_text}` `Mapping` once, `exporter.py` consumes it and
  mutates `span_attrs["chain"]["input.value"]` in place — exactly as the Phase 16
  `doc_lookup` path mutates `span_attrs["retriever"]`.

### Data flow

```
rag-export-traces [--enrich-from-questions] [--questions-revision SHA]
        │
        ▼
cli.main ─ if enrich_from_questions and not dry_run:
        │     question_lookup = {q.question_id: q.question
        │                        for q in load_questions(revision=args.questions_revision)}
        │   else: question_lookup = None
        ▼
replay_jsonl(path, sink, *, project, dry_run, doc_lookup, question_lookup)
        │   per record:
        │     span_attrs = build_span_attrs(record)      # generation.output.value ALWAYS set
        │     if doc_lookup    is not None: mutate span_attrs["retriever"]   # Phase 16
        │     if question_lookup is not None: mutate span_attrs["chain"]["input.value"]  # Phase 17
        ▼
sink.start_span(chain) → Phoenix Info tab renders input.value (question) + output.value (answer)
```

The pure mapper (`attributes.py`) never learns about gold; the external read is confined to
`cli.py`; `exporter.py` consumes a plain `collections.abc.Mapping[str, str]` (already
imported at line 4). No new abstraction, no `Protocol`, no `EvalRecord` schema change, no
re-run, no ADR (the coupling is a stdlib `Mapping` — same bar as Phase 16 OQ-5).

## File Manifest

| File                                                 | Change                                                                                                                                                                                                                                                                                                                  | Owner (agent / direct) | Phase order |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ----------- |
| `src/enterprise_rag_ops/observability/attributes.py` | In `build_span_attrs`, add `gen_attrs["output.value"] = record.answer` and `gen_attrs["output.mime_type"] = "text/plain"` (always-on, together). No import, no signature change.                                                                                                                                        | direct                 | 1           |
| `src/enterprise_rag_ops/observability/exporter.py`   | Add kw-only `question_lookup: Mapping[str, str] \| None = None` to `replay_jsonl`; in the per-record loop, after `build_span_attrs(record)` and before the chain span opens, mutate `span_attrs["chain"]` in place (set `input.value`/`input.mime_type` if id present; else omit + `logger.warning`). Update docstring. | direct                 | 2           |
| `src/enterprise_rag_ops/observability/cli.py`        | Add `--enrich-from-questions` (`store_true`) and `--questions-revision` (default `config.DATASET_REVISION`) to `_build_parser`; in `main`, build `question_lookup` only when `args.enrich_from_questions and not args.dry_run`, pass to `replay_jsonl`. Add imports `load_questions`, `config`.                         | direct                 | 3           |
| `tests/observability/test_exporter.py`               | Append Phase 17 AC tests (AC-1..AC-6, AC-8 enrichment/dry-run) mirroring the Phase 16 block; add `_chain_attrs`/`_generation_attrs` helpers.                                                                                                                                                                            | direct                 | 4           |
| `tests/observability/test_cli.py`                    | CLI-wiring AC tests (AC-7, AC-8 CLI dry-run): patched `load_questions`, `--help` lists flag. New file (mirror `tests/observability/` package; `__init__.py` already present). May instead extend the CLI tests already living in `test_exporter.py` — see Risks.                                                        | direct                 | 4           |

No specialist agent owns `observability/` (the Infrastructure Readiness table lists `—`
for every dependency); all changes are `direct`, consistent with the Phase 16 ship.

## Implementation Phases

Ordered lowest-risk-first; each source touch lands with its mirrored test in the same pass.
(The standard schema/config/core/eval/observability/tests order collapses here: there is no
data-schema or eval change; all three touched modules are `observability/`, ordered
mapper → exporter → CLI by dependency direction — the CLI depends on the exporter param,
which is independent of the mapper.)

1. **Pure mapper (answer, always-on)** — `attributes.py`. In the generation attrs block
   (`gen_attrs`, currently `attributes.py:45-55`), add the two keys together, before the
   `cost_usd` conditional or right after the dict literal:

   ```python
   gen_attrs["output.value"] = record.answer
   gen_attrs["output.mime_type"] = "text/plain"
   ```

   Do **not** touch `chain_attrs` (question is boundary-only). No new import; `record` is
   already the parameter. Signature stays `build_span_attrs(record: EvalRecord)`.
   Satisfies FR-4, FR-10, NFR-1, NFR-7; checkable by AC-3, AC-5.

2. **Exporter (question param + boundary mutation)** — `exporter.py`. Add the kw-only param
   to the `replay_jsonl` signature (after `doc_lookup`):

   ```python
   question_lookup: Mapping[str, str] | None = None,
   ```

   In the per-record loop, after `span_attrs = build_span_attrs(record)` (line 82) and the
   existing `doc_lookup` block, **before** the chain span opens (line 99), mirror the Phase 16
   block exactly:

   ```python
   if question_lookup is not None:
       if record.question_id in question_lookup:
           span_attrs["chain"]["input.value"] = question_lookup[record.question_id]
           span_attrs["chain"]["input.mime_type"] = "text/plain"
       else:
           logger.warning(
               "question_id %r not found in question map; omitting input.value on chain span",
               record.question_id,
           )
   ```

   Update the docstring `Args:` to document `question_lookup`. `Mapping` is already imported
   (line 4) — no new HF/Phoenix import. Satisfies FR-3, FR-5, FR-6, FR-9, NFR-4, NFR-6;
   checkable by AC-1, AC-2, AC-4, AC-6.

3. **CLI wiring (opt-in flag + revision pin)** — `cli.py`. In `_build_parser`, append after
   `--corpus`:

   ```python
   parser.add_argument(
       "--enrich-from-questions",
       action="store_true",
       help="Hydrate input.value on chain spans with the gold question text from load_questions (opt-in; default off).",
   )
   parser.add_argument(
       "--questions-revision",
       default=config.DATASET_REVISION,
       help=f"Dataset revision SHA for the gold question map (default: {config.DATASET_REVISION}).",
   )
   ```

   Add imports at the top, mirroring the existing `read_corpus` / `CORPUS_PATH` shape:

   ```python
   from enterprise_rag_ops.eval.questions import load_questions
   from enterprise_rag_ops.ingest import config
   ```

   In `main`, after the `doc_lookup` block (line 117), build the question map under the same
   guard shape (`... and not args.dry_run`):

   ```python
   question_lookup = None
   if args.enrich_from_questions and not args.dry_run:
       question_lookup = {
           q.question_id: q.question
           for q in load_questions(revision=args.questions_revision)
       }
   ```

   Pass `question_lookup=question_lookup` into the `replay_jsonl(...)` call. Satisfies FR-1,
   FR-2, FR-7, FR-8, NFR-2, NFR-4; checkable by AC-7, AC-8.

4. **Tests (8 ACs, offline)** — mirror the Phase 16 block in `test_exporter.py:389-597`.
   Add two helpers next to `_retriever_attrs`:

   ```python
   def _chain_attrs(sink): ...        # first span where openinference_span_kind == "chain"
   def _generation_attrs(sink): ...   # first span where name == "generation"
   ```

   Reuse the existing `_one_record_jsonl(...)` helper (its record already has
   `answer="Answer 1"` and `question_id="qst_0001"`). Test map:
   - **AC-1** default call (no `question_lookup`): `_chain_attrs` has **no** `input.value`/
     `input.mime_type`; `_generation_attrs["output.value"] == "Answer 1"` and
     `output.mime_type == "text/plain"`; existing generation keys unchanged.
   - **AC-2** `replay_jsonl(..., question_lookup={"qst_0001": "What is X?"})`:
     `_chain_attrs["input.value"] == "What is X?"`, `input.mime_type == "text/plain"`;
     `question_id`/`category` still present; no file I/O.
   - **AC-3** answer always-on without any lookup: `_generation_attrs["output.value"] ==
record.answer`; `gen_ai.request.model`, token counts, `latency_s` unchanged.
   - **AC-4** `caplog` (logger `enterprise_rag_ops.observability.exporter`,
     `logging.WARNING`): record `qst_missing` + `question_lookup={"qst_0001": "..."}` → no
     `input.value` on chain, `"qst_missing"` in `caplog.text`, no raise; `output.value` still
     written.
   - **AC-5** in **`test_exporter.py`** (extend the existing `test_ac5_*` or add a sibling):
     `inspect.signature(build_span_attrs).parameters == ["record"]`; import-line scan
     forbids `eval.questions`/`questions`, `datasets`, `ingest`, `retrieval`, `phoenix`,
     `opentelemetry`; assert `"output.value"` appears in `inspect.getsource(attrs_mod)` and
     `"input.value"` does **not** (question is boundary-only).
   - **AC-6** offline: fake `question_lookup` + `FakeScoreSink`; assert no gold file created,
     `input.value` came from the in-memory map.
   - **AC-7** (`test_cli.py`): patch `cli.load_questions` returning a fake `Question` iterable
     (`SimpleNamespace(question_id=..., question=...)`); `--enrich-from-questions` →
     `mock_replay.call_args[1]["question_lookup"] == {...}` and `load_questions` called once;
     without the flag → `load_questions` not called and `question_lookup is None`. Plus a
     `--help` test: exits 0, output lists `--enrich-from-questions`.
   - **AC-8** (`test_cli.py`): `--enrich-from-questions --dry-run` → patched `load_questions`
     call-count == 0.

5. **Quality pass** — `make lint test` (the real gate, also CI). Targeted first:
   `uv run pytest tests/observability/ -k "ac1 or ac2 or ac3 or ac4 or ac5 or ac6 or ac7 or ac8"`.

**Docs + ADR:** none. No ADR (DEFINE § Resolved Open Questions; coupling is a stdlib
`Mapping`). The `/update-kb observability` refresh (`span-attribute-mapping` +
`span-tree-shape` to record the now-live `input.value`/`output.value` keys) is **deferred by
design** to the Sprint-Wide Knowledge Plan, after impl — not a Phase-17 deliverable.

## Infrastructure Gaps

Deep three-layer check — **clean**, mirroring Phase 16. Every dependency maps to an existing
module and an existing KB concept; no new domain, concept, or specialist is needed.

| Gap Type           | Area | Detail                                                                                                                                                                                                                                                                                                                                                       | Recommendation                                       |
| ------------------ | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| Missing domain     | —    | All tech areas (Phoenix/OpenInference span attrs, gold join, argparse CLI) are covered by the existing `observability` and `rag-eval`/`rag-ingest` KB domains in `_index.yaml`.                                                                                                                                                                              | none                                                 |
| Missing concept    | —    | `observability` already carries `span-attribute-mapping` (conf 0.95), `span-tree-shape` (0.95), and pattern `dashboard-phoenix-boundary` — exactly the concepts this phase exercises. The `input.value`/`output.value` activation is a documentation _refresh_ (deferred post-impl per the Sprint-Wide Knowledge Plan), not a missing concept blocking impl. | `/update-kb observability` — **deferred, not a gap** |
| Missing specialist | —    | `observability/` has no owning specialist (`—` across the Infrastructure Readiness table); Phase 16 shipped `direct`. No new agent warranted for a 3-module mirror.                                                                                                                                                                                          | none                                                 |

- **Domain existence:** ✅ `observability` (path `observability/`, status draft) covers the
  exporter/mapper/Phoenix surface; `rag-eval` covers `load_questions`/`EvalRecord`;
  `rag-ingest` covers `DATASET_REVISION`. All three are registered.
- **Concept coverage:** ✅ `span-attribute-mapping` covers the OpenInference key conventions;
  `dashboard-phoenix-boundary` covers the opt-in boundary-enrichment pattern this reuses.
- **Agent alignment:** ✅ N/A — no specialist owns this area; `kb-architect` owns the
  (deferred) KB refresh, consistent with `_index.yaml` `agents: [kb-architect]`.

## Consistency Check

**Verdict: ✅ CONSISTENT.** Non-trivial phase (3 source modules + tests, DEFINE went through
a confirmed fork), full six-pass cross-check of DEFINE↔DESIGN against the constitution
(AGENTS.md § Engineering Behavior + § Conventions + § Testing, the `observability` KB domain,
the Phase 16 precedent). No CRITICAL/HIGH drift.

| ID  | Severity | Pass               | Location                    | Finding                                                                                                                                                                                                                                                     | Suggested fix                                                                                                                                                      |
| --- | -------- | ------------------ | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| C-1 | LOW      | Ambiguity          | Manifest rows 5 + AC-5/AC-7 | DEFINE/NFR-5 allows CLI-flag/dry-run tests in **either** `test_exporter.py` or `test_cli.py`. DESIGN picks `test_cli.py` for AC-7/AC-8-CLI and keeps AC-5 in `test_exporter.py` (where the purity scan already lives). Both honour the no-flat-test rule.   | Documented in Risks; either placement is acceptable — implementer may consolidate CLI tests into `test_exporter.py` if a new file feels heavyweight for two tests. |
| C-2 | LOW      | Underspecification | Step 1 (mapper edit site)   | DEFINE fixes the two keys but not the exact line within `gen_attrs`. DESIGN pins "together, after the dict literal / before the `cost_usd` conditional" — exact insertion is implementer's choice as long as both keys land on `gen_attrs` unconditionally. | None needed; constraint (both keys, always-on, no import) is unambiguous.                                                                                          |

- **Duplication:** none. FR-4 (mapper answer) and FR-5 (boundary question) are disjoint by
  data origin; no overlapping requirement.
- **Ambiguity:** only C-1 (test file placement, explicitly permitted by DEFINE). No vague
  descriptors; no unresolved `TODO`/placeholder (RQ-1..RQ-5 all marked resolved).
- **Underspecification:** only C-2 (cosmetic insertion point). Every FR maps to a concrete
  named site (`gen_attrs`, `replay_jsonl` loop, `_build_parser`/`main`); every AC names its
  assertion mechanism (helper, `caplog`, `inspect.signature`, patched `load_questions`).
- **Constitution alignment:** ✅ Minimal scope — exactly two Info-tab keys; no speculative
  feature, no `Protocol`/abstraction (DEFINE Out-of-Scope). The `question_lookup` param is a
  named, justified seam (mirrors the shipped `doc_lookup`), not "in case." No
  stranger-test/private-path leak. Conventions honoured: English, tests mirror `src/` into
  `tests/observability/` with `__init__.py` (no flat test file), Conventional Commits at
  commit time, cassette/replay N/A (no live LLM in this path — injected fake `Mapping`).
- **Coverage:** ✅ all 10 FR + 7 NFR map to ≥1 manifest entry/AC; all 8 AC map to a test in
  the manifest. Reverse check: no manifest entry references an undefined component
  (`load_questions`, `config.DATASET_REVISION`, `record.answer`, `record.question_id`,
  `Mapping` all confirmed in source this session).
- **Inconsistency:** none. Terminology is identical across DEFINE/DESIGN
  (`question_lookup`, `input.value`, `output.value`, `--enrich-from-questions`,
  `--questions-revision`); no conflicting directive against the Phase 16 precedent.

## Risks & Trade-offs

- **Test-file placement (C-1).** Two CLI tests (AC-7, AC-8-CLI) go in a **new**
  `tests/observability/test_cli.py`, while the existing CLI tests (`test_cli_endpoint_precedence`,
  `test_cli_dry_run`, `test_ac7_cli_*`) currently live in `test_exporter.py`. This splits CLI
  coverage across two files. _Mitigation / alternative:_ the implementer may instead append
  AC-7/AC-8-CLI to `test_exporter.py` alongside the Phase 16 `test_ac7_*` tests for locality.
  Either satisfies NFR-5 (no flat `tests/test_*.py`). Low risk — naming only.
- **Mapper now emits answer text on every export (AC-1 "byte-identical + one key").** A
  reviewer expecting the _exact_ prior default output will see one new generation key. This is
  the **confirmed** fork (RQ-1) and DEFINE states the default "gains exactly one key"; AC-1
  asserts it explicitly. Not a regression — by design.
- **`load_questions` hits HF on the live opt-in path.** Acceptable: gated behind
  `--enrich-from-questions and not dry_run` (FR-7), identical to `triage_cli` precedent. Tests
  never trigger it (patched / fake `Mapping`), so the suite stays offline (NFR-3, AC-6, AC-8).
- **No ADR.** Correct per DEFINE — a stdlib `Mapping` at the boundary is below the sprint
  "ADR only if non-trivial" bar (same as Phase 16 OQ-5). Flagging here only to confirm the
  decision was deliberate, not an omission.
- **KB stays stale until the deferred refresh.** The `input.value`/`output.value` activation
  won't appear in `span-attribute-mapping` until the post-impl `/update-kb observability`.
  Deferred by the Sprint-Wide Knowledge Plan — acceptable, not a gap.

## Next Step

→ `/implement sprint-6/phase-17-qa-legibility` — gaps are clean (none blocking). Per the
cross-tool **Implement Contract** (AGENTS.md), the implement stage runs in
**Antigravity / Gemini** against this `DESIGN.md` as the contract: confirm the branch
`sprint-6/phase-17-qa-legibility`, read this manifest + `DEFINE.md` (acceptance criteria) +
the `observability` KB (`span-attribute-mapping`, `dashboard-phoenix-boundary`), implement in
phase order (mapper → exporter → CLI → tests), then `make lint test`.
