# DEFINE: sprint-8/phase-2-root-cause-linkage — Per-Fact Root-Cause Attribution

**Sprint/Phase:** sprint-8/phase-2-root-cause-linkage | **Date:** 2026-06-16

---

## Context & Grounding Invariant

Phase-1 added `FactVerdict.supporting_doc_id: str | None` (`eval/schema.py`) and an FR-5
hallucination guard that collapses any `supporting_doc_id` not in the judge's retrieved
set to `None` _before_ persistence. The judge's retrieved set (`{c.doc_id for c in
ctx_chunks}`) is provably equal to the persisted `EvalRecord.retrieval_ranked_ids` (same
`chunk_hits` source, same doc-level dedup). **Verified invariant:** when phase-2 reads a
persisted record, every `supporting_doc_id` is _either_ `None` _or_ already a member of
`retrieval_ranked_ids`. A naive non-None set-intersection is therefore tautological.

The real per-fact signal for a **failed** fact (`verdict ∈ {absent, contradicted}`) is:

- `supporting_doc_id is None` → **retrieval_gap** — no retrieved doc substantiates the
  fact; the evidence never reached the generator.
- `supporting_doc_id is not None` → **generation_gap** — the evidence WAS retrieved; the
  generator failed to use it.

A defensive explicit cross-reference (`supporting_doc_id not in retrieval_ranked_ids` →
retrieval_gap) is kept as a Should, so the predicate stays correct if the FR-5 guard is
ever relaxed.

This phase serves the sprint success criteria:

- **SC-2** — the eval report distinguishes "fact failed, supporting doc WAS retrieved"
  from "fact failed, supporting doc was NEVER retrieved" for ≥1 worked category.
- **SC-3** — the failure-mode taxonomy can attribute a retrieval-miss root cause using
  the new field, not just answer-level aggregates.

---

## Requirements

### Functional

**FR-1 — Shared root-cause predicate.** A new pure module
`src/enterprise_rag_ops/eval/root_cause.py` exposes a single named predicate that classifies
one fact verdict, given the record's `retrieval_ranked_ids`, into a root-cause label.
Contract:

- Returns `None` when `verdict == "present"` (the fact is not a failure).
- Returns `"retrieval_gap"` when the fact failed (`verdict ∈ {absent, contradicted}`) **and**
  `supporting_doc_id is None` — or, defensively, when `supporting_doc_id` is not in
  `retrieval_ranked_ids` (FR-4).
- Returns `"generation_gap"` when the fact failed and `supporting_doc_id` is present in
  `retrieval_ranked_ids`.
- Output domain is exactly `Literal["retrieval_gap", "generation_gap"] | None`.
- The module is pure: no I/O, no network, no imports from `runner`/`report`/`failure_taxonomy`
  (it is a leaf consumed by them, never the reverse).

**FR-2 — Per-record rollup.** `root_cause.py` exposes a `RootCauseRollup` type (dataclass or
TypedDict — design's call) carrying integer counts `{retrieval_gap, generation_gap,
no_failed_facts}`, and a `rollup(record: EvalRecord) -> RootCauseRollup` that applies FR-1's
predicate across `record.per_fact`. Contract:

- Counts each failed fact into `retrieval_gap` or `generation_gap` per FR-1.
- `no_failed_facts` is `True`/`1` (design's representation) **iff** the record has per-fact
  evidence but zero failed facts — i.e. the "data present, zero gaps" case (distinct from
  the degraded case below).
- **Graceful degradation:** when `record.per_fact is None`, `rollup` must signal "no
  per-fact evidence" distinctly from "zero gaps" (e.g. all-zero counts plus a degraded
  marker, or a sentinel the report maps to N/A). It must NOT raise and must NOT report it
  as `0` gaps masquerading as data.

**FR-3 — Report sub-section (Decision B / OQ-1 → 1b).** `report.py`'s
`generate_report_data(jsonl_path) -> dict` gains a **new top-level key** (e.g. `"root_cause"`)
holding per-category root-cause aggregates, computed via `root_cause.rollup`. `render_markdown`
and `render_html` each gain **one new dedicated "Root-Cause Attribution" section/table block**
— NOT extra columns on the existing 7-column per-category table. The section must, for at
least one category with per-fact evidence, present the retrieval-gap vs generation-gap split
of failed facts (counts and/or percentages). This satisfies **SC-2**.

**FR-4 — Defensive cross-reference (Should).** FR-1's predicate uses an explicit membership
check (`supporting_doc_id not in record.retrieval_ranked_ids` → retrieval*gap) rather than
relying solely on the `None` value, making the FR-5 invariant visible in code and robust to a
future guard removal. A module docstring states \_why* None-vs-non-None is the signal and cites
phase-1 FR-5 as the invariant source.

**FR-5 — Taxonomy-level attribution capability (Decision C / OQ-2 → 2a).** The failure-mode
taxonomy gains a **new, additive per-fact root-cause attribution capability** built on
`root_cause.py`, reachable as a taxonomy-surface capability (a function in
`failure_taxonomy.py` that calls `root_cause.py`, or `root_cause.py` re-exported through the
taxonomy module — design finalizes placement). This capability lets the taxonomy attribute a
retrieval-miss root cause from the per-fact `supporting_doc_id` field, satisfying **SC-3**.
The existing 5-label `classify()` cascade, its order, the `FailureMode` `StrEnum` values, and
the `is_*` helpers/thresholds are **untouched** — no record changes label.

**FR-6 — N/A vs 0.0% rendering (Decision D / OQ-3 → 3a).** When a category has no per-fact
evidence (pre-sprint-8 `per_fact=None` records, or an empty failed-fact denominator),
root-cause cells render **N/A** via the existing `_fmt(None) -> "N/A"` path. The "data present,
zero gaps" case renders `0.0%`. The null-vs-absent distinction (phase-1 AC-7) is preserved end
to end — a missing signal must never read as "zero gaps."

**FR-7 — Mirrored tests.** `tests/eval/test_root_cause.py` covers the predicate, the rollup
(including `per_fact is None` degradation), and the defensive branch. Report and taxonomy
changes are covered in their existing mirrored test files (`tests/eval/test_report.py`,
`tests/eval/test_failure_taxonomy.py`). All tests are offline (no network, no API key, no
mocked LLM) and reuse `tests/eval/conftest.py` fixtures / canned payloads.

### Non-functional

**NFR-1 — Backward compatibility.** Records with `per_fact=None` (pre-sprint-8) must flow
through `rollup`, the report, and the taxonomy capability without error, rendering N/A per
FR-6. No schema field is added or changed; `aggregate.py` is not modified.

**NFR-2 — Determinism & offline.** All new code is pure and deterministic; the full test
surface runs under `make test` with no network, no API key, no model download, no mocked LLM.

**NFR-3 — Minimal scope, clean seam.** The predicate is defined exactly once in
`root_cause.py` and imported by both consumers (no duplicated inline logic). No speculative
config knobs, no new ADR (the change is additive). New module ≈ one predicate + one rollup
type + docstring.

**NFR-4 — Report data-model stability.** The existing `report` output keys (`k`, `summary`,
`categories`, `costs`) and the 7-column per-category table are unchanged; root-cause is purely
additive (a new key + a new render block). Existing report tests stay green unmodified except
for additions.

**NFR-5 — Gate.** `make lint test` is green.

---

## Acceptance Criteria

1. **(FR-1, present→None)** `classify_fact_gap` returns `None` for any fact with
   `verdict == "present"`, regardless of `supporting_doc_id` value or membership in
   `retrieval_ranked_ids`.
2. **(FR-1, retrieval_gap)** For a failed fact (`verdict == "absent"` and `verdict ==
"contradicted"`, both tested) with `supporting_doc_id is None`, the predicate returns
   `"retrieval_gap"`.
3. **(FR-1, generation_gap)** For a failed fact whose `supporting_doc_id` IS present in
   `retrieval_ranked_ids`, the predicate returns `"generation_gap"`.
4. **(FR-4, defensive)** For a failed fact whose `supporting_doc_id` is non-None but **not**
   in `retrieval_ranked_ids`, the predicate returns `"retrieval_gap"` (defensive branch) and a
   test asserts this explicitly.
5. **(FR-1, output domain)** The predicate's return value is always one of
   `{"retrieval_gap", "generation_gap", None}` — asserted across the verdict × membership
   matrix.
6. **(FR-2, rollup counts)** Given a record with a mix of present/absent/contradicted facts,
   `rollup` returns counts that sum the failed facts correctly into `retrieval_gap` and
   `generation_gap`, with `no_failed_facts` set only when per-fact evidence exists but no
   fact failed.
7. **(FR-2/NFR-1, degradation)** `rollup(record)` with `record.per_fact is None` does not
   raise and yields a result the report renders as N/A (not `0` gaps) — the degraded marker is
   distinct from "zero gaps".
8. **(FR-3/SC-2, report data)** `generate_report_data` output contains the new top-level
   `"root_cause"` key with per-category aggregates, and for ≥1 category with per-fact evidence
   the aggregate distinguishes retrieval-gap from generation-gap counts/percentages among
   failed facts.
9. **(FR-3/SC-2, render)** Both `render_markdown` and `render_html` emit a dedicated
   "Root-Cause Attribution" section/table block (asserted by a section-header/table-marker
   substring), and the existing 7-column per-category table is unchanged in column structure
   (NFR-4).
10. **(FR-6/Decision D)** A category whose records all have `per_fact=None` renders N/A in the
    root-cause section; a category with per-fact evidence and zero failed facts renders `0.0%`.
    Both are asserted in a render test, distinguishing N/A from `0.0%`.
11. **(FR-5/SC-3)** A taxonomy-surface function attributes a per-fact root-cause
    (`retrieval_gap` vs `generation_gap`) for a record, built on `root_cause.py`; a test calls
    it through the taxonomy module's public surface and asserts the attribution.
12. **(FR-5, no reclassification)** `classify(record, question)` returns the same
    `FailureMode` for every fixture record as before this phase — the cascade order, the
    `FailureMode` `StrEnum` members, and the `is_*` helpers are unchanged (regression test over
    existing taxonomy fixtures stays green).
13. **(Won't enforcement)** `aggregate.py` is unmodified (no diff); `FailureMode` has exactly
    5 members (no 6th label); no new ADR is added under `docs/adr/`.
14. **(FR-7/NFR-2)** `tests/eval/test_root_cause.py` exists with a package `__init__.py`
    present, runs offline, and reuses existing conftest fixtures/canned payloads; no LLM is
    mocked.
15. **(NFR-5)** `make lint test` is green.

---

## Resolved Open Questions (assumptions — confirm before `/design`)

The three real open questions (report placement, taxonomy refinement, `per_fact is None`
handling) are LOCKED by the user (Decisions B/C/D in BRAINSTORM). The residual ambiguities
below were resolved to BRAINSTORM/code-aligned defaults; each is an **unconfirmed assumption**,
flagged per protocol (AskUserQuestion not invoked):

- **A1 — Predicate signature.** Assumed `classify_fact_gap(fact_verdict: FactVerdict,
retrieval_ranked_ids: list[str]) -> Literal["retrieval_gap","generation_gap"] | None`
  (matches the locked Decision A wording). Exact parameter shape (passing the `FactVerdict` vs
  unpacked fields) is design's call; the ACs pin only the _contract_.
- **A2 — `RootCauseRollup` representation.** Assumed an integer-count triple `{retrieval_gap,
generation_gap, no_failed_facts}` plus a degraded marker for `per_fact is None`. Dataclass
  vs TypedDict and the exact degraded-marker encoding are deferred to design (Decision A says
  so).
- **A3 — Report aggregate unit.** Assumed the report's `"root_cause"` key aggregates **per
  category** (mirroring the existing per-category table grain) and per model where multiple
  models are present, summing rollups across that category's records. The report renders
  percentages as `retrieval_gap / (retrieval_gap + generation_gap)` among failed facts (so the
  two percentages sum to 100% when data is present), with N/A when the denominator is empty
  or all records are degraded.
- **A4 — Taxonomy capability name/placement.** Assumed a new public function in
  `failure_taxonomy.py` (e.g. `attribute_root_cause(record) -> RootCauseRollup` or a per-fact
  variant) that delegates to `root_cause.py`, so SC-3 is met at the _taxonomy surface_. Exact
  name and whether it is a re-export vs a thin wrapper is design's call.
- **A5 — Post-phase KB.** Assumed the only KB action is `/update-kb observability`
  (failure-taxonomy) **after** this phase lands; no `/new-kb` or new ADR. (Matches BRAINSTORM.)

---

## Won't (explicit, this phase)

- No modification to `aggregate.py` (phase brief excludes it).
- No 6th `FailureMode` label; no change to the `StrEnum` values.
- No cascade-order change in `classify()`; no change to `is_*` helpers or the 0.5/0.5
  thresholds.
- No Option-2c redefinition of `is_retrieval_miss` to fire on the per-fact signal — deferred
  to a backlog item + ADR-0008 amendment only if the coarse label later proves insufficient.
- No Phoenix span integration (phase-3 scope).
- No schema field added/changed; no record reclassification.

---

## Clarity Score

| Dimension       | Score | Note                                                                                                                                                               |
| --------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Problem**     | 3     | Root cause stated with code evidence: the FR-5 guard makes non-None intersection tautological; None-vs-non-None on failed facts is the verified signal.            |
| **Users**       | 3     | Named roles: the eval operator reading the report (SC-2 diagnosis) and the triage/taxonomy consumer (SC-3 attribution). Workflow impact is explicit.               |
| **Success**     | 3     | 15 falsifiable ACs mapped to FRs, each asserting a concrete branch/output; SC-2 and SC-3 each have a dedicated AC (8/9, 11).                                       |
| **Scope**       | 3     | MoSCoW inherited from BRAINSTORM + explicit Won't list (aggregate.py, 6th label, cascade order, 2c, Phoenix, schema change).                                       |
| **Constraints** | 3     | All constraints named: offline/no-mock-LLM, `make lint test` gate, mirrored test layout + `__init__.py`, additive data model, N/A-vs-0.0% null discipline, no ADR. |

**Total: 15/15** — PASS (≥12). All three open questions were pre-resolved and locked by the
user; residual ambiguities resolved to aligned defaults and flagged as assumptions (A1–A5).

---

## Infrastructure Readiness

| Dependency                                                                    | KB domain       | Specialist      | Status                                                                            |
| ----------------------------------------------------------------------------- | --------------- | --------------- | --------------------------------------------------------------------------------- |
| `eval/schema.py` `FactVerdict.supporting_doc_id`                              | `rag-eval`      | (eval workflow) | Ready — shipped phase-1; verified in code.                                        |
| `eval/records.py` `EvalRecord` (`per_fact`, `retrieval_ranked_ids`, `k`)      | `rag-eval`      | (eval workflow) | Ready — fields verified; `per_fact: list[FactVerdict] \| None`.                   |
| `eval/report.py` (`generate_report_data`, `render_*`, `_fmt`/`_mean`)         | `rag-eval`      | (eval workflow) | Ready — render pattern + `_fmt(None)->"N/A"` confirmed; additive key/section.     |
| `eval/failure_taxonomy.py` (5-label cascade, `is_*`)                          | `observability` | (taxonomy)      | Ready — cascade/StrEnum verified; additive capability only.                       |
| `tests/eval/conftest.py` fixtures (`canned_verdict_payload`, `sample_chunks`) | `rag-eval`      | (eval workflow) | Ready — offline fixtures exercise both guard branches; reusable for FR-7.         |
| `make lint test` gate                                                         | —               | —               | Ready — standard gate.                                                            |
| ADR-0008 (taxonomy) — amendment                                               | `observability` | (taxonomy)      | Not needed this phase (2c is a Won't); deferred to backlog if coarse label fails. |
| Post-phase `/update-kb observability`                                         | `observability` | (taxonomy)      | Pending — run AFTER phase lands (failure-taxonomy entry). Not a blocker.          |

No infrastructure gaps. KB domains `rag-eval` and `observability` are sufficient; no
`/new-kb`, `/new-agent`, or new ADR is required.

---

## Next Step

→ `/design sprint-8/phase-2-root-cause-linkage`
