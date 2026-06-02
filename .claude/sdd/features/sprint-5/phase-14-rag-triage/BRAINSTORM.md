# BRAINSTORM: phase-14-rag-triage — rag-triage Core

**Sprint/Phase:** sprint-5/phase-14-rag-triage | **Date:** 2026-06-01

---

## Problem Statement

The harness already produces a classified JSONL (`rag-classify` output) with a
`failure_mode` label on every `EvalRecord`. What is missing is the aggregation step
that clusters those records by `failure_mode` (and optionally `category`), quantifies
each cluster, and emits a deterministic, machine-readable artifact that Phase 15 can
consume to draft GitHub Issues. Phase 14 is the pure read-only data step: no re-run,
no network, no LLM, no external side effects.

---

## Suggested Research & KB Work

| Topic                                                                        | Coverage                                                         | Action                                                   |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------- |
| `EvalRecord` schema + `failure_mode` field                                   | sufficient — `rag-eval/concepts/eval-record-schema.md`           | Reuse                                                    |
| None/empty-denominator convention (rate denominators)                        | sufficient — `rag-eval/concepts/none-empty-denominator.md`       | Reuse                                                    |
| Retrieval metric aggregation patterns (per-category grouping, None-skipping) | sufficient — `rag-eval/concepts/retrieval-metric-aggregation.md` | Reuse                                                    |
| Failure taxonomy 5-label cascade                                             | sufficient — `observability/concepts/failure-taxonomy.md`        | Reuse                                                    |
| Triage cluster → issue contract (the cluster signature for Phase 15)         | thin — not yet documented                                        | Add to `rag-eval` KB **after ADR-0009 lands** (Phase 15) |

No `--deep-research` needed. The triage pattern is a groupby-aggregate over a known
schema; the interesting unknown (issue idempotency key) belongs to Phase 15.

---

## Approaches Considered

### Axis summary (how each approach resolves the six design axes)

Before the table: axis choices that are identical across all three approaches —

- **Input validation:** require pre-classified input; bail with a clear `ValueError` if
  any record's `failure_mode` is `None`. Keep phases composable; no auto-classify.
- **Representative example selection:** deterministic — sort candidates by `question_id`
  (lexicographic), pick the first. Stable across re-runs; no metric-ranked selection
  (over-build for Phase 14).
- **Dominant pattern definition:** highest raw count across all clusters. Rate is
  available as a derived field but count drives ranking (sufficient for Phase 15; a
  count-based dominant cluster is unambiguous and needs no denominator decision).

| Approach                                                    | Module strategy                                                                                                                        | Cluster key                                                          | Model dimension                                                                                                                                           | Output                                             | Derived metrics                                                                          | Effort |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------ |
| A — Thin extension of `aggregate.py`                        | Add `triage_clusters()` to the existing `aggregate.py`; no new file                                                                    | `failure_mode` only (default)                                        | Ignored in groupby; preserved as metadata in representative example                                                                                       | JSON file + stdout summary                         | Count + rate (count / total); no per-cluster diagnostic metric                           | S      |
| B — New `triage.py` module + `triage_cli.py` (recommended)  | New `eval/triage.py` (pure function `compute_triage`) + `eval/triage_cli.py` (thin CLI); mirrors `inspect_cli.py` split                | `failure_mode` × `category` (default); configurable via `--group-by` | Multi-model awareness: per-cluster breakdown by model if multiple `run_id`/`model` values detected; model is a metadata field, not a default grouping key | JSON file (`results/triage.json`) + stdout summary | Count + rate + per-cluster representative `question_id` (+ question text from gold join) | M      |
| C — Fully configurable groupby + derived diagnostic metrics | Same new-module structure as B but adds configurable groupby axes (including `model`) and per-cluster abstain-precision derived metric | `failure_mode` × `category` × optional `model`                       | Model is a first-class configurable groupby key                                                                                                           | JSON file + stdout                                 | Count + rate + abstain-precision (for `abstention_error` clusters)                       | L      |

---

### Approach A — Thin extension of `aggregate.py`

**How it works.** Add a `triage_clusters()` function directly to the existing
`aggregate.py`. The function iterates over a `list[EvalRecord]`, groups by
`failure_mode`, counts, computes rate, picks one representative `question_id`. A new
`triage_cli.py` calls it and formats stdout. No new module boundary.

**Pros.** Smallest surface area; zero new files beyond `triage_cli.py`; no new import
graph edges.

**Cons.** `aggregate.py` currently owns a single, clean concern (verdict list →
three judge floats). Adding a JSONL-level groupby breaks that single-responsibility
boundary. It also makes the triage logic harder to unit-test in isolation (must import
the full `aggregate.py`). Finally, `failure_mode`-only grouping loses the
`category` dimension that the sprint plan explicitly calls out.

**Design axis choices:** new-vs-extend → extend; cluster key → `failure_mode` only;
model dimension → ignored; output → both; derived metrics → count + rate.

---

### Approach B — New `triage.py` + `triage_cli.py` (recommended)

**How it works.** A new `eval/triage.py` exports a pure function:

```
compute_triage(
    records: list[EvalRecord],
    gold: dict[str, Question],
    group_by: Literal["failure_mode", "failure_mode_category"] = "failure_mode_category",
) -> TriageReport
```

`TriageReport` and `TriageCluster` are frozen `@dataclass`s (mirroring
`InspectResult` / `ModelInspection`). `triage_cli.py` is a thin argparse wrapper that
loads the JSONL, loads gold, calls `compute_triage`, writes
`results/triage.json`, and prints a summary table to stdout. `--dry-run` prints the
summary and skips the write (same pattern as `rag-classify`).

The JSON artifact shape per cluster:

```json
{
  "failure_mode": "abstention_error",
  "category": "basic",
  "count": 42,
  "rate": 0.084,
  "representative_question_id": "qst_0007",
  "representative_question_text": "..."
}
```

Top-level `TriageReport` carries: `total_records`, `models_seen` (list of unique
model strings from records), `dominant_cluster` (the cluster with highest count),
`clusters` (all clusters, sorted by count descending). The JSON file is written
atomically (temp + rename, same as `rag-classify`).

Multi-model awareness: `models_seen` on the report, and each cluster records the
unique models present in that cluster as metadata. Model is NOT a grouping key by
default (avoids combinatorial explosion on a 3-model sweep; Phase 15 gets per-cluster
model context via `models_seen`).

**Pros.** Clean single-responsibility boundary; mirrors the house pattern
(`inspect_cli.py` split); `failure_mode` × `category` is the exact cluster key the
sprint plan names; testable pure function; stable JSON contract for Phase 15; no
changes to `aggregate.py`.

**Cons.** Two new files instead of one; slightly more effort than A.

**Design axis choices:** new module; `failure_mode` × `category` default; model →
metadata not groupby; JSON + stdout; count + rate + representative example.

---

### Approach C — Fully configurable groupby + derived diagnostic metrics

**How it works.** Extends Approach B with `--group-by model` making model a first-class
grouping axis, and adds a per-cluster `abstain_precision` derived metric (for
`abstention_error` clusters: fraction of abstentions that were on unanswerable
questions). Configurable via `--group-by {failure_mode,failure_mode_category,failure_mode_category_model}`.

**Pros.** Maximum flexibility for post-triage analysis; abstain-precision directly
answers the over-abstention finding quantitatively.

**Cons.** Abstain-precision requires the gold `expected_doc_ids` predicate (already
available via the gold join), but the derived-metric logic adds code that Phase 15
doesn't need and that can be added later. Model as a groupby key produces up to
3× as many clusters (one per model per failure_mode × category), making the "dominant
cluster" less actionable for Phase 15's one-issue-per-cluster heuristic. Violates
minimal-scope: the sprint plan explicitly puts derived diagnostic metrics in "Could".

**Design axis choices:** new module; configurable cluster key; model → optional
groupby; JSON + stdout; count + rate + abstain-precision.

---

## Recommended Approach

**Approach B.**

It is the only approach that hits all Must/Should criteria without over-build. The
`aggregate.py` extension (A) breaks an existing clean boundary for marginal effort
savings. The configurable groupby + derived metric (C) adds complexity Phase 15 doesn't
consume and contradicts the sprint's "Could" classification for derived metrics. Approach
B delivers the exact artifact shape Phase 15 needs (dominant cluster + per-cluster stats

- representative example), keeps the pure-function + thin-CLI house pattern, and stays
  offline-testable. The `failure_mode` × `category` default is the named cluster key from
  the sprint plan; model dimension is preserved as metadata without inflating the cluster
  count.

---

## Scope (MoSCoW)

| Priority         | Item                                                                                           |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| Must             | `rag-triage` CLI entry point in `pyproject.toml`                                               |
| Must             | `eval/triage.py` — pure `compute_triage()` returning `TriageReport` dataclass                  |
| Must             | `eval/triage_cli.py` — thin argparse CLI mirroring `inspect_cli.py` / `classify_cli.py`        |
| Must             | Cluster by `failure_mode` × `category` (default); per-cluster count + rate                     |
| Must             | Gold join: each cluster carries `representative_question_id` + `representative_question_text`  |
| Must             | Deterministic representative selection (sort by `question_id`, take first)                     |
| Must             | Machine-readable JSON output (`results/triage.json`, atomic temp+rename write)                 |
| Must             | Human-readable stdout summary (table of clusters sorted by count, dominant cluster called out) |
| Must             | Clear error if any record's `failure_mode` is `None` (guard against unclassified input)        |
| Must             | `tests/test_triage.py` — offline unit tests; no network, no LLM                                |
| Should           | `--dry-run` flag (print summary, skip JSON write)                                              |
| Should           | `models_seen` list on the report (multi-model JSONL awareness)                                 |
| Should           | Per-cluster `models_seen` metadata (which models appear in each cluster)                       |
| Should           | `dominant_cluster` pointer on `TriageReport`                                                   |
| Could            | Per-cluster derived diagnostic metric (e.g. abstain-precision for `abstention_error`)          |
| Could            | `--output` flag to override the default `results/triage.json` path                             |
| Could            | Markdown-rendered summary (for embedding in issue body — but that is Phase 15's concern)       |
| Won't (Phase 14) | GitHub Issue creation or drafting (Phase 15)                                                   |
| Won't (Phase 14) | Agent or LLM involvement of any kind                                                           |
| Won't (Phase 14) | Re-running the eval sweep                                                                      |
| Won't (Phase 14) | Any network call or external side effect                                                       |
| Won't (Phase 14) | Model as a groupby key (metadata only, not a cluster dimension)                                |
| Won't (Phase 14) | Doc-content enrichment or Phoenix hydration (Phase 16)                                         |
| Won't (Phase 14) | Configurable `--group-by` flag (fixed `failure_mode` × `category` default is sufficient)       |

---

## Open Questions

1. **Output path convention.** Should `results/triage.json` be the hardcoded default
   (matching `results/baseline.jsonl`) and overridable via `--output`, or is the path
   always caller-specified? The classify CLI defaults to overwriting its input; inspect
   defaults to `results/baseline.jsonl`. A fixed default with `--output` override is the
   most ergonomic for Phase 15 scripting.

2. **Empty-cluster behaviour.** If a `failure_mode` appears in the enum but has zero
   records in the input JSONL, should the triage report include an explicit zero-count
   cluster or omit it? Omitting keeps the report compact and Phase 15 simpler
   (only acts on clusters that exist); including gives a complete picture. The choice
   affects what Phase 15's "dominant cluster" logic needs to handle.

3. **Rate denominator.** Rate = count / what? Options: (a) total records in the JSONL
   (all models, all categories), (b) total records for the cluster's category, (c) total
   records for the cluster's `failure_mode`. Option (a) is simplest and consistent across
   clusters; options (b)/(c) are more diagnostic but require a design choice that should
   be explicit in DEFINE.

4. **Unclassified-record policy.** If some records have `failure_mode = None` (e.g. the
   JSONL is a mix of classified and raw records), should `rag-triage` fail fast (error on
   first None), skip-and-warn, or surface the None count as its own cluster? The
   recommended approach above is fail-fast, but this should be confirmed before coding.

5. **Phase 15 contract stability.** The JSON artifact is the contract Phase 15 consumes.
   Should the schema be versioned (a `schema_version` field on `TriageReport`) so Phase 15
   can assert compatibility, or is that premature for a two-phase sprint? Lightweight
   versioning (a single string field) costs almost nothing and prevents silent mismatches
   if Phase 14 is extended mid-sprint.

---

## Next Step

-> `/define sprint-5/phase-14-rag-triage`
