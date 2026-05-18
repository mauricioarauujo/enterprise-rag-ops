# DESIGN: sprint-1/phase-1-data-ingest — Data Ingest & Document Indexing

**Sprint/Phase:** sprint-1/phase-1-data-ingest | **Date:** 2026-05-17

## Architecture

Phase 1 is the project's first implementation phase: there is no `src/` and
`pyproject.toml` has an empty `dependencies` list. This design introduces the
`enterprise_rag_ops` package with a single subpackage, `ingest`, and wires two
Make targets around it. No retrieval, embedding, or eval code is in scope.

### Components

```
                   make download-data            make check-data
                          │                            │
                          ▼                            ▼
              ┌──────────────────────┐      ┌──────────────────────┐
              │  ingest.cli          │      │  tests/ingest/        │
              │  (orchestrator)      │      │  test_corpus.py       │
              └──────────┬───────────┘      │  (offline smoke)      │
                         │                  └──────────┬───────────┘
                         ▼                             │
        ┌────────────────────────────────┐             │
        │  ingest.loader                 │             │
        │  load_dataset(streaming=True,   │             │
        │  revision=SHA)                  │             │
        └────────────────┬───────────────┘             │
                         │ raw HF records               │
                         ▼                              │
        ┌────────────────────────────────┐              │
        │  ingest.adapters               │              │
        │  registry: {source_type: fn}   │              │
        │  raw record → Document         │              │
        └────────────────┬───────────────┘              │
                         │ Document objects             │
                         ▼                              │
        ┌────────────────────────────────┐              │
        │  ingest.sampler                │              │
        │  stratified, sort by doc_id,   │              │
        │  first DOCS_PER_SOURCE per src │              │
        └────────────────┬───────────────┘              │
                         │ bounded Document subset      │
                         ▼                              │
        ┌────────────────────────────────┐              │
        │  ingest.writer                 │              │
        │  → data/processed/corpus.jsonl │──────────────┘
        └────────────────────────────────┘     reads (offline)
```

### Data flow

1. `make download-data` invokes `ingest.cli`, passing `DOCS_PER_SOURCE` (env/Make
   param, default 100).
2. `loader` streams `onyx-dot-app/EnterpriseRAG-Bench` at the pinned revision SHA —
   no full materialization (NFR-2).
3. Each raw record is routed by its `source_type` to the matching adapter in the
   `adapters` registry; an unmapped `source_type` raises `UnknownSourceTypeError`
   (FR-3, AC-8). Adapters return validated `Document` instances (`schema.Document`).
4. `sampler` groups by `source_type`, sorts each group by `doc_id`, and takes the
   first `DOCS_PER_SOURCE` — deterministic, no RNG (FR-4, NFR-1).
5. `writer` serializes the subset to `data/processed/corpus.jsonl`, one
   `Document` per line, with stable key order and no timestamps (FR-6, NFR-1).
6. `cli` logs per-source counts at INFO via stdlib `logging` (NFR-5).
7. `make check-data` runs `tests/ingest/test_corpus.py`, which reads the JSONL file
   with no network access and asserts the five integrity properties (FR-7, NFR-3).

### Module decomposition (`src/enterprise_rag_ops/ingest/`)

| Module       | Responsibility                                                             |
| ------------ | -------------------------------------------------------------------------- |
| `schema.py`  | Pydantic `Document` model + `UnknownSourceTypeError`; validation boundary. |
| `config.py`  | `DOCS_PER_SOURCE` default, dataset id, pinned revision SHA, output path.   |
| `loader.py`  | Thin wrapper over `datasets.load_dataset(streaming=True, revision=SHA)`.   |
| `adapters/`  | One adapter per source type + `REGISTRY` dict keyed by `source_type`.      |
| `sampler.py` | Stratified deterministic subset selection.                                 |
| `writer.py`  | Deterministic JSONL serialization of `Document` objects.                   |
| `cli.py`     | Orchestrator + `logging` setup; the `make download-data` entrypoint.       |

The `adapters/` subpackage holds `base.py` (adapter protocol + `REGISTRY`) and one
module per source type. Sources are confirmed at ingest time; the BRAINSTORM lists
9 (Confluence, Jira, Slack, Linear, Gmail, GDrive, GitHub, HubSpot, Fireflies). If
several sources share an identical raw field shape, the implementer may collapse
them onto one shared adapter function registered under multiple keys — the registry
is keyed by `source_type`, so this is a registration detail, not a design change.

## File Manifest

| File                                                 | Change                                                                      | Owner (agent / direct) | Phase order |
| ---------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------- | ----------- |
| `src/enterprise_rag_ops/__init__.py`                 | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/__init__.py`          | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/schema.py`            | create                                                                      | direct                 | 1           |
| `src/enterprise_rag_ops/ingest/config.py`            | create                                                                      | direct                 | 2           |
| `src/enterprise_rag_ops/ingest/loader.py`            | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/adapters/__init__.py` | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/adapters/base.py`     | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/adapters/<source>.py` | create (one per source type)                                                | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/sampler.py`           | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/writer.py`            | create                                                                      | direct                 | 3           |
| `src/enterprise_rag_ops/ingest/cli.py`               | create                                                                      | direct                 | 3           |
| `tests/__init__.py`                                  | create                                                                      | direct                 | 6           |
| `tests/ingest/__init__.py`                           | create                                                                      | direct                 | 6           |
| `tests/ingest/test_schema.py`                        | create                                                                      | direct                 | 6           |
| `tests/ingest/test_adapters.py`                      | create                                                                      | direct                 | 6           |
| `tests/ingest/test_sampler.py`                       | create                                                                      | direct                 | 6           |
| `tests/ingest/test_writer.py`                        | create                                                                      | direct                 | 6           |
| `tests/ingest/test_corpus.py`                        | create                                                                      | direct                 | 6           |
| `tests/ingest/fixtures/corpus_valid.jsonl`           | create                                                                      | direct                 | 6           |
| `tests/ingest/fixtures/corpus_corrupt_*.jsonl`       | create (corruption fixtures for AC-5)                                       | direct                 | 6           |
| `pyproject.toml`                                     | edit (add `datasets`, `pydantic` with bounds; `[project.scripts]` optional) | direct                 | 2           |
| `Makefile`                                           | edit (add `download-data`, `check-data` targets)                            | direct                 | 4           |
| `docs/dataset.md`                                    | edit (pinned SHA, per-source field mapping, sampling contract)              | direct                 | 7           |

**Owner note.** Every implementation file is `direct`. The agent registry contains
only workflow agents (`brainstorm-agent`, `define-agent`, `design-agent`),
`kb-architect`, and `code-reviewer` — there is no ingest/data specialist. `direct`
is correct for Phase 1. `code-reviewer` still reviews the result at `/review`; it
is a workflow agent, not a manifest owner. See Infrastructure Gaps for a
non-blocking suggestion about a future data/ingest specialist.

## Implementation Phases

Ordered per the convention (data schema → config → core logic → eval wiring →
observability → tests → docs). Phase 1 has no `eval/` or `observability/` work, so
those convention slots are empty here.

1. **Data schema / dataset loading.** `ingest/schema.py` — Pydantic `Document`
   (`id`, `source_type`, `text`, `metadata`), non-empty validators for `id` and
   `text` (FR-2, AC-7), and `UnknownSourceTypeError` (FR-3, AC-8). This is the
   contract every other module depends on, so it lands first.
2. **Config.** `pyproject.toml` dependency edits (`datasets`, `pydantic`,
   version-bounded — NFR-4, AC-10) and `ingest/config.py` (`DOCS_PER_SOURCE`
   default 100, dataset id, pinned revision SHA placeholder, output path). The SHA
   is captured during `/implement` by inspecting the HF repo (DEFINE Q1).
3. **Core module logic (`src/`).** `loader.py`, `adapters/` (base + registry +
   per-source modules), `sampler.py`, `writer.py`, `cli.py`, and the `__init__.py`
   files. `cli.py` is built last in this group since it orchestrates the others
   and owns `logging` setup (NFR-5).
4. **(eval harness — not applicable to Phase 1.)** Instead, the Make wiring lands
   here: `Makefile` gains `download-data` (runs `ingest.cli`, accepts
   `DOCS_PER_SOURCE`) and `check-data` (runs the offline smoke test) — FR-1, FR-5,
   FR-7.
5. **(observability hooks — not applicable.)** NFR-5 logging is satisfied inline in
   `cli.py` under step 3; there is no separate `observability/` module this phase.
6. **Tests.** Unit tests mirror each `src/` module (`test_schema.py`,
   `test_adapters.py`, `test_sampler.py`, `test_writer.py`) plus the offline corpus
   smoke test `test_corpus.py` (FR-7, AC-5, AC-6) and its JSONL fixtures, including
   deliberately corrupted fixtures for AC-5. `loader.py` and `cli.py` are exercised
   indirectly; no live-HF test runs in `make verify` or `make check-data`.
7. **Docs + ADR.** Update `docs/dataset.md` with the pinned revision SHA, the
   per-source raw→`Document` field mapping, and the deterministic sampling contract
   (FR-8, AC-9). **No ADR is written in Phase 1** — ADR-001 and ADR-002 belong to
   Phase 2 per `SPRINT.md` and are not scheduled here.

### Requirement → manifest coverage

| Requirement | Covered by                                                               |
| ----------- | ------------------------------------------------------------------------ |
| FR-1        | `loader.py`, `cli.py`, `Makefile` (`download-data`)                      |
| FR-2        | `schema.py`                                                              |
| FR-3        | `adapters/base.py` + per-source adapters, `schema.py` error              |
| FR-4        | `sampler.py`                                                             |
| FR-5        | `config.py`, `cli.py`, `Makefile`                                        |
| FR-6        | `writer.py`                                                              |
| FR-7        | `tests/ingest/test_corpus.py` + fixtures, `Makefile` (`check-data`)      |
| FR-8        | `docs/dataset.md`                                                        |
| NFR-1       | `sampler.py` (sort), `writer.py` (stable serialization)                  |
| NFR-2       | `loader.py` (streaming), `sampler.py` (bounded `take`)                   |
| NFR-3       | `test_corpus.py` (offline), `Makefile` (`check-data`)                    |
| NFR-4       | `pyproject.toml`                                                         |
| NFR-5       | `cli.py` (`logging`)                                                     |
| NFR-6       | package layout under `src/enterprise_rag_ops/ingest/`, mirrored `tests/` |

All 8 FR and 6 NFR map to at least one manifest entry.

## Infrastructure Gaps

| Gap Type           | Area                     | Detail                                                                                                                                                                             | Recommendation                                                                                                              |
| ------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Missing domain     | HF `datasets` / Pydantic | No KB domain covers them, and none is needed — well-trodden APIs; field-level notes go in `docs/dataset.md`.                                                                       | None — not a blocker (confirmed by DEFINE/BRAINSTORM).                                                                      |
| Missing domain     | `rag-retrieval`          | `_index.yaml` `domains` is empty; no `rag-retrieval` KB exists. Not needed for Phase 1 (no chunking/retrieval).                                                                    | `/new-kb rag-retrieval` **before Phase 2** — already tracked in `SPRINT.md` § Sprint-Wide KB & Research. Not a Phase 1 gap. |
| Missing concept    | n/a                      | No KB domain is consumed by Phase 1, so concept coverage is vacuously satisfied.                                                                                                   | None.                                                                                                                       |
| Missing specialist | data / ingest            | No ingest/data specialist agent exists; all manifest files are `direct`. Phase 1 is the first and only ingest workload, so one occurrence — below the ≥2 self-improvement trigger. | None blocking. Non-blocking watch item — see Risks.                                                                         |

**Three-layer check result.** (1) _Domain existence_ — every Phase 1 technology
area either has sufficient ambient coverage (HF `datasets`, Pydantic) or is an
out-of-scope future need (`rag-retrieval`, Phase 2). (2) _Concept coverage_ — no KB
domain is read by this phase, so there is nothing to under-cover. (3) _Agent
alignment_ — no specialist owns Phase 1 files; `direct` ownership is correct and
the `code-reviewer` workflow agent's review scope needs no `kb_domains` change.

**No gap blocks Phase 1.** The single forward-looking item (`rag-retrieval` KB) is
a Phase 2 prerequisite already recorded in `SPRINT.md`.

## Risks & Trade-offs

- **Adapter effort is S→M, not S (DEFINE Q2).** Per-source raw field schemas are
  reverse-engineered during `/implement`. If sources are more heterogeneous than
  expected, `adapters/` grows. Mitigation: the registry pattern isolates each
  source; a thin shared adapter can back several `source_type` keys when shapes
  match. No design change needed if the count or shapes differ from the BRAINSTORM's
  nine.
- **Pinned SHA captured late.** `config.py` ships with a SHA placeholder filled in
  at `/implement` time (DEFINE Q1). Until then, `download-data` cannot run
  reproducibly. Acceptable — it is a one-line capture, and `check-data` is offline
  so CI is unaffected.
- **Deterministic-output fragility (NFR-1, AC-4).** Byte-identical re-runs require
  stable JSON key order, no timestamps, and a stable sort key. `writer.py` must use
  a fixed `Document` field order and `sort_keys`-style serialization; `sampler.py`
  must sort by `doc_id` with a total order (ties broken deterministically). This is
  the most likely source of a silent AC-4 failure — `test_writer.py` should assert
  byte-identity directly.
- **`metadata: dict` is untyped (BRAINSTORM, DEFINE Q5).** Deferring per-source
  typing keeps Phase 1 small but means schema drift in `metadata` is silent until
  Phase 2 consumes it. Accepted trade-off; `doc_id` stability inside `metadata` is
  the one guaranteed contract.
- **No ADR this phase.** The acquisition choice (`datasets` streaming + revision
  pin) and the `Document` model are real architectural decisions, but `SPRINT.md`
  deliberately places ADR-001/ADR-002 in Phase 2. The _why_ for those choices is
  captured in `BRAINSTORM.md` § Approaches Considered and will be folded into the
  Phase 2 ADRs — no ADR is written or scheduled here.
- **No data/ingest specialist (non-blocking).** Phase 1 is the only ingest
  workload in the current sprint plan, so a specialist agent is not yet justified
  (one occurrence, below the ≥2 trigger). If a later sprint adds more ingest
  surface (new datasets, incremental refresh, format converters), revisit with
  `/new-agent`. Flagged as a watch item, not an action.

## Next Step

→ `/implement sprint-1/phase-1-data-ingest` — no infrastructure gap blocks
implementation; capture the pinned HF revision SHA as the first step.
