# DESIGN: sprint-8/phase-3-trace-surfacing — Per-Fact Root-Cause on the Judge Span

**Sprint/Phase:** sprint-8/phase-3-trace-surfacing | **Date:** 2026-06-17

> Implement stage runs in **Antigravity / Gemini** against this artifact (AGENTS.md
> § Implement Contract). The manifest below is prescriptive enough to need no extra context.

---

## Architecture

This phase is a **single-site enrichment** of one pure mapper function. No new module,
no new seam, no schema/exporter/ADR change. The data already exists end to end after
phases 1–2; phase 3 only changes how the judge span's `output.value` free-text block is
rendered.

**Data flow (unchanged shape, enriched rendering):**

```
EvalRecord (per_fact: list[FactVerdict] | None, retrieval_ranked_ids: list[str])
   │
   ▼
build_span_attrs(record)            # observability/attributes.py — PURE mapper
   │   judge block: for each fv in record.per_fact:
   │       gap = classify_fact_gap(fv, record.retrieval_ranked_ids)   # eval/root_cause.py (pure leaf)
   │       doc_or_dash = fv.supporting_doc_id if fv.supporting_doc_id is not None else "—"
   │       line = f"fact: {fv.fact} -> {fv.verdict} [doc: {doc_or_dash}]"            (present, gap is None)
   │              f"fact: {fv.fact} -> {fv.verdict} [doc: {doc_or_dash} | {gap}]"    (failed, gap non-None)
   │   then citation lines (UNCHANGED), appended AFTER all fact lines
   ▼
judge_attrs["output.value"]         # only when lines is non-empty (existing guard preserved)
   │
   ▼
exporter.py boundary  →  Phoenix Info tab  (self-diagnosing trace, SC-4)
```

**Single change site:** the judge-span block of `observability/attributes.py`
(lines ~72–78). The `chain`, `retriever`, `generation` blocks, the citation-line
construction, the `if lines:` guard, the cost rule, and `build_score_rows` are all
untouched.

**Purity invariant (NFR-1 / FR-5).** `attributes.py` adds exactly one import —
`from enterprise_rag_ops.eval.root_cause import classify_fact_gap`. `root_cause.py` is a
pure leaf (imports only `eval.schema` + `eval.records`), so mapper purity is preserved:
still no `phoenix`, no `opentelemetry` import. `FAILED_VERDICTS` is **not** imported —
`classify_fact_gap` returns `None` for present facts and a non-None label exactly for
failed facts, so "gap is None" is the gating signal for whether to append the label.
This keeps the new import surface to a single symbol and avoids re-deriving the
failed-verdict set in the mapper.

---

## File Manifest

| File                                                          | Change                                                                                                                                                                                      | Owner (agent / direct) | Phase order           |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | --------------------- |
| `src/enterprise_rag_ops/observability/attributes.py`          | Modify — add `classify_fact_gap` import; replace the judge fact-line construction (lines ~72–78). Citation/rollup/guard/cost logic intact.                                                  | direct                 | 3 (core module logic) |
| `tests/observability/test_attributes.py`                      | Modify — update existing fact-line assertions to the new format; add 7 new offline cases (mapped to ACs below).                                                                             | direct                 | 6 (tests)             |
| `.claude/kb/observability/concepts/span-attribute-mapping.md` | Modify — refresh the Judge-Span `output.value` fenced example (lines ~85–98) to the bracket+pipe format. On-branch post-phase `/update-kb observability`, per repo KB-on-branch convention. | direct                 | 7 (docs / KB)         |

No specialist agent owns any of these — this is an observability-mapper change plus its
mirrored test plus an on-branch KB example refresh; all `direct`. The test package
`tests/observability/__init__.py` already exists (no new package dir to create).

---

## Implementation Phases

Ordered for the cross-tool (Antigravity / Gemini) executor — follow exactly. (Data
schema / config / eval-harness / observability-hook phases of the standard convention do
not apply here; this is core-logic + tests + KB.)

### Phase order step 1 — modify `src/enterprise_rag_ops/observability/attributes.py`

- Add the import alongside the existing `EvalRecord` import (after line 8):
  ```python
  from enterprise_rag_ops.eval.root_cause import classify_fact_gap
  ```
- Replace the current fact-line construction. **Current (lines 72–75):**
  ```python
  # Build verdict lines for hydration onto the judge span (FR-10, RQ-2)
  lines = [f"fact: {fv.fact} -> {fv.verdict}" for fv in (record.per_fact or [])] + [
      f"citation: {cv.doc_id} -> {cv.verdict}" for cv in (record.per_citation or [])
  ]
  ```
  **Replacement** (fact lines gain the `[doc: …]` bracket with an optional ` | <label>`
  for failed facts; citation lines and the `if lines:` guard unchanged):
  ```python
  # Build verdict lines for hydration onto the judge span (FR-10, RQ-2).
  # Each fact line carries its supporting_doc_id (or "—" sentinel); failed facts also
  # carry the phase-2 root-cause label from classify_fact_gap (sprint-8/phase-3, FR-1/2/3).
  fact_lines = []
  for fv in record.per_fact or []:
      doc_or_dash = fv.supporting_doc_id if fv.supporting_doc_id is not None else "—"
      gap = classify_fact_gap(fv, record.retrieval_ranked_ids)
      bracket = f"[doc: {doc_or_dash}]" if gap is None else f"[doc: {doc_or_dash} | {gap}]"
      fact_lines.append(f"fact: {fv.fact} -> {fv.verdict} {bracket}")
  lines = fact_lines + [
      f"citation: {cv.doc_id} -> {cv.verdict}" for cv in (record.per_citation or [])
  ]
  ```
- Leave everything else in the judge block (`if lines:` omit-guard, `output.mime_type`,
  the `cost_usd` rule) and all other span blocks exactly as-is.
- The `—` must render as the literal **U+2014 EM DASH** character (not a hyphen-minus
  `-`, not an en-dash `–`).

### Phase order step 2 — mirror tests in `tests/observability/test_attributes.py`

Update the existing present-case expected block and add the new cases (table below). All
offline over hand-built `EvalRecord`s — no network, no API key, no mocked LLM, no
cassette (the mapper makes no LLM call). Build records in the existing house style
(positional/keyword `EvalRecord(...)` like the current tests).

| Test name | AC | Load-bearing expected substring / line |
| -------------------------------------------------------------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_build_span_attrs_verdict_hydration_present` (update existing) | 2, 9 | Set `fact1` = `present`, `supporting_doc_id="d1"`; `fact2` = `absent`, `supporting_doc_id=None`; `retrieval_ranked_ids=["d1"]`. New `expected_value`: `"fact: fact1 -> present [doc: d1]\nfact: fact2 -> absent [doc: —                                                                                         | retrieval_gap]\ncitation: d1 -> supported\ncitation: d2 -> unsupported"`. Confirms fact prefix preserved, citation lines byte-for-byte unchanged and ordered AFTER all fact lines. |
| `test_fact_line_carries_supporting_doc_id` (new) | 1 | Present fact, `supporting_doc_id="doc-12"`. Assert `"[doc: doc-12]"` ∈ `judge["output.value"]`. (SC-4 acceptance.) |
| `test_failed_fact_generation_gap_absent` (new) | 4 | `verdict="absent"`, `supporting_doc_id="doc-12"`, `retrieval_ranked_ids=["doc-12"]`. Assert line == `"fact: <text> -> absent [doc: doc-12                                                                                                                                                                       | generation_gap]"`. |
| `test_failed_fact_generation_gap_contradicted` (new) | 4 | `verdict="contradicted"`, `supporting_doc_id="doc-12"`, `retrieval_ranked_ids=["doc-12"]`. Assert `"[doc: doc-12                                                                                                                                                                                                | generation_gap]"` ∈ value (exercises both FAILED verdicts). |
| `test_failed_fact_retrieval_gap_none_doc` (new) | 5, 7 | `verdict="absent"`, `supporting_doc_id=None`, any `retrieval_ranked_ids`. Assert line == `"fact: <text> -> absent [doc: —                                                                                                                                                                                       | retrieval_gap]"`; assert `"None"`not in line and the doc token is the`—` (U+2014), not empty. (Assert the FULL line so an em-dash downgrade fails.) |
| `test_present_fact_has_doc_no_label` (new) | 3, 6 | Present fact, `supporting_doc_id="doc-9"`. Assert `"[doc: doc-9]"` present AND `"retrieval_gap"` not in line AND `"generation_gap"` not in line. |
| `test_label_matches_classify_fact_gap_predicate` (new) | 11 | Record whose facts span both labels: one `absent` with doc in ranked → generation_gap; one `contradicted` with `None` doc → retrieval_gap. For each `fv`, assert the rendered label on its line equals `classify_fact_gap(fv, record.retrieval_ranked_ids)`. Pins predicate reuse (no reimplemented gap logic). |
| `test_judge_attrs_key_set_unchanged` (new) | 12 | Record with facts + citations + known judge `cost_usd`. Assert `set(judge_attrs) == {"gen_ai.request.model", "gen_ai.system", "gen_ai.operation.name", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "latency_s", "output.value", "output.mime_type", "cost_usd"}`. No `eval.fact.*` key. |
| `test_attributes_module_has_no_phoenix_or_otel_import` (new) | 10 | Read the module source file and assert neither `"phoenix"` nor `"opentelemetry"` appears as an import. (Static substring check on the source file — offline, no import side effects.) |
| `test_build_span_attrs_verdict_hydration_both_none` (keep existing) | 8 | `per_fact=None`, `per_citation=None` → neither `output.value` nor `output.mime_type` in `judge_attrs`. |
| `test_build_span_attrs_verdict_hydration_both_empty` (keep existing) | 8 | `per_fact=[]`, `per_citation=[]` → same omission. |

### Phase order step 3 — gate

Run `make lint test` (the real gate, also CI). Validate smallest-first first if desired:
`uv run pytest -k attributes`, then `make lint test`. Must be green (NFR-5).

### Phase order step 4 — on-branch KB refresh

Run `/update-kb observability` (or hand-edit) to update the Judge-Span `output.value`
fenced example in `.claude/kb/observability/concepts/span-attribute-mapping.md`
(lines ~85–98) from the old three-line example to the new bracket+pipe format, e.g.:

```
fact: <fact text> -> <verdict> [doc: <supporting_doc_id or —>]
fact: <fact text> -> <verdict> [doc: <supporting_doc_id or —> | <retrieval_gap|generation_gap>]
citation: <doc_id> -> <verdict>
```

Also note in prose that the `[doc: …]` suffix is on every fact line (present + failed),
the `—` is the U+2014 None sentinel, and the ` | <label>` appears only on failed facts
(via `classify_fact_gap`). Do this AFTER code + tests land and the gate is green, per the
repo's KB-on-branch convention. Listed here so it isn't forgotten — it is not a blocker
for the code change.

---

## Edge cases to encode

- **Failed fact with `None` doc** → `[doc: — | retrieval_gap]` (FR-3/FR-2). Covered by
  `test_failed_fact_retrieval_gap_none_doc` (full-line assertion).
- **Em-dash literal.** The sentinel must be U+2014 (`—`), never a hyphen `-` or en-dash
  `–`. The full-line assertion in the retrieval-gap test catches a downgrade.
- **FR-5 guard interaction.** Phase-1's FR-5 collapses any out-of-set `supporting_doc_id`
  to `None` before persistence, so on a persisted record a non-None doc id is provably in
  `retrieval_ranked_ids`; `classify_fact_gap`'s defensive `doc_id not in
retrieval_ranked_ids` branch rarely fires in production. The label still derives
  correctly because the predicate is **reused verbatim** (not reimplemented) — no special
  handling in the mapper. Pinned by `test_label_matches_classify_fact_gap_predicate`.
- **Zero-lines case.** `per_fact` None/empty AND `per_citation` None/empty → `lines` is
  empty → `output.value` / `output.mime_type` omitted entirely (existing `if lines:`
  guard, unchanged). Covered by the two retained `both_none` / `both_empty` tests.
- **Present fact never gets a label.** `classify_fact_gap` returns `None` for present, so
  `gap is None` selects the no-label bracket; the doc suffix still appears (symmetric, A2).

---

## Infrastructure Gaps

Three-layer check (domain existence / concept coverage / agent alignment):

| Gap Type           | Area | Detail                                                                                                                                                                                                               | Recommendation |
| ------------------ | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| Missing domain     | —    | `observability` KB domain exists in `_index.yaml`; `rag-eval` exists for `root_cause.py`. Both sufficient.                                                                                                           | None           |
| Missing concept    | —    | `span-attribute-mapping.md` already documents the Judge-Span `output.value` block (concept covered); only the rendered **example string** goes stale — a refresh, handled by manifest item 3, not a missing concept. | None           |
| Missing specialist | —    | `attributes.py`, its test, and the KB doc are all `direct`-owned; `root_cause.py` already shipped (phase 2).                                                                                                         | None           |

**Zero infrastructure gaps.** No `/new-kb`, no `/update-kb` for a _missing_ concept
(only the existing-example refresh, already in the manifest), no `/new-agent`, no new
ADR. Confirms DEFINE § Infrastructure Readiness.

## Consistency Check

**Skipped — single-module phase.** Per the `/design` rules, the six-pass
DEFINE↔DESIGN / constitution cross-check runs for non-trivial phases (>2 modules). This
phase touches one production module (`attributes.py`) plus its mirrored test and an
on-branch KB example refresh; the change is additive, introduces no new seam, no
schema/exporter/ADR surface, and no constitution surface (AGENTS.md § Engineering
Behavior / § Conventions) is touched. No drift. The A1/A2 locked strings are used
verbatim in the test fixtures above.

## Risks & Trade-offs

- **Em-dash character integrity** (above) — the only real implementation hazard; mitigated
  by the full-line assertion.
- **No ADR warranted.** Additive change within ADR-0004's already-decided observability
  architecture (NFR-2); no design decision rises to an ADR. No new file under `docs/adr/`.
- **Diff containment** — the only production diff is `attributes.py`; `eval/schema.py`,
  `eval/records.py`, and `observability/exporter.py` have zero diff (AC-13). The executor
  must not touch them.

## Next Step

→ `/implement sprint-8/phase-3-trace-surfacing` — no gaps to address first; follow the
implementation phase order (modify `attributes.py` → mirror tests → `make lint test` →
on-branch KB refresh).
