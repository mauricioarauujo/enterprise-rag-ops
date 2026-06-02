# DEFINE: sprint-5/phase-14-rag-triage — rag-triage Core

**Sprint/Phase:** sprint-5/phase-14-rag-triage | **Date:** 2026-06-01
**Approach:** B (from BRAINSTORM) — new `eval/triage.py` pure core + thin `eval/triage_cli.py`.

## Problem

`rag-classify` already tags every `EvalRecord` with a `failure_mode`, but the harness
has no step that **aggregates** those tags. A human reading the JSONL must eyeball 500×3
records to find the dominant failure cluster (Sprint 4 surfaced over-abstention by hand).
Phase 15 (GitHub Issues) needs a **deterministic, machine-readable** cluster artifact to
draft from — there is no such contract today. Phase 14 fills exactly that gap: a pure,
read-only, offline groupby-aggregate over the classified JSONL → `results/triage.json` +
a stdout summary. No re-run, no network, no LLM, no side effects.

## Users / Stakeholders

- **Phase 15 (`rag-issues`, this sprint)** — the primary consumer. Reads `triage.json`'s
  `dominant_cluster` + per-cluster stats + representative example to draft one Issue per
  cluster. Needs a stable, versioned schema.
- **Maintainer (Mauricio) at the CLI** — runs `rag-triage` after a sweep+classify to see
  the failure distribution at a glance (stdout table) and to decide where to invest.
- **Phase 16 (Phoenix enrichment)** — downstream; consumes the same artifact's
  `representative_question_id` to deep-link traces. Out of scope here, but informs the
  schema contract.

## Requirements

### Functional

- **FR-1** Expose a pure function `compute_triage(records, gold) -> TriageReport` in a new
  `src/enterprise_rag_ops/eval/triage.py`. No I/O, no network, no LLM, no mutation of inputs.
- **FR-2** `TriageReport` and `TriageCluster` are frozen `@dataclass`s (`frozen=True,
slots=True`), mirroring `InspectResult` / `ModelInspection` in `inspect_cli.py`.
- **FR-3** Cluster key = (`failure_mode`, `category`) using **the record's own `category`**
  field (authoritative; classify already resolved gold). One `TriageCluster` per distinct
  observed key.
- **FR-4** Each `TriageCluster` carries: `failure_mode`, `category`, `count`, `rate`,
  `representative_question_id`, `representative_question_text`, `models_seen`
  (sorted unique `gen_ai.request.model` strings in that cluster).
- **FR-5** `rate = count / total_records` (denominator = all records in the JSONL — see
  Resolved Decisions §3). With `total_records == 0`, the report is empty (`clusters == []`,
  `dominant_cluster is None`); no division occurs.
- **FR-6** Clusters sorted by `count` descending, tiebroken by (`failure_mode`, `category`)
  lexicographic ascending. `dominant_cluster` = `clusters[0]` (None when empty).
- **FR-7** Representative example: among a cluster's records, sort by `question_id`
  lexicographic and take the first; `representative_question_text` from the gold join
  (`gold[question_id].question`); empty string if the id is absent from gold.
- **FR-8** `TriageReport` top-level fields: `schema_version: str`, `total_records: int`,
  `models_seen: list[str]` (sorted unique across all records), `dominant_cluster:
TriageCluster | None`, `clusters: list[TriageCluster]`.
- **FR-9** Fail-fast: if **any** record has `failure_mode is None`, raise `ValueError`
  naming the first offending `question_id` (require pre-classified input).
- **FR-10** Provide `eval/triage_cli.py` — a thin argparse wrapper (`rag-triage`) that:
  loads the JSONL via `EvalRecord.model_validate_json`, loads gold via `load_questions`,
  calls `compute_triage`, writes `results/triage.json` atomically (temp file in the target
  dir + `os.replace`), and prints a summary table to stdout.
- **FR-11** CLI flags mirror the house pattern: `--results` (input JSONL, required),
  `--output` (default `results/triage.json`), `--dry-run` (print summary, write nothing),
  `--questions-revision` (default `config.DATASET_REVISION`).
- **FR-12** Register `rag-triage = "enterprise_rag_ops.eval.triage_cli:main"` in
  `pyproject.toml` `[project.scripts]`.
- **FR-13** Serialize `TriageReport` to JSON via a deterministic dataclass→dict dump
  (stable key order, clusters in sorted order) so byte output is reproducible across runs.

### Non-functional

- **NFR-1 Purity / offline.** `triage.py` performs zero I/O, network, or LLM calls. All
  network/gold-stream and file writes live in `triage_cli.py`. Tests run fully offline.
- **NFR-2 Determinism.** Same `(records, gold)` → identical `TriageReport` and identical
  `triage.json` bytes (FR-6, FR-7, FR-13). No reliance on dict/set iteration order.
- **NFR-3 House structure.** Pure-core + thin-CLI split mirrors `inspect_cli.py` /
  `classify_cli.py`; atomic write mirrors `classify_cli.py` (temp + `os.replace`, cleanup
  on failure).
- **NFR-4 No side effects beyond the artifact.** Only file written is `--output` (and its
  temp); `--dry-run` writes nothing. Inputs are never mutated.
- **NFR-5 Test mirror.** New module → `tests/eval/test_triage.py` (with `tests/eval/__init__.py`),
  offline, no network/LLM. `make lint test` is the gate.
- **NFR-6 Multi-model safety.** A JSONL spanning the 3-way sweep must not inflate clusters;
  model is metadata (`models_seen`), never a groupby axis (Won't, BRAINSTORM).
- **NFR-7 Schema stability.** `schema_version` is a literal constant in `triage.py`; Phase
  15 can assert against it.

## Acceptance Criteria

Each AC is checkable by a unit test in `tests/eval/test_triage.py`.

- **AC-1 Cluster key.** Given records across ≥2 (`failure_mode`, `category`) pairs,
  `compute_triage` returns exactly one cluster per distinct observed pair, each with the
  correct `count`.
- **AC-2 Record-category authoritative.** A record whose `category` differs from its gold
  question's `category` is clustered under the **record's** `category` (FR-3).
- **AC-3 Rate.** For a cluster of count `c` over `N` total records, `rate == c / N`
  (float); summing `count` over clusters equals `N`.
- **AC-4 Empty input.** `compute_triage([], gold)` returns `total_records == 0`,
  `clusters == []`, `dominant_cluster is None` — no `ZeroDivisionError`.
- **AC-5 Sort + tiebreak.** Clusters are ordered by `count` desc; two equal-count clusters
  are ordered by (`failure_mode`, `category`) lexicographic ascending (FR-6).
- **AC-6 Dominant cluster.** `dominant_cluster` is the highest-count cluster (== `clusters[0]`),
  and `None` only when input is empty.
- **AC-7 Representative determinism.** For a cluster with `question_id`s
  `{qst_0009, qst_0002, qst_0005}`, `representative_question_id == "qst_0002"` and the text
  matches `gold["qst_0002"].question`. Re-running yields the same pick.
- **AC-8 Missing-gold representative.** If the chosen representative `question_id` is absent
  from `gold`, `representative_question_text == ""` (empty), no exception.
- **AC-9 Fail-fast on unclassified.** `compute_triage` raises `ValueError` (message names the
  first offending `question_id`) when any record has `failure_mode is None`.
- **AC-10 models_seen.** With records from ≥2 distinct `gen_ai.request.model` values in one
  cluster, that cluster's `models_seen` is the sorted unique list; report-level `models_seen`
  is the sorted unique across all records.
- **AC-11 schema_version.** `TriageReport.schema_version` equals the module constant and is
  present in the serialized `triage.json`.
- **AC-12 JSON artifact shape + atomic write.** `triage_cli.main()` writes `--output` whose
  JSON parses to the documented shape (`schema_version`, `total_records`, `models_seen`,
  `dominant_cluster`, `clusters[]` with the FR-4 keys). Write is atomic (no partial file on
  simulated write failure; temp file cleaned up).
- **AC-13 Deterministic bytes.** Two `compute_triage` + serialize passes over the same input
  produce byte-identical JSON (FR-13).
- **AC-14 stdout summary.** `--dry-run` prints a cluster table (sorted by count, dominant
  called out) and writes **no** file; exit code 0.
- **AC-15 Offline guarantee.** The full `tests/eval/test_triage.py` suite passes with no
  network access and no LLM client constructed.
- **AC-16 Console script.** `rag-triage` resolves to `eval.triage_cli:main` and
  `rag-triage --help` exits 0.

## Resolved Decisions

The 5 BRAINSTORM open questions — all resolved to their recommended defaults; none blocked
scoring, so none was escalated as a clarifying question.

1. **Output path.** Fixed default `results/triage.json`, overridable via `--output`. Mirrors
   `rag-inspect`'s `results/baseline.jsonl` default and `rag-classify`'s `--output`. **Confirmed.**
2. **Empty-cluster behaviour.** Omit any (`failure_mode`, `category`) combo with zero records —
   only observed clusters are emitted. **Confirmed.** _Phase 15 impact:_ `dominant_cluster` is
   derived from observed clusters only and is `None` on empty input; Phase 15 must handle the
   absence of a never-observed mode (no zero-count rows to suppress).
3. **Rate denominator.** `rate = count / total_records` (all records in the JSONL — option a).
   Simplest and consistent across clusters; per-category/per-mode denominators deferred (they
   belong to the "Could" derived-metrics bucket). **Confirmed.**
4. **Unclassified-record policy.** Fail-fast `ValueError` if any record's `failure_mode is None`.
   Keeps phases composable (`rag-classify` must run first); no skip-and-warn, no None cluster.
   **Confirmed.**
5. **Schema versioning.** Add `schema_version: str` to `TriageReport` (module constant, e.g.
   `"1.0"`). Near-zero cost; lets Phase 15 assert compatibility. **Confirmed.**

## Dependencies + Infrastructure Readiness

| Dependency                                            | Type       | KB domain                           | Specialist   | Status                                                                                          |
| ----------------------------------------------------- | ---------- | ----------------------------------- | ------------ | ----------------------------------------------------------------------------------------------- |
| `eval/records.py` (`EvalRecord`)                      | module     | rag-eval (`eval-record-schema`)     | kb-architect | Ready — fields confirmed (`question_id`, `category`, `failure_mode`, `gen_ai.request.model`, …) |
| `eval/questions.py` (`load_questions`, `Question`)    | module     | rag-eval                            | kb-architect | Ready — gold join via `{q.question_id: q}` dict, as in `classify_cli.py`                        |
| `eval/failure_taxonomy.py` (`FailureMode`)            | module     | observability (`failure-taxonomy`)  | kb-architect | Ready — 5-label enum; triage consumes the produced string labels                                |
| `inspect_cli.py` / `classify_cli.py` (pattern source) | module     | rag-eval                            | —            | Ready — pure-core + thin-CLI + atomic-write patterns to mirror                                  |
| None/empty-denominator convention                     | KB concept | rag-eval (`none-empty-denominator`) | —            | Ready — applied to FR-5 (zero-total → empty report)                                             |
| `eval-triage` cluster→issue contract                  | KB concept | rag-eval                            | kb-architect | **Deferred (not a Phase 14 gap)** — lands after ADR-0009 in Phase 15, per BRAINSTORM            |
| `pyproject.toml` `[project.scripts]`                  | config     | —                                   | —            | Ready — append `rag-triage` alongside existing scripts                                          |

**No new KB or `--deep-research` needed.** Coverage holds: the triage pattern is a groupby-
aggregate over a known schema (`rag-eval` + `observability` concepts cover it). The only thin
spot (the cluster→issue idempotency contract) is correctly owned by Phase 15. No new agent or
command required.

## Out of Scope (Won't — Phase 14)

- GitHub Issue creation/drafting (Phase 15); any LLM or agent involvement.
- Re-running the eval sweep; any network call or external side effect.
- Model as a groupby key (metadata only).
- Doc-content / Phoenix enrichment (Phase 16).
- Configurable `--group-by` flag and per-cluster derived diagnostic metrics (e.g.
  abstain-precision) — "Could", deferred.

## Clarity Score

| Dimension        | Score          | Note                                                                                                      |
| ---------------- | -------------- | --------------------------------------------------------------------------------------------------------- |
| Problem          | 3              | Root cause + evidence: classified JSONL exists but no aggregator; Sprint-4 over-abstention found by hand. |
| Users            | 3              | Named roles with workflow impact: Phase 15 consumer (primary), maintainer at CLI, Phase 16 deep-link.     |
| Success          | 3              | 16 falsifiable ACs, each unit-testable; deterministic bytes + atomic write are measurable.                |
| Scope            | 3              | MoSCoW inherited from BRAINSTORM with explicit Won't list reproduced.                                     |
| Constraints      | 3              | All named: pure/offline, determinism, house split, atomic write, test mirror, multi-model metadata-only.  |
| **Total: 15/15** | **PASS (≥12)** |                                                                                                           |

## Next Step

→ `/design sprint-5/phase-14-rag-triage`
