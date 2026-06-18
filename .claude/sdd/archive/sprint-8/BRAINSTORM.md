# BRAINSTORM: sprint-8/phase-3-trace-surfacing — Per-Fact Root-Cause on the Judge Span

**Sprint/Phase:** sprint-8/phase-3-trace-surfacing | **Date:** 2026-06-17

---

## Problem Statement

Phases 1–2 produced per-fact root-cause labels (`retrieval_gap`/`generation_gap`) in the
eval report and failure taxonomy. Phase 3 makes those labels visible inside a failed trace
in Phoenix so that a single failed trace is self-explanatory — no cross-referencing the
aggregate report required. SC-4: "A failed trace in Phoenix shows, per fact, the doc it
was judged against."

---

## Suggested Research & KB Work

Coverage for the two relevant domains is **sufficient**:

- `observability/concepts/span-attribute-mapping.md` — full judge-span attribute table,
  `output.value` format, cost-omit/None discipline, and the "Offline Score Annotations"
  section are all current and accurate.
- `observability/patterns/manual-span-instrumentation.md` — tool-swap seam and
  exporter-boundary enrichment pattern are current.
- `rag-eval` KB — `root_cause.py` (phase-2) is not yet KB-documented but the code is
  small and directly readable.

One **deferred KB action** is already tracked in `SPRINT.md`: after phase 3 lands, run
`/update-kb observability` on-branch to update `span-attribute-mapping.md` with whatever
the judge-span `output.value` format becomes. This is a post-phase task, not a blocker.

No `/new-kb`, no `--deep-research`.

---

## The Sharp Design Tensions — Resolved from Code

**Tension 1 — mapper purity.** `attributes.py`'s NFR: no phoenix/otel imports; stays
import-light. Importing `eval/root_cause.py` is safe (`root_cause.py` is a pure leaf:
`eval.schema` + `eval.records` only). Importing it in `attributes.py` is acceptable
and keeps everything inside the pure mapper.

**Tension 2 — annotation model mismatch.** The existing score-annotation path
(`build_score_rows` → `sink.log_scores`) emits one `{span_id, score, label}` row per
metric per record. Per-fact annotations would require one row per fact, not one per
record. A record with 5 facts would emit 5 annotation rows for the same judge span,
which means 5 rows with the same `span_id` and metric name `root_cause` but different
labels — this is unusual/unsupported by the current `log_scores` shape and Phoenix's
annotation model treats a metric as a single scalar per span, not a list. Adding a
record-level rollup annotation (`retrieval_gap_count`/`generation_gap_count`) is
feasible, but a count does not satisfy SC-4 ("shows, per fact, the doc it was judged
against") on its own.

**Tension 3 — free-text vs structured attributes.** Enriching the existing
`output.value` text block is the lowest-friction path (one changed line in
`attributes.py`; no new attribute keys; no exporter change). Structured per-fact
attributes (`eval.fact.{i}.supporting_doc_id`, etc.) are queryable but have no
established OpenInference key and add verbosity proportional to fact count (no upside in
Phoenix's current filtering model for free-form custom keys).

---

## Approaches Considered

| #     | Approach                                                                                                                                                                                                                                                                                                              | Pros                                                                                                                                                                                                                        | Cons                                                                                                                                                                                                                                                                                                           | Effort |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **A** | Enrich the existing `output.value` text lines on the judge span. For each fact line, append `[doc: <id or —>` and optionally `\| <root_cause label>]`. `attributes.py` imports `classify_fact_gap` from `root_cause.py` (pure leaf). Zero new attribute keys, zero exporter change, zero annotation machinery change. | Smallest diff; respects mapper purity; reuses existing KB-documented attribute; human-readable in Phoenix Info tab; covers SC-4 ("shows, per fact, the doc"); no new keys to KB-document beyond updating the format string. | Free-text — not filterable/queryable in Phoenix by doc or gap label; the `output.value` field is already shared with citation lines, so the format must be backward-compatible (tests change).                                                                                                                 | XS     |
| **B** | Structured span attributes: one `eval.fact.{i}.supporting_doc_id` and `eval.fact.{i}.root_cause` attribute per fact. Pure mapper emits them; KB is updated with new keys.                                                                                                                                             | Queryable/filterable per-attribute; follows `retrieval.documents.{i}.*` precedent.                                                                                                                                          | No established OpenInference key for per-fact eval detail — purely custom; verbosity proportional to fact count (5 facts = 10 new keys per trace); Phoenix's attribute tab is flat, not grouped, so readability is no better than `output.value`; zero filtering benefit in practice for this harness's scale. | S      |
| **C** | Hybrid A + record-level rollup annotation. Enrich `output.value` (Approach A) AND add two score annotations on the judge span (`retrieval_gap_count`, `generation_gap_count`) from `rollup(record)` via `build_score_rows`.                                                                                           | Legibility (A) + coarse filterability (annotation scores are numeric).                                                                                                                                                      | Two separate mechanisms for related data; `rollup()` is a count not per-fact; the annotation model is already well-used — adding two more named metrics (`retrieval_gap_count`, `generation_gap_count`) is fine, but SC-4 is already met by A alone; the rollup counts are already in the report.              | S      |

---

## Recommended Approach — **A** (enrich `output.value` with `supporting_doc_id` and root-cause label)

1. **SC-4 is specifically "per fact, the doc it was judged against."** That is human
   reading a trace. `output.value` is exactly the Phoenix Info tab field a human reads
   on a failed trace. Approach A satisfies SC-4 directly.
2. **Scope discipline.** The sprint brief says phase 3 is "the thinnest" and is "cut
   first if the budget runs tight." Approach A is the XS change that satisfies the
   stated SC and no more. B and C add complexity that the SC does not require.
3. **Mapper purity is preserved.** `classify_fact_gap` is a pure leaf — importing it in
   `attributes.py` adds no coupling beyond what already exists for `EvalRecord`/`FactVerdict`.
4. **No new attribute keys.** `output.value` is already KB-documented; the only required
   KB update is a format-string change to the documented example — not a structural
   mapping change. This minimises the post-phase `/update-kb observability` scope.
5. **Annotation machinery is unchanged.** `build_score_rows` and the exporter loop stay
   untouched, keeping the blast radius to `attributes.py` and its tests.

The root-cause label in the text line is a **Should** (adds `retrieval_gap` /
`generation_gap` after the doc id) not a **Must** — SC-4 only asks for the doc id per
fact. Including it costs one function call per fact and adds meaningful context at no
architectural cost, so it is kept as Should with an explicit cut line.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                                                                                                                                  |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | In `attributes.py`, extend each fact line in `output.value` from `fact: <text> -> <verdict>` to `fact: <text> -> <verdict> [doc: <supporting_doc_id or "—">]`. Preserves existing format prefix; all existing test assertions still match after extending.                            |
| **Must**   | Null discipline: when `fv.supporting_doc_id is None`, render `"—"` (not empty string, not the word "None"). When `record.per_fact is None`, the entire `output.value` block is already omitted — no change needed.                                                                    |
| **Must**   | `tests/observability/test_attributes.py`: update existing fixtures to expect the new format; add a case with a failed fact carrying a `supporting_doc_id` and a case with `supporting_doc_id=None` to assert the `"—"` sentinel.                                                      |
| **Must**   | `make lint test` green; no exporter changes; no new attribute keys.                                                                                                                                                                                                                   |
| **Should** | Append root-cause label to each failed fact's line: `[doc: <id or "—"> \| retrieval_gap]` / `[doc: <id> \| generation_gap]`. For present facts (verdict == "present"), omit the root-cause suffix (not a failure). Requires one `classify_fact_gap` call per fact in `attributes.py`. |
| **Could**  | Record-level rollup annotation (`retrieval_gap_count`, `generation_gap_count`) added via `build_score_rows` pointing at the judge span — gives coarse filterability on top of legibility.                                                                                             |
| **Won't**  | Structured per-fact span attributes (`eval.fact.{i}.supporting_doc_id`, etc.) — zero filtering benefit at this scale; no established OpenInference key.                                                                                                                               |
| **Won't**  | Any change to the annotation model for per-fact grain (one annotation row per fact) — the model expects one scalar per metric per span; fighting it is out of scope.                                                                                                                  |
| **Won't**  | New span, new span kind, or any change to the span-tree shape.                                                                                                                                                                                                                        |
| **Won't**  | Any change to `exporter.py`'s main replay loop.                                                                                                                                                                                                                                       |

---

## Open Questions

1. **Format for the `"—"` sentinel.** The KB currently documents `output.value` as plain
   `"fact: <text> -> <verdict>"`. The "—" (em dash) is readable but the separator char
   and bracket style (`[doc: ...]`) need to be locked for the DESIGN so tests are written
   once. Alternative: `(doc: -)` or just append `| —` with no brackets. Which format
   reads best in Phoenix's Info tab (monospace text block)?

2. **Should the root-cause label suffix be gated on `verdict in FAILED_VERDICTS` only?**
   For `verdict == "present"` there is no gap, so the suffix is meaningless (`classify_fact_gap`
   returns `None`). The design must decide: (a) omit the suffix entirely for present facts
   (clean but asymmetric lines), or (b) emit `[doc: <id> | present]` for uniformity. The
   choice affects the test fixtures and the KB example.

3. **Is the root-cause suffix a Must or Should?** SC-4 says "shows, per fact, the doc it
   was judged against" — the doc id alone satisfies it. The root-cause label (`retrieval_gap`/
   `generation_gap`) is the phase-2 artifact surfaced onto the trace, which is the spirit of
   the sprint. Confirming the priority prevents scope creep into the budget-tight phase.

4. **KB update scope.** The post-phase `/update-kb observability` only needs to update the
   format string in `span-attribute-mapping.md` (judge-span `output.value` example). Confirm
   no other KB section references the old format (e.g., `concepts/span-tree-shape.md`).

---

## Next Step

→ `/define sprint-8/phase-3-trace-surfacing`
