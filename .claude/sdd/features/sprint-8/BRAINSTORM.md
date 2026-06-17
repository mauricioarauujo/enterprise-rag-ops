# BRAINSTORM: sprint-8/phase-2-root-cause-linkage — Per-Fact Root-Cause Attribution

**Sprint/Phase:** sprint-8/phase-2-root-cause-linkage | **Date:** 2026-06-15

---

## Problem Statement

Phase-1 added `supporting_doc_id: str | None` to `FactVerdict`, with a hallucination
guard that collapses any id not in the retrieved set to `None` before persistence.
Phase-2 must cross-reference this field against retrieval to attribute root cause for
failed facts, distinguish "retrieval gap" from "generation gap" in the report, and feed
that signal into the failure-mode taxonomy — **without** redesigning the taxonomy or the
report's data model.

Serves sprint success criteria:

- **SC-2** — the eval report distinguishes "fact failed, supporting doc WAS retrieved"
  from "fact failed, supporting doc was NEVER retrieved" for at least one worked category.
- **SC-3** — the failure-mode taxonomy can attribute a retrieval-miss root cause using the
  new field, not just answer-level aggregates.

---

## Suggested Research & KB Work

The `rag-eval` KB domain already covers `supporting_doc_id` (sprint-8/phase-1 entry), the
5-label taxonomy cascade, the report-render pattern, and the eval-record schema. The
`observability` KB covers ADR-0008 (taxonomy). Coverage is **sufficient** — no `/new-kb`,
`/update-kb`, or `--deep-research` is needed before `/define`. The planned post-phase KB
action is `/update-kb observability` (failure-taxonomy) **after** phase-2 lands.

---

## The Sharp Design Tension — Resolved from Code

**Question:** does the judge's retrieved-doc set equal the persisted
`retrieval_ranked_ids`? If so, cross-referencing a non-None `supporting_doc_id` against
the retrieved set is tautological (phase-1's FR-5 guard already guarantees membership).

**Verified from `runner.py` (lines ~281–315) and `openai_judge.py` (lines ~137–140):**

- Persisted `retrieval_ranked_ids = deduplicate_ranked_ids([cid for cid, _, _ in chunk_hits])`
  — deduped doc-level ids from `chunk_hits`.
- The judge's guard set `retrieved_ids = {c.doc_id for c in ctx_chunks}`, where
  `ctx_chunks = ContextAssembler(store).assemble(chunk_hits)` — same `chunk_hits` source.
- The two sets are **equivalent** in the happy path (same source, same doc-level dedup);
  `ContextAssembler` neither adds nor drops docs relative to `deduplicate_ranked_ids`.

**Consequence:** when phase-2 reads a record, `supporting_doc_id` is **either `None` or
already a member of `retrieval_ranked_ids`**. A naive set-intersection on non-None values
is provably tautological — a structural invariant of the FR-5 guard, not a coincidence.

**The real signal** — for any failed fact (`verdict ∈ {absent, contradicted}`):

- `supporting_doc_id is not None` → the evidence WAS retrieved, but the answer still got
  the fact wrong/missing → **generation gap** (generator had the doc, failed to use it).
- `supporting_doc_id is None` → no retrieved doc substantiates this fact → **retrieval
  gap** (evidence never reached the generator).

This None-vs-non-None framing on failed facts is the correct predicate — not a set
intersection.

**Honest caveat:** if a future change relaxes/removes the FR-5 guard, the invariant breaks
and a naive None-vs-non-None read becomes wrong. A defensive explicit cross-reference
(`supporting_doc_id in record.retrieval_ranked_ids`) costs ~nothing and makes the
assumption visible in code → kept as a **Should**.

---

## Approaches Considered

| #     | Approach                                                                                                                                                                                                                | Pros                                                                                                                                                | Cons                                                                                                                                                                                       | Effort |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| **A** | New pure module `eval/root_cause.py` with a `classify_fact_gap(...) -> "retrieval_gap" \| "generation_gap" \| None` predicate + a per-record `rollup(record)`; **both** `report.py` and `failure_taxonomy.py` import it | DRY — single definition of a named predicate; clean seam (two real consumers); defensive cross-reference lives in one place; one tiny tested module | One new file for what is essentially one boolean expression                                                                                                                                | S      |
| **B** | Inline the predicate in `report.py` and `failure_taxonomy.py` separately                                                                                                                                                | No new files                                                                                                                                        | Duplicates the core `supporting_doc_id is None and verdict ∈ {absent, contradicted}` logic across two modules; divergence risk; the predicate is a named concept, not an inline expression | S      |
| **C** | Inline in `report.py` only (satisfy SC-2); leave taxonomy untouched                                                                                                                                                     | Strictest minimal scope; zero taxonomy risk                                                                                                         | **SC-3 unmet** — taxonomy attribution is a stated success criterion                                                                                                                        | XS→S   |

---

## Recommended Approach — **A** (shared `eval/root_cause.py` predicate)

1. **SC-3 requires the taxonomy to change** — rules out C. B meets it but duplicates the
   predicate. A meets both without speculation.
2. **The predicate is a named concept, not an inline expression** — "a failed fact whose
   `supporting_doc_id is None` is a retrieval gap; non-None is a generation gap" is a
   reusable, testable invariant that belongs in one place.
3. **Two consumers confirm the seam** — `report.py` needs per-category counts;
   `failure_taxonomy.py` needs the same predicate. A pure function (no I/O) is trivially
   testable and imports nothing risky.
4. **Aligned with clean-structure / minimal-scope** — ~30 lines (one predicate, one
   rollup type). It refines two existing labels by adding a per-fact evidence check;
   it does **not** change the 5-label cascade, its order, or the StrEnum values.
5. **Defensive cross-reference is right** — makes the FR-5 invariant explicit and robust
   to a future guard removal at near-zero cost.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                                                                                                                                                               |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Must**   | `eval/root_cause.py`: `classify_fact_gap(fv, retrieval_ranked_ids) -> Literal["retrieval_gap","generation_gap"] \| None`. Returns `None` for `verdict == "present"` (not a failure); `"retrieval_gap"` when `supporting_doc_id is None` (or, defensively, not in `retrieval_ranked_ids`); else `"generation_gap"`. |
| **Must**   | `eval/root_cause.py`: a small `RootCauseRollup` (dataclass/TypedDict) with `{retrieval_gap, generation_gap, no_failed_facts}` counts + `rollup(record: EvalRecord) -> RootCauseRollup`. Degrades gracefully when `per_fact is None`.                                                                               |
| **Must**   | `report.py`: per-category root-cause counts (retrieval-gap vs generation-gap on failed facts) added to `generate_report_data` output and rendered in `render_markdown` + `render_html`. Satisfies **SC-2**.                                                                                                        |
| **Must**   | `failure_taxonomy.py`: refine an existing label (likely `is_retrieval_miss` / `is_incomplete`) to use per-fact supporting-doc evidence when `per_fact` is available. Satisfies **SC-3**. **No 6th label; no cascade-order change.**                                                                                |
| **Must**   | `tests/eval/test_root_cause.py`: predicate (present excluded; absent + contradicted; None vs non-None; defensive out-of-set), rollup (incl. `per_fact is None`), and the taxonomy refinement branches.                                                                                                             |
| **Should** | Defensive cross-reference `supporting_doc_id not in record.retrieval_ranked_ids` inside `classify_fact_gap` (guards against future FR-5 removal).                                                                                                                                                                  |
| **Should** | Docstring in `root_cause.py` explaining why None-vs-non-None is the signal, citing FR-5 as the invariant source.                                                                                                                                                                                                   |
| **Could**  | Refine `is_incomplete` too (distinguish "low recall, no evidence" vs "low recall, evidence available") — low confidence; defer unless cheap.                                                                                                                                                                       |
| **Could**  | Per-question root-cause drill-down in the report.                                                                                                                                                                                                                                                                  |
| **Won't**  | A 6th taxonomy label (→ ADR-0008 amendment; out of scope per sprint risk).                                                                                                                                                                                                                                         |
| **Won't**  | Phoenix span integration (phase-3 scope).                                                                                                                                                                                                                                                                          |
| **Won't**  | Change the cascade order / 5-label `StrEnum` values.                                                                                                                                                                                                                                                               |
| **Won't**  | Modify `aggregate.py` (phase brief excludes it).                                                                                                                                                                                                                                                                   |

---

## Resolved Open Questions

All three resolved with the user (2026-06-16) — decisions locked for `/define`.

1. **Report placement → DEDICATED SUB-SECTION (option 1b).** Root-cause counts render as
   a **separate "Root-Cause Attribution" section**, not extra columns on the already-wide
   (7-col) per-category table. `generate_report_data` gains a **new top-level key**
   (e.g. `"root_cause"`); `render_markdown`/`render_html` each gain one new table block.
   Rationale: keep the primary metrics table readable; give the diagnosis its own billing
   (it is the sprint deliverable). _Rejected: 1a (new columns) — inflates a 9-col table and
   mixes quality metrics with diagnosis._

2. **Taxonomy refinement → ORTHOGONAL PER-FACT ATTRIBUTION (option 2a).** The 5-label
   `classify()` cascade, its order, and the `StrEnum` values stay **untouched** — no record
   is reclassified. The taxonomy gains a **new, additive capability**: a per-fact root-cause
   attribution (`retrieval_gap` vs `generation_gap`) built on `eval/root_cause.py`,
   satisfying SC-3's literal wording ("the taxonomy _can attribute_ a retrieval-miss root
   cause using the new field, not just answer-level aggregates"). No ADR needed.
   **Rejected: 2c (redefine `is_retrieval_miss` to fire on the per-fact signal even on a
   gold-doc hit) — deliberately a Won't.** Cost analysis (2026-06-16): 2c delivers **zero**
   diagnostic information beyond 2a (the retrieval-gap/generation-gap breakdown is fully in
   the report either way); it is a _lossy_ projection of a per-fact distribution onto one
   per-record label, and it costs (a) an arbitrary aggregation threshold (all/any/≥X% failing
   facts → label) = a new policy knob, (b) a cascade ripple — `retrieval_miss` sits at
   position 2 and would steal records from `hallucination`/`incomplete`, re-partitioning the
   whole space = the redesign the sprint risk forbids, (c) broken comparability with the
   published Sprint-3 baseline distribution, (d) an ADR-0008 amendment, (e) test-fixture
   churn. The 5-label headline is _intentionally_ answer-level/coarse and the root-cause is
   _intentionally_ fact-level/fine (cf. KB `observability/aggregate-granularity-limit`);
   keeping them separate is the cleaner architecture even at zero cost. **2c is deferred,
   not killed** → harvest as a backlog item ("fact-level `failure_mode` / per-fact
   taxonomy") that triggers the ADR-0008 amendment _if and when_ the coarse label proves
   insufficient in practice (e.g. `rag-triage` routing degrades and the report section is
   not enough). The closed-loop pull (triage groups by `failure_mode`) is solvable
   **additively** — extend `triage` to also group by the root-cause attribution — without
   redefining the label.

3. **`per_fact is None` handling → N/A, NOT 0/0 (option 3a).** When a category has no
   per-fact evidence (e.g. pre-sprint-8 records with `per_fact=None`, or an empty
   failed-fact denominator), the root-cause cells render **N/A** via the existing
   `_fmt(None)` → `"N/A"` path (KB `rag-eval/none-empty-denominator`). "Data present, zero
   gaps" renders `0.0%`. Rationale: preserve the **null-vs-absent** distinction the whole
   sprint defends (phase-1 AC-7) — a missing signal must not read as "zero gaps."
   _Rejected: 3b (silent 0/0) — conflates "no data" with "no failure."_

---

## Next Step

→ `/define sprint-8/phase-2-root-cause-linkage`
