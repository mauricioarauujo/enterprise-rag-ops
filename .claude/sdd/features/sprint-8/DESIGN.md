# DESIGN: sprint-8/phase-2-root-cause-linkage — Per-Fact Root-Cause Attribution

**Sprint/Phase:** sprint-8/phase-2-root-cause-linkage | **Date:** 2026-06-16

> Implement stage runs in **Antigravity / Gemini** against this artifact (AGENTS.md
> § Implement Contract). This DESIGN is the contract — self-contained and precise.

## Architecture

### The seam

Phase-1 persisted `FactVerdict.supporting_doc_id: str | None` with the FR-5 guard collapsing any out-of-set id to `None` before write. The **verified invariant** (BRAINSTORM, "Sharp Design Tension"): when phase-2 reads a persisted record, every `supporting_doc_id` is _either_ `None` _or_ already a member of `retrieval_ranked_ids` — so a non-None set-intersection is tautological, and the real per-fact signal for a **failed** fact (`verdict ∈ {absent, contradicted}`) is `supporting_doc_id is None → retrieval_gap` vs `supporting_doc_id is not None → generation_gap`.

This phase introduces one **pure leaf module** `src/enterprise_rag_ops/eval/root_cause.py` that owns that predicate exactly once — `classify_fact_gap(...)` plus a per-record `rollup(record) -> RootCauseRollup`. It is consumed by **two** real callers — `report.py` (new top-level `"root_cause"` key + one dedicated "Root-Cause Attribution" render block in each of `render_markdown`/`render_html`, SC-2) and `failure_taxonomy.py` (new additive `attribute_root_cause(record) -> RootCauseRollup`, SC-3). The leaf imports only `eval.schema` and `eval.records` — never `runner`/`report`/`failure_taxonomy` (Decision A; FR-1 purity). A defensive explicit membership check (`supporting_doc_id not in retrieval_ranked_ids`, FR-4) keeps the predicate correct if the FR-5 guard is ever relaxed.

### Data flow

```
EvalRecord.per_fact (list[FactVerdict] | None)
        │
        ▼
  root_cause.rollup(record) ──► RootCauseRollup{retrieval_gap, generation_gap,
        │   (per fact, via classify_fact_gap)        no_failed_facts, has_per_fact}
        │
        ├──► report.generate_report_data → data["root_cause"]  → render_markdown / render_html block  (SC-2)
        └──► failure_taxonomy.attribute_root_cause(record)      → taxonomy-surface attribution         (SC-3)

classify(record, question)  ── UNCHANGED 5-label cascade (no consumer of root_cause)  (FR-5 / AC-12)
aggregate.py / schema.py / records.py  ── UNTOUCHED  (AC-13 / NFR-1)
```

## File Manifest

| File                                              | Change                                                                                                                  | Owner                  | Phase order |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------- | ----------- |
| `src/enterprise_rag_ops/eval/root_cause.py`       | **CREATE** — `classify_fact_gap`, `rollup`, `RootCauseRollup` (pure leaf + docstring)                                   | direct (eval workflow) | 1           |
| `tests/eval/test_root_cause.py`                   | **CREATE** — predicate + rollup + degradation + defensive tests (ACs 1–7)                                               | direct (eval workflow) | 2           |
| `src/enterprise_rag_ops/eval/report.py`           | **MODIFY** — new `"root_cause"` key in `generate_report_data`; one new block in each of `render_markdown`/`render_html` | direct (eval workflow) | 3           |
| `tests/eval/test_report.py`                       | **MODIFY** — add root-cause data + render tests (ACs 8/9/10)                                                            | direct (eval workflow) | 4           |
| `src/enterprise_rag_ops/eval/failure_taxonomy.py` | **MODIFY** — add `attribute_root_cause(record)` delegating to `root_cause.rollup`; cascade/StrEnum/`is_*` untouched     | direct (taxonomy)      | 5           |
| `tests/eval/test_failure_taxonomy.py`             | **MODIFY** — add SC-3 attribution test + no-reclassification regression assertion (ACs 11/12)                           | direct (taxonomy)      | 6           |
| `src/enterprise_rag_ops/eval/aggregate.py`        | **UNTOUCHED** (AC-13, NFR-1)                                                                                            | —                      | —           |
| `src/enterprise_rag_ops/eval/schema.py`           | **UNTOUCHED** (no schema change)                                                                                        | —                      | —           |
| `src/enterprise_rag_ops/eval/records.py`          | **UNTOUCHED** (no schema change)                                                                                        | —                      | —           |
| `tests/eval/__init__.py`                          | **EXISTS** — confirm present (AC-14); do not recreate                                                                   | —                      | —           |

No specialist sub-agent exists for the eval/observability code surface; all work is `direct` per the existing eval-workflow / taxonomy convention (see Infrastructure Gaps — agent alignment).

## Exact Contracts

### 1. `src/enterprise_rag_ops/eval/root_cause.py` (CREATE)

```python
"""Per-fact root-cause attribution — the shared leaf predicate (FR-1, FR-2, FR-4).

Why None-vs-non-None is the signal (NOT a set intersection): sprint-8/phase-1's FR-5
hallucination guard collapses any `FactVerdict.supporting_doc_id` not in the judge's
retrieved set to `None` *before* persistence, and that retrieved set is provably equal
to the persisted `EvalRecord.retrieval_ranked_ids` (same `chunk_hits` source, same
doc-level dedup). So on a persisted record every `supporting_doc_id` is either `None`
or already a member of `retrieval_ranked_ids` — a non-None intersection is tautological.

For a FAILED fact (`verdict in {"absent", "contradicted"}`):
  - `supporting_doc_id is None`     -> retrieval_gap  (no retrieved doc substantiates
                                       the fact; evidence never reached the generator)
  - `supporting_doc_id` is present  -> generation_gap (the evidence WAS retrieved; the
                                       generator failed to use it)

A defensive explicit membership check (FR-4) is kept so the predicate stays correct if
the FR-5 guard is ever relaxed. Pure leaf: no I/O, no network, imports only eval.schema
and eval.records — never runner / report / failure_taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from enterprise_rag_ops.eval.records import EvalRecord
from enterprise_rag_ops.eval.schema import FactVerdict

FAILED_VERDICTS: frozenset[str] = frozenset({"absent", "contradicted"})

FactGap = Literal["retrieval_gap", "generation_gap"]


def classify_fact_gap(
    fact_verdict: FactVerdict,
    retrieval_ranked_ids: list[str],
) -> FactGap | None:
    """Classify one fact verdict into a root-cause gap label (FR-1, FR-4).

    Returns:
        None              when verdict == "present" (the fact is not a failure).
        "retrieval_gap"   when the fact failed AND supporting_doc_id is None, or
                          (defensively, FR-4) supporting_doc_id is not in
                          retrieval_ranked_ids.
        "generation_gap"  when the fact failed AND supporting_doc_id is present in
                          retrieval_ranked_ids.
    """
    if fact_verdict.verdict not in FAILED_VERDICTS:
        return None
    doc_id = fact_verdict.supporting_doc_id
    if doc_id is None or doc_id not in retrieval_ranked_ids:
        return "retrieval_gap"
    return "generation_gap"


@dataclass(frozen=True, slots=True)
class RootCauseRollup:
    """Per-record root-cause counts (FR-2).

    `has_per_fact` distinguishes "no per-fact evidence" (record.per_fact is None →
    has_per_fact=False, the degraded case the report maps to N/A) from "data present,
    zero gaps" (has_per_fact=True with all counts 0 → 0.0%). This preserves the
    null-vs-absent distinction (phase-1 AC-7 / FR-6).

    `no_failed_facts` is True iff per-fact evidence exists but zero facts failed.
    """

    retrieval_gap: int = 0
    generation_gap: int = 0
    no_failed_facts: bool = False
    has_per_fact: bool = True

    @property
    def total_failed(self) -> int:
        """Failed facts with an assigned gap (retrieval_gap + generation_gap)."""
        return self.retrieval_gap + self.generation_gap


def rollup(record: EvalRecord) -> RootCauseRollup:
    """Apply `classify_fact_gap` across `record.per_fact` (FR-2).

    Graceful degradation (FR-2 / NFR-1): when record.per_fact is None, returns a rollup
    with has_per_fact=False and zero counts — distinct from "zero gaps" — never raises.
    """
    if record.per_fact is None:
        return RootCauseRollup(has_per_fact=False)

    retrieval = 0
    generation = 0
    for fv in record.per_fact:
        gap = classify_fact_gap(fv, record.retrieval_ranked_ids)
        if gap == "retrieval_gap":
            retrieval += 1
        elif gap == "generation_gap":
            generation += 1
    return RootCauseRollup(
        retrieval_gap=retrieval,
        generation_gap=generation,
        no_failed_facts=(retrieval == 0 and generation == 0),
        has_per_fact=True,
    )
```

**A1 resolved:** signature is `classify_fact_gap(fact_verdict: FactVerdict, retrieval_ranked_ids: list[str]) -> FactGap | None`. Passing the whole `FactVerdict` (not unpacked fields) keeps the call site readable and matches Decision A wording. Parameter typed `list[str]` (not `set`) to match the persisted `EvalRecord.retrieval_ranked_ids: list[str]` field exactly — the caller (`rollup`) iterates `per_fact` once and the membership check is over the typically short top-k id list, so the O(1)-set micro-optimization is not justified at this scale and `list` avoids a per-call `set()` build that would obscure the contract. (If a hot path emerges, the caller can pass a pre-built `set[str]` — `in` works identically.)

**A2 resolved:** `RootCauseRollup` is a `@dataclass(frozen=True, slots=True)` (matches the project's frozen-dataclass convention, e.g. `Question`, `TriageReport`). Degraded marker is the explicit `has_per_fact: bool` field — `has_per_fact=False` is "no per-fact evidence" (degraded → N/A), `has_per_fact=True` with `total_failed == 0` is "data present, zero gaps" → `0.0%`. `total_failed` is a `@property`, not a stored field, to keep the count fields the single SSoT.

### 2. `report.py` — `generate_report_data` new key (MODIFY)

**Import to add** (top of file, with the other eval imports):

```python
from enterprise_rag_ops.eval.root_cause import RootCauseRollup, rollup
```

**A3 resolved — data shape.** Per DEFINE/FR-3 a **new top-level key** `"root_cause"` (not nested into `categories[*].metrics`). Grain = **per category AND per model**, mirroring the existing `categories[*].metrics[model]` shape. Inside the existing per-category / per-model loop in `generate_report_data`, accumulate a rollup sum across that category-model's records and build a parallel `root_cause_data` list:

```python
# after the existing category loop body computes model_cat_metrics, also accumulate
# root-cause rollups per model for this category:
model_cat_root_cause = {}
for model_name, recs in model_records.items():
    cat_recs = [r for r in recs if r.question_id in cat_q_ids]
    agg_retrieval = 0
    agg_generation = 0
    any_evidence = False
    for r in cat_recs:
        rc = rollup(r)
        if rc.has_per_fact:
            any_evidence = True
            agg_retrieval += rc.retrieval_gap
            agg_generation += rc.generation_gap
    denom = agg_retrieval + agg_generation
    # FR-6 / Decision D: no per-fact evidence at all -> None (N/A); evidence with
    # zero gaps -> 0.0 (0.0%); otherwise the retrieval-gap share among failed facts.
    if not any_evidence:
        retrieval_gap_pct = None
    elif denom == 0:
        retrieval_gap_pct = 0.0
    else:
        retrieval_gap_pct = agg_retrieval / denom
    model_cat_root_cause[model_name] = {
        "retrieval_gap": agg_retrieval,
        "generation_gap": agg_generation,
        "retrieval_gap_pct": retrieval_gap_pct,
        "has_evidence": any_evidence,
    }
root_cause_data.append({"category": cat, "metrics": model_cat_root_cause})
```

Initialise `root_cause_data = []` alongside `category_data = []`. Add `"root_cause": root_cause_data` to the returned dict. The existing four keys (`k`, `summary`, `categories`, `costs`) and the 7-column category table are **unchanged** (NFR-4).

**Per-category-per-model dict shape (exact):**

```python
data["root_cause"] = [
    {
        "category": str,
        "metrics": {
            model_name: {
                "retrieval_gap": int,            # count of failed facts, no doc retrieved
                "generation_gap": int,           # count of failed facts, doc was retrieved
                "retrieval_gap_pct": float | None,  # None => N/A; 0.0 => 0.0%; else share
                "has_evidence": bool,            # False => whole category-model degraded (N/A)
            },
            ...
        },
    },
    ...
]
```

**Percentage formula (FR-3, A3):** `retrieval_gap_pct = retrieval_gap / (retrieval_gap + generation_gap)` among **failed** facts. The complement `generation_gap_pct = 1 - retrieval_gap_pct` (the two sum to 100% when data present), so the renderer derives generation share from the stored retrieval share and need not store both.

**N/A vs 0.0% rule (FR-6, Decision D):** `retrieval_gap_pct is None` ⇒ render via `_fmt(None, pct=True)` → `"N/A"` (no per-fact evidence anywhere in the category-model — `has_evidence=False`, or denominator 0 because all records degraded). `retrieval_gap_pct == 0.0` with `has_evidence=True` ⇒ `_fmt(0.0, pct=True)` → `"0.0%"` (data present, zero failed-fact gaps). Counts render directly (`int`) — N/A only ever applies to the percentage cell.

### 3. `report.py` — `render_markdown` new block (MODIFY)

After the cost table block and before `template = Template(...)`, build:

```python
# Root-Cause Attribution table (SC-2): retrieval-gap vs generation-gap of FAILED facts.
md_root_cause = (
    "| Category | Model | Retrieval-Gap (failed facts) | Generation-Gap (failed facts) | Retrieval-Gap % |\n"
)
md_root_cause += "| --- | --- | --- | --- | --- |\n"
for rc_row in data["root_cause"]:
    first = True
    for model_name, rc in rc_row["metrics"].items():
        cat_label = f"**{rc_row['category']}**" if first else ""
        md_root_cause += (
            f"| {cat_label} | {model_name} | {rc['retrieval_gap']} | "
            f"{rc['generation_gap']} | {_fmt(rc['retrieval_gap_pct'], pct=True)} |\n"
        )
        first = False
```

Add a `## Root-Cause Attribution` section to the markdown `Template` string (after the `## Detailed Breakdown Per Category` section) with a `$root_cause_table` placeholder, and add `root_cause_table=md_root_cause` to `template.substitute(...)`.

**Render marker for tests (AC-9):** the exact substring `"## Root-Cause Attribution"` MUST appear in the markdown output.

### 4. `report.py` — `render_html` new block (MODIFY)

After the cost-rows block, build `html_root_cause_rows` mirroring the category-table rowspan pattern, using `_fmt(rc["retrieval_gap_pct"], pct=True)` for the percentage cell. Add a new `<div class="card">` containing an `<h2>Root-Cause Attribution</h2>` and a 5-column table (`Category`, `Model`, `Retrieval-Gap`, `Generation-Gap`, `Retrieval-Gap %`) with a `$root_cause_rows` placeholder in `<tbody>`, inserted after the "Detailed Category breakdown" card. Add `root_cause_rows=html_root_cause_rows` to `template.substitute(...)`.

**Render marker for tests (AC-9):** the exact substring `"Root-Cause Attribution"` MUST appear in the HTML output (the `<h2>` text). The existing category `<table>` keeps its 7 `<th>` columns unchanged (NFR-4).

### 5. `failure_taxonomy.py` — `attribute_root_cause` (MODIFY)

**A4 resolved.** Add a single new public function; the 5-label `classify()` cascade, `FailureMode` StrEnum, `is_*` helpers, and 0.5/0.5 thresholds are **untouched** (FR-5 / AC-12 / AC-13). New import + function:

```python
from enterprise_rag_ops.eval.root_cause import RootCauseRollup, rollup


def attribute_root_cause(record: EvalRecord) -> RootCauseRollup:
    """Per-fact root-cause attribution at the taxonomy surface (FR-5 / SC-3).

    Delegates to `root_cause.rollup` so the taxonomy can attribute a retrieval-miss
    vs generation-gap root cause from the per-fact `supporting_doc_id` signal — not
    just answer-level aggregates (SC-3's literal requirement). Additive and orthogonal:
    it does NOT touch `classify()`, the cascade order, the `FailureMode` members, or
    the `is_*` helpers — no record is reclassified (Decision C / AC-12).
    """
    return rollup(record)
```

**Why this satisfies SC-3 at the taxonomy surface without importing report or touching `classify()`:** SC-3 requires "the taxonomy _can attribute_ a retrieval-miss root cause using the new field." `attribute_root_cause` is a public function _in `failure_taxonomy.py`_ (the taxonomy module surface) returning the per-fact `retrieval_gap`/`generation_gap` breakdown via the shared leaf. It adds zero coupling to `report.py` and leaves the 5-label classifier byte-identical (verified by the AC-12 regression). It is a thin delegating wrapper (not a re-export) so the taxonomy surface exposes the capability as its own named function — discoverable where a triage/taxonomy consumer looks.

## Implementation Phases

Built leaf-first, each step independently testable (Engineering Behavior — validate-smallest-first):

1. **Create `eval/root_cause.py`** (Phase order 1) — `FAILED_VERDICTS`, `classify_fact_gap`, `RootCauseRollup`, `rollup`. Pure; no consumer yet.
2. **Create `tests/eval/test_root_cause.py`** (2) — covers ACs 1–7. Validate: `uv run pytest tests/eval/test_root_cause.py`. Gate the leaf before any consumer wiring.
3. **Modify `report.py`** (3) — add `"root_cause"` key + the two render blocks. Validate: `uv run pytest tests/eval/test_report.py`.
4. **Modify `tests/eval/test_report.py`** (4) — ACs 8/9/10. Validate same -k subset.
5. **Modify `failure_taxonomy.py`** (5) — add `attribute_root_cause`. Validate: `uv run pytest tests/eval/test_failure_taxonomy.py`.
6. **Modify `tests/eval/test_failure_taxonomy.py`** (6) — ACs 11/12 (incl. the no-reclassification regression). Then full gate: `make lint test` (AC-15 / NFR-5).

This honours the phase-ordering convention: no data-schema/config/dataset change (schema untouched), core module (`root_cause.py`) → eval-harness consumers (`report.py`, `failure_taxonomy.py`) → tests, then the lint/test gate. No observability hook, no docs/ADR (AC-13: no new ADR).

## Test Plan

All tests **offline** (no network, no API key, no model download, no mocked LLM — NFR-2 / AC-14), reusing `tests/eval/conftest.py` fixtures. A new tiny local factory is added in `test_root_cause.py` for records with controllable `per_fact`/`retrieval_ranked_ids` (the existing `make_eval_record` in `test_failure_taxonomy.py` does not expose `per_fact`, so duplicating it locally is cleaner than cross-importing a test helper).

### `tests/eval/test_root_cause.py` (CREATE) — new local factory

```python
def _fv(fact: str, verdict: str, supporting_doc_id: str | None = None) -> FactVerdict:
    return FactVerdict(fact=fact, verdict=verdict, supporting_doc_id=supporting_doc_id)

def _record_with_facts(
    per_fact: list[FactVerdict] | None,
    retrieval_ranked_ids: list[str],
) -> EvalRecord:
    """Minimal EvalRecord with controllable per_fact / retrieval_ranked_ids."""
    # build via EvalRecord(...) mirroring make_eval_record's required fields, setting
    # per_fact=per_fact and retrieval_ranked_ids=retrieval_ranked_ids.
```

| Test name                                                    | AC  | Asserts                                                                                                                                                                                                                                      | Fixtures           |
| ------------------------------------------------------------ | --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| `test_present_fact_returns_none`                             | 1   | `classify_fact_gap(_fv("f","present", "doc_x"), ["doc_x"])` and `(..., None, [])` — present always → `None` regardless of `supporting_doc_id`/membership                                                                                     | none (local `_fv`) |
| `test_failed_fact_none_doc_is_retrieval_gap`                 | 2   | for both `"absent"` and `"contradicted"` with `supporting_doc_id is None` → `"retrieval_gap"` (parametrized over the two verdicts)                                                                                                           | local              |
| `test_failed_fact_retrieved_doc_is_generation_gap`           | 3   | `_fv("f","absent","doc_real")` with `retrieval_ranked_ids=["doc_real"]` → `"generation_gap"`                                                                                                                                                 | local              |
| `test_failed_fact_out_of_set_doc_is_retrieval_gap_defensive` | 4   | `_fv("f","absent","gd_hallucinated")` with `retrieval_ranked_ids=["doc_real"]` (non-None but **not** in set) → `"retrieval_gap"` — explicit defensive branch                                                                                 | local              |
| `test_output_domain_over_matrix`                             | 5   | iterate verdict × `supporting_doc_id ∈ {None, in-set, out-of-set}`; assert every return ∈ `{"retrieval_gap","generation_gap", None}`                                                                                                         | local              |
| `test_rollup_counts_mixed_facts`                             | 6   | record with `per_fact=[present(doc_real), absent(None), contradicted(doc_real), absent(out_of_set)]`, `retrieval_ranked_ids=["doc_real"]` → `retrieval_gap=2, generation_gap=1, no_failed_facts=False, has_per_fact=True`; `total_failed==3` | local              |
| `test_rollup_zero_failed_facts_distinct_from_degraded`       | 6   | record with all-`present` per_fact → `no_failed_facts=True, has_per_fact=True, total_failed==0`                                                                                                                                              | local              |
| `test_rollup_per_fact_none_degrades`                         | 7   | `rollup(record_with per_fact=None)` does not raise; `has_per_fact is False`, all counts 0, `no_failed_facts is False` — distinct from the zero-gaps case above                                                                               | local              |

**Reuse note:** `canned_verdict_payload` already encodes the exact two-branch case (one `present`/`doc_real` retained, one `absent`/`gd_hallucinated` → collapsed to `None` by the guard). `test_root_cause.py` need not parse it (the local `_fv` factory is more direct for unit coverage), but the doc-id vocabulary (`doc_real`, `gd_hallucinated`, `gd_unrelated`) is reused for consistency.

### `tests/eval/test_report.py` (MODIFY) — additions

Extend the existing `sample_jsonl` fixture records (or add a focused second fixture) so that: (a) the `basic` category record carries a `per_fact` list with ≥1 failed fact split across gap types → exercises the count + percentage path; (b) at least one category's records all have `per_fact` **absent/None** → exercises N/A; (c) one category has per-fact evidence with zero failed facts → exercises `0.0%`. (The existing fixture records omit `per_fact`, so they default to `None` and already provide the degraded/N-A baseline — AC-10's N/A half is satisfied by leaving most fillers as-is.)

| Test name                                      | AC  | Asserts                                                                                                                                                                                                                                                           | Fixtures                                             |
| ---------------------------------------------- | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `test_root_cause_key_in_report_data`           | 8   | `generate_report_data(sample_jsonl)` (with `load_questions` monkeypatched as in existing test) has top-level `"root_cause"`; the `basic` category entry distinguishes `retrieval_gap` vs `generation_gap` counts among failed facts                               | `sample_jsonl`, `monkeypatch`                        |
| `test_root_cause_section_rendered_md_and_html` | 9   | `render_report` output contains `"## Root-Cause Attribution"` (md) and `"Root-Cause Attribution"` (html `<h2>`); existing 7-column category table column count unchanged — assert the category header line still has exactly its 7 columns / the 7 `<th>` (NFR-4) | `sample_jsonl`, `tmp_path`, `monkeypatch`            |
| `test_root_cause_na_vs_zero_pct`               | 10  | a category whose records are all `per_fact=None` renders `N/A` in the root-cause section; a category with per-fact evidence and zero failed facts renders `0.0%`; the two are asserted **distinctly**                                                             | `sample_jsonl` (extended), `tmp_path`, `monkeypatch` |

### `tests/eval/test_failure_taxonomy.py` (MODIFY) — additions

`make_eval_record` currently has no `per_fact` parameter. Add an optional `per_fact: list[FactVerdict] | None = None` parameter to it (additive, default `None` keeps all existing call sites green) and pass it through to the `EvalRecord(...)` constructor.

| Test name                                       | AC  | Asserts                                                                                                                                                                                                                                                                                                                                                            | Fixtures                                          |
| ----------------------------------------------- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| `test_attribute_root_cause_at_taxonomy_surface` | 11  | import `attribute_root_cause` from `enterprise_rag_ops.eval.failure_taxonomy`; call on a record with mixed failed facts (`per_fact` set, `retrieval_ranked_ids` set); assert the returned `RootCauseRollup.retrieval_gap`/`generation_gap` match the expected split — proves SC-3 reachable through the taxonomy module's public surface, built on `root_cause.py` | extended `make_eval_record`                       |
| `test_classify_unchanged_no_reclassification`   | 12  | re-run the five canonical fixtures (one per label) asserting `classify(...)` returns the identical `FailureMode` for each — regression guard that the cascade order, StrEnum members, and `is_*` helpers are untouched. Also assert `len(FailureMode) == 5` (no 6th label, AC-13)                                                                                  | reuse existing `make_eval_record`/`make_question` |

**AC-13 coverage** is split: the `len(FailureMode) == 5` assertion lives in `test_classify_unchanged_no_reclassification`; the "`aggregate.py` unmodified / no new ADR" half is a manifest/diff invariant (the executor must not touch `aggregate.py` or add `docs/adr/*`) — enforced by code review, not a runtime test.

## Infrastructure Gaps

| Gap Type           | Area                         | Detail                                                                                                                                                                                                                                                              | Recommendation                                                                                                                                                                                |
| ------------------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Missing domain     | —                            | No new technology area. `rag-eval` covers per-fact judge/report-render/eval-record-schema; `observability` covers the failure taxonomy. Both exist in `_index.yaml`.                                                                                                | None                                                                                                                                                                                          |
| Missing concept    | `rag-eval` / `observability` | The root-cause-attribution predicate (None-vs-non-None on failed facts, the FR-5-tautology insight) is **not yet** a KB concept — but DEFINE A5 explicitly defers KB work to a post-phase `/update-kb observability`. Not a blocker.                                | After phase lands: `/update-kb observability` (failure-taxonomy entry) and optionally a `rag-eval` `root-cause-attribution` concept — per A5, **not** before `/implement`.                    |
| Missing specialist | eval / taxonomy code         | No `rag-eval` or `observability` _specialist_ sub-agent exists (`.claude/agents/` holds only workflow agents). All prior eval/taxonomy phases shipped `direct`. The change is ~1 leaf module + 3 thin edits — below the self-improvement threshold for a new agent. | None this phase. If a 3rd eval-internals phase needs the same `report.py`+`failure_taxonomy.py`+`conftest` read-set, propose `/new-agent eval-specialist` then (self-improvement trigger #3). |

**Three-layer verdict:** domain existence ✅, concept coverage ✅ (sufficient for `/implement`; KB enrichment deferred per A5), agent alignment ✅ (`direct` is the established convention; no gap). Matches DEFINE's "No infrastructure gaps".

## Consistency Check

**Verdict: ✅ CONSISTENT.** Non-trivial phase (3 source modules + 3 test files); full six-pass review run.

| ID  | Severity | Pass                           | Location                  | Finding                                                                                                                                                                                                                                                               | Suggested fix                                        |
| --- | -------- | ------------------------------ | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| C1  | LOW      | 1 Duplication                  | DEFINE FR-4 vs FR-1       | FR-4's defensive membership check is described twice. DESIGN folds both into the single `classify_fact_gap` body — no duplication in code.                                                                                                                            | None; phrasing overlap is intentional emphasis.      |
| C2  | LOW      | 2 Ambiguity                    | DEFINE FR-2 "True/1"      | DEFINE left `no_failed_facts` as bool-or-int open. DESIGN pins it to `bool`.                                                                                                                                                                                          | Resolved (A2).                                       |
| C3  | MEDIUM   | 3 Underspecification           | A3 / FR-3 report shape    | DEFINE said "new top-level key" but left nest-vs-parallel and the dict shape open. DESIGN pins a parallel top-level `"root_cause"` list mirroring `categories[*].metrics[model]`, with the exact 4-key per-cell dict.                                                 | Resolved — § Exact Contracts.                        |
| C4  | —        | 4 Constitution alignment       | whole design              | No speculative scope: leaf justified by **two named consumers**. Defensive FR-4 branch justified by a named anticipated change (FR-5 guard relaxation). Conventions honoured (English, mirrored `tests/eval/`, `__init__.py` present, frozen-dataclass, no LLM mock). | None — no CRITICAL.                                  |
| C5  | —        | 5 Coverage                     | FR-1…FR-7, NFR-1…5        | Every FR maps to ≥1 manifest entry + ≥1 AC test (FR-1→ACs 1–5; FR-2→ACs 6,7; FR-3→ACs 8,9; FR-4→AC 4; FR-5→ACs 11,12; FR-6→AC 10; FR-7→AC 14). NFR-1→AC 7,10; NFR-4→AC 9; NFR-5→make lint test. No orphan.                                                            | None.                                                |
| C6  | —        | 6 Inconsistency                | DEFINE↔DESIGN terminology | Terms used identically across DEFINE/BRAINSTORM/DESIGN. No drift.                                                                                                                                                                                                     | None.                                                |
| C7  | —        | Won't adherence                | AC-13 / Won't             | No `aggregate.py`/`schema.py`/`records.py` change; no 6th label; no cascade-order/`is_*`/threshold change; no Option-2c; no Phoenix span; no schema field; no new ADR. All Won'ts respected.                                                                          | None.                                                |
| C8  | LOW      | 5 Coverage (test-AC bijection) | AC-13                     | AC-13 is part-runtime (`len(FailureMode)==5`) and part-invariant (no `aggregate.py` diff, no ADR) — invariant half is review-enforced.                                                                                                                                | Acceptable; flagged so the reviewer checks the diff. |

No CRITICAL or HIGH findings. The two MEDIUM/LOW underspecifications (C2, C3) were the assumptions DEFINE deferred to design (A2, A3) and are now resolved. Self-review; `DEFINE.md` is **not** rewritten.

## Risks & Trade-offs

- **Tautology risk if FR-5 guard is relaxed.** The whole signal rests on the phase-1 invariant. Mitigation is the FR-4 defensive `not in retrieval_ranked_ids` branch plus the module docstring citing the invariant source — a future guard removal degrades gracefully rather than silently inverting the signal. **No ADR warranted** (additive, NFR-3) — but if the coarse 5-label taxonomy later proves insufficient and Option-2c is revisited, _that_ triggers the deferred ADR-0008 amendment (DEFINE Won't / backlog).
- **Report fixture extension.** The biggest test-surface change is extending `sample_jsonl` to carry `per_fact` for ≥1 category. Mitigation: keep most filler records `per_fact`-absent (their default `None`) so existing assertions stay green and the degraded/N-A path is covered for free; add per-fact evidence to a single category.
- **`make_eval_record` signature change** in `test_failure_taxonomy.py` (adding `per_fact=None`) is additive with a default — no existing call site breaks.
- **N/A-vs-0.0% is the load-bearing correctness property** (the sprint's null-vs-absent discipline). Asserted distinctly in AC-10; the `has_evidence` flag in the data shape is what keeps "no data" from collapsing into "0.0%".

No architectural decision rises to an ADR this phase (additive, no seam swap, no new tool) — consistent with DEFINE AC-13.

## Next Step

→ `/implement sprint-8/phase-2-root-cause-linkage` — no infrastructure gaps to clear first; KB enrichment (`/update-kb observability`) runs **after** the phase lands per assumption A5.
