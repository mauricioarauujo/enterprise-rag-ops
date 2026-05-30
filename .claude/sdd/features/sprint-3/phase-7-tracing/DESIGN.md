# DESIGN: sprint-3/phase-7-tracing — Phoenix Replay Exporter & ADR-0004 Acceptance

**Sprint/Phase:** sprint-3/phase-7-tracing | **Date:** 2026-05-27

This DESIGN is the **sole implement contract** — the implement stage runs in
Antigravity/Gemini against it with no other context. Every module below carries its
signatures, attribute keys, and the FR/AC it satisfies so an executor needs no extra
discovery. Phoenix-API facts are grounded against a Context7 verification done at design
time (2026-05-27); residual uncertainties are flagged inline as **[CONFIRM @impl]**.

---

## Architecture

### Module shape

```
src/enterprise_rag_ops/observability/
├── __init__.py            # package marker; re-exports replay_jsonl
├── attributes.py          # pure mapping: EvalRecord → OTEL/OpenInference attr dicts (no Phoenix import)
├── phoenix_client.py      # THE SEAM (NFR-3): all Phoenix/OTEL specifics behind one boundary
├── exporter.py            # replay_jsonl orchestration: parse → reset → build spans → write scores
└── cli.py                 # rag-export-traces entry point (argparse, mirrors eval/cli.py)

infra/phoenix/
└── docker-compose.yml     # single arizephoenix/phoenix container, pinned tag, SQLite-on-volume

tests/observability/
├── __init__.py
└── test_exporter.py       # fully offline; fake tracer + fake client; 2-record JSONL
```

### Why this shape (the seam — NFR-3)

The DEFINE requires all Phoenix specifics localized so a future tool swap (back to
Langfuse on a bigger box, or the ADR-0004 Phase 3 OTEL-Collector fan-out) is a contained
change, not a rewrite. The module is split along the **vendor boundary**, mirroring the
house `eval/interfaces.py` Protocol-seam precedent:

- **`attributes.py`** — pure functions, zero Phoenix/OTEL import. Maps an `EvalRecord`
  into plain `dict[str, Any]` attribute bundles (one per span) keyed by the ADR-0004
  OTEL-GenAI / OpenInference names. This is where the `None`-safe cost rule and the
  `retrieval.documents.{i}.*` flattening live. **Tool-agnostic** — survives any backend
  swap untouched. Trivially unit-testable without a fake tracer.
- **`phoenix_client.py`** — the **only** module that imports `phoenix.otel` /
  `phoenix.client`. Wraps: tracer registration, span creation + `span_id` capture,
  project reset (FR-4), and the `log_span_annotations_dataframe` write-back (FR-5).
  Exposes a small `TracerHandle` / `ScoreSink` surface the exporter calls. A swap edits
  this file only.
- **`exporter.py`** — orchestration. Knows the _shape_ of the work (parse JSONL → reset
  project → per record build CHAIN→RETRIEVER→LLM(gen)→LLM(judge) → collect `span_id`s →
  assemble per-metric annotation rows → flush scores) but delegates every vendor call to
  `phoenix_client` and every attribute computation to `attributes`. Takes its Phoenix
  collaborators **by injection** so tests pass fakes (NFR-1).
- **`cli.py`** — argparse + env-var resolution; wires `phoenix_client` to `exporter`.

### Data flow

```
results/baseline.jsonl  (read-only input contract — EvalRecord per line, NFR-2)
        │  exporter.replay_jsonl(path, sink, *, project, dry_run)
        ▼
  for each line → EvalRecord.model_validate_json(line)        # pydantic parse
        │
        ├─ (once, before ingest) sink.reset_project(project)  # FR-4 idempotency
        ▼
  attributes.build_span_attrs(record) ──► {chain, retriever, generation, judge} attr dicts
        │
        ▼
  sink.start_span(CHAIN, attrs) ── as parent ─┐
        ├─ child RETRIEVER span (attrs)        │  span_ids captured in-process
        ├─ child LLM "generation" span (attrs) │  (FR-4): {role → span_id}
        └─ child LLM "judge" span (attrs)      ┘
        │
        ▼
  attributes.build_score_rows(record, span_ids) ──► per-metric DataFrame rows
        │   (None floats skipped; metric → semantically-aligned span_id)
        ▼
  sink.log_scores(rows_by_metric)   # log_span_annotations_dataframe, annotator_kind="CODE"
        │
        ▼
  sink.flush()   # ensure spans/scores delivered before process exit
```

The exporter makes **no LLM calls** — it replays existing records (NFR-1) — and imports
**nothing** under `eval/` (NFR-2; it depends only on `eval.records.EvalRecord` as a
read-only type, which is the declared input contract).

---

## File Manifest

| File                                                     | Change | Owner  | Phase order | Purpose / key signatures                                                                                                                                                                                                                   | FR / AC                  |
| -------------------------------------------------------- | ------ | ------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------ |
| `pyproject.toml`                                         | edit   | direct | 1           | Add runtime deps `arize-phoenix-otel>=0.16.0`, `arize-phoenix-client`, `pandas>=2.0,<3.0` (see Risks). Add `[project.scripts]` `rag-export-traces = "enterprise_rag_ops.observability.cli:main"`.                                          | FR-6, NFR-4              |
| `infra/phoenix/docker-compose.yml`                       | create | direct | 1           | One `arizephoenix/phoenix:version-X.X.X` service (pinned, see below); ports `6006:6006` + `4317:4317`; `PHOENIX_WORKING_DIR=/mnt/data`; named volume `phoenix-data:/mnt/data`. No auth, no Postgres.                                       | FR-1, AC-1               |
| `Makefile`                                               | edit   | direct | 1, 3        | Add `trace-up` (phase 1), `export-traces` (phase 3), optional `trace-reset` (fallback). Add all three to `.PHONY`. `RESULTS_FILE ?= results/baseline.jsonl`.                                                                               | FR-1, FR-7, AC-1, AC-7   |
| `src/enterprise_rag_ops/observability/__init__.py`       | create | direct | 2           | Package marker; `from .exporter import replay_jsonl` re-export. Module docstring naming `observability/` as the tool-swap seam (NFR-3).                                                                                                    | NFR-3                    |
| `src/enterprise_rag_ops/observability/attributes.py`     | create | direct | 2           | Pure mapping, no vendor import. `build_span_attrs(record) -> SpanAttrBundle`; `build_score_rows(record, span_ids) -> dict[str, list[ScoreRow]]`. Houses `None`-safe cost rule + retrieval flattening + `--enrich-from-index` seam comment. | FR-3, FR-5, FR-12        |
| `src/enterprise_rag_ops/observability/phoenix_client.py` | create | direct | 2           | THE SEAM. `register_tracer(project, endpoint) -> TracerHandle`; `reset_project(project)`; `start_span(...)` capturing `span_id`; `log_scores(rows_by_metric)` via `log_span_annotations_dataframe`; `flush()`.                             | FR-3, FR-4, FR-5, NFR-3  |
| `src/enterprise_rag_ops/observability/exporter.py`       | create | direct | 2           | `replay_jsonl(path, sink, *, project, dry_run=False) -> ReplaySummary`. Orchestrates parse→reset→span-tree→score-write. Injectable `sink` for offline tests.                                                                               | FR-2, FR-4, FR-5, NFR-2  |
| `tests/observability/__init__.py`                        | create | direct | 2           | Package marker for the mirrored test dir (matches `tests/eval/` convention).                                                                                                                                                               | FR-10                    |
| `tests/observability/test_exporter.py`                   | create | direct | 2           | Fully offline. Fake `TracerHandle` + `ScoreSink` record calls in-memory. 2-record fixture JSONL (one with `None` cost + `None` metric). Asserts (a)–(f) of FR-10. **No cassette, no network, no Phoenix.**                                 | FR-10, NFR-1, AC-2..AC-5 |
| `src/enterprise_rag_ops/observability/cli.py`            | create | direct | 3           | `main(argv=None) -> int`, mirrors `eval/cli.py`. Flags `--results`, `--endpoint`, `--project`, `--dry-run`. Endpoint precedence: flag > `PHOENIX_COLLECTOR_ENDPOINT` > `http://localhost:6006`. Key env-only.                              | FR-6, FR-11, AC-6, AC-13 |
| `.gitignore`                                             | edit   | direct | 4           | Add `!results/baseline.jsonl` after the existing `!results/baseline.md` (line ~62).                                                                                                                                                        | FR-8, AC-8               |
| `results/baseline.jsonl`                                 | commit | direct | 4           | Commit the existing Phase 6 baseline (~999 records). Confirm size acceptable; sample fallback if it bloats clone (see Risks).                                                                                                              | FR-8, AC-8, AC-11        |
| `docs/adr/0004-observability-tool.md`                    | edit   | direct | 5           | Status `proposed → accepted`; append `## Acceptance Note` (Phoenix, hardware rationale, pinned tag, unchanged OTEL wire format). No new ADR number.                                                                                        | FR-9, AC-9               |

**Owner = `direct` for every entry.** No specialist agent exists for observability and
none is warranted — see Infrastructure Gaps (single additive module over a documented
input contract).

### Pinned facts (resolve DEFINE deferrals)

- **Phoenix image tag (FR-1):** pin `arizephoenix/phoenix:version-X.X.X`, a specific
  stable tag, **never `:latest`**. **[CONFIRM @impl]** the exact latest-stable patch in
  the v13+ era at implement time and write it into both the compose file and the ADR
  Acceptance Note. Record the same tag in both places.
- **Persistence (FR-1):** `PHOENIX_WORKING_DIR=/mnt/data` env var pointing at a mounted
  named docker volume (`phoenix-data`). Phoenix writes its SQLite DB there; the volume
  survives `docker compose down` (but not `down -v` — that is the `trace-reset` fallback).
- **Packages (NFR-4):** `arize-phoenix-otel>=0.16.0` (provides `phoenix.otel.register`
  AND re-exports OpenInference context managers + semantic conventions at >=0.16.0 — so
  **no separate `openinference-instrumentation` / `-semantic-conventions` packages**) +
  `arize-phoenix-client` (provides `phoenix.client.Client`). The Phoenix **server** is the
  docker image, **not** a Python dep — do **not** add `arize-phoenix` (full server pkg).
- **pandas:** the verified score-write-back path
  `Client().spans.log_span_annotations_dataframe(dataframe=df, ...)` takes a **pandas
  DataFrame**. `pandas` is **not** currently a project dep (checked `pyproject.toml`) — so
  this phase introduces `pandas>=2.0,<3.0`. **Decision: add pandas** (the documented,
  verified path; lowest-risk for the implementer). **[CONFIRM @impl]** whether a row-wise
  client method exists that would avoid the dep; if so, prefer it and drop pandas — but do
  **not** block on it. Recorded in the infra-gap table.

### OTEL / OpenInference attribute keys (FR-3 — the span-attribute spec)

Names follow the ADR-0004 mapping table; keys not in that table are pinned here against
the OpenInference spec. `attributes.build_span_attrs` returns these.

**Root `chain` span** (OpenInference span kind `CHAIN`; name e.g. the question id):

| Attribute               | Source field                   |
| ----------------------- | ------------------------------ |
| `question_id`           | `record.question_id`           |
| `category`              | `record.category`              |
| `run_id`                | `record.run_id`                |
| `k`                     | `record.k`                     |
| `gen_ai.request.model`  | `record.gen_ai.request.model`  |
| `gen_ai.system`         | `record.gen_ai.system`         |
| `gen_ai.operation.name` | `record.gen_ai.operation.name` |

**Child `retriever` span** (OpenInference span kind `RETRIEVER`): for each `i, doc_id` in
`enumerate(record.retrieval_ranked_ids)` set **id + rank only**:

| Attribute                               | Value    |
| --------------------------------------- | -------- |
| `retrieval.documents.{i}.document.id`   | `doc_id` |
| `retrieval.documents.{i}.document.rank` | `i`      |

**NO** `retrieval.documents.{i}.document.content` and **NO** `.document.score`
(`EvalRecord` does not persist them — ADR-0007; id+rank-only fidelity, BRAINSTORM
Decision 3). The `--enrich-from-index` re-hydration path (FR-12) is documented here in a
code comment as the named, unbuilt seam — no LanceDB/BM25 import.

**Child `llm` "generation" span** (OpenInference span kind `LLM`), from
`record.generation` (`CallStats`):

| Attribute                    | Source                                          |
| ---------------------------- | ----------------------------------------------- |
| `gen_ai.request.model`       | `generation.model`                              |
| `gen_ai.system`              | `generation.system`                             |
| `gen_ai.operation.name`      | `"chat"`                                        |
| `gen_ai.usage.input_tokens`  | `generation.input_tokens`                       |
| `gen_ai.usage.output_tokens` | `generation.output_tokens`                      |
| `latency_s`                  | `generation.latency_s`                          |
| `cost_usd`                   | `generation.cost_usd` **only if not None** (Q3) |

**Child `llm` "judge" span** (OpenInference span kind `LLM`), from `record.judge`: same
attribute set sourced from `record.judge`.

**Cost rule (Q3 / FR-3 / FR-5):** omit the `cost_usd` attribute entirely when the source
is `None` (never write `0`). Trace-level total (set on the root `chain` span as
`cost_usd_total`): write **only if both** `generation.cost_usd` and `judge.cost_usd` are
known; if either is `None`, omit the total. **[CONFIRM @impl]** the exact OpenInference
span-kind constant import path from the `arize-phoenix-otel` re-export (e.g. the semantic
conventions enum vs the `openinference_span_kind=` kwarg on `start_as_current_span`).

### Score write-back contract (FR-5)

`attributes.build_score_rows(record, span_ids)` returns `dict[metric_name -> list[row]]`
where each row carries `span_id` + `score` (float) + `label` (str). The optional
OpenInference `explanation` column is omitted — pre-computed metrics have no natural
explanation string.
**A `None` float skips its row** (no `0`/`None` written). Metric → span placement:

| Metric                  | Type    | Attaches to span | Skip if None |
| ----------------------- | ------- | ---------------- | ------------ |
| `did_abstain_e2e`       | BOOLEAN | root `chain`     | n/a (bool)   |
| `did_abstain_retrieval` | BOOLEAN | `retriever`      | n/a (bool)   |
| `faithfulness_ratio`    | NUMERIC | `generation`     | yes          |
| `fact_recall`           | NUMERIC | `judge`          | yes          |
| `fact_precision`        | NUMERIC | `judge`          | yes          |

`phoenix_client.log_scores` calls
`Client().spans.log_span_annotations_dataframe(dataframe=df, annotation_name=<metric>,
annotator_kind="CODE")` once per metric (DataFrame keyed on `span_id`). The deprecated
`px.Client().log_evaluations(SpanEvaluations(...))` path is **not** used. **[CONFIRM
@impl]** the exact DataFrame column names the method expects (`span_id` as column vs
index; `score`/`label`/`explanation` column spellings) — verified the method exists and
its dataframe shape; confirm the precise column contract against the installed client.

### Reset-and-replay (FR-4)

**Primary plan:** `phoenix_client.reset_project(project)` clears the target project
before ingest so a re-run yields exactly one trace per record. **[CONFIRM @impl]** the
span-delete call: the REST endpoints are verified to exist (Phoenix 11.19+) —
`DELETE /v1/projects/{project_identifier}/span_annotations?delete_all=true` and the
trace-annotation equivalent, plus span deletion — confirm whether `phoenix.client.Client`
wraps them; if not, fall back to a direct `httpx` DELETE against those endpoints.
**Robust fallback (documented, not the primary):** `make trace-reset`
(`docker compose -f infra/phoenix/docker-compose.yml down -v && ... up -d`) wipes the
SQLite volume for a guaranteed clean slate. The exporter targets a fixed default
`--project enterprise-rag-eval`.

Idempotency is testable offline (AC-4) because `reset_project` is a `sink` method: the
fake records that it was called **before** any `start_span`, and a second `replay_jsonl`
over the same JSONL reproduces the same trace/span counts.

---

## Implementation Phases

Per DEFINE § Sequencing Notes, one PR on `sprint-3/phase-7-tracing`, this commit order:

1. **Infra + deps + `trace-up`.** Add the three runtime deps and the `rag-export-traces`
   script stub to `pyproject.toml`; create `infra/phoenix/docker-compose.yml` (pinned
   tag, ports, volume, `PHOENIX_WORKING_DIR`); add `make trace-up` (+ `.PHONY`). `uv sync`.
   Commit: `feat(observability): pin Phoenix deps + docker-compose + make trace-up`.
2. **Exporter core + offline tests.** `attributes.py` (pure mapping, cost rule, retrieval
   flattening, enrich seam comment) → `phoenix_client.py` (the seam) → `exporter.py`
   (`replay_jsonl`) → `tests/observability/test_exporter.py` (fake sink, 2-record JSONL,
   FR-10 (a)–(f)). Commit: `feat(observability): replay exporter + span tree + score write-back`.
3. **CLI + console script + `export-traces`.** `cli.py` (flags, endpoint precedence) +
   confirm the `pyproject.toml` script entry resolves + `make export-traces`
   (`RESULTS_FILE ?= results/baseline.jsonl`, in `.PHONY`). Extend the test file with an
   offline CLI flag-parsing/endpoint-precedence test. Commit:
   `feat(observability): rag-export-traces CLI + make export-traces`.
4. **Gitignore negation + commit baseline JSONL.** Add `!results/baseline.jsonl`; commit
   the Phase 6 baseline. Commit: `chore(results): commit baseline.jsonl for cloneable trace demo`.
5. **ADR-0004 acceptance.** Status `proposed → accepted` + Acceptance Note (Phoenix,
   hardware rationale, pinned tag, unchanged wire format). Commit:
   `docs(adr): accept ADR-0004 — Phoenix deployed (hardware rationale)`.

**Shoulds/Coulds last (absence does not fail the phase):** `--dry-run` (FR-11) — fold into
phase 3 (cheap; the flag already parses, just gate the write calls + an AC-13 offline
test). `--enrich-from-index` (FR-12) — phase 2 code comment only, **not built**; verified
by a docstring naming the seam + absence of LanceDB/BM25 imports (AC-14).

---

## Infrastructure Gaps

| Gap Type           | Area                       | Detail                                                                                                                                                                                                                                                                                                                                        | Recommendation                                                                                                             |
| ------------------ | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Missing domain     | `observability`            | No `observability` KB domain in `_index.yaml` (the `domains:` block has only `rag-eval`, `rag-retrieval`). **Correctly deferred** per SPRINT.md — `/new-kb observability` runs **after** ADR-0004 acceptance (phase close), to capture the _decided_ exporter pattern, not pre-decision research. **Not blocking** `/design` or `/implement`. | `/new-kb observability` at `/review` / sprint-close (deferred, not now).                                                   |
| Concept coverage   | `rag-eval`                 | `rag-eval` covers the exporter's **input contract** (`eval-record-schema`, `cost-accounting`, `stats-capture-seam` concepts) — sufficient for reading `EvalRecord`/`CallStats`. No new concept needed for input.                                                                                                                              | None for input. New exporter concepts (span-tree, reset-and-replay, score-attach) land in the deferred `observability` KB. |
| Concept coverage   | OTEL / OpenInference       | ADR-0004's mapping table + this DESIGN's pinned-key section cover every attribute the exporter writes. The two **[CONFIRM @impl]** items (span-kind import path, DataFrame column spelling) are verified-to-exist API details, not missing knowledge.                                                                                         | Resolve the two `[CONFIRM @impl]` items at implement time against the installed package; no KB gap.                        |
| Missing dependency | Phoenix client/instrument. | New runtime deps `arize-phoenix-otel>=0.16.0` + `arize-phoenix-client` (server is the docker image, not a dep). Pinned in the manifest.                                                                                                                                                                                                       | Add in phase-1 commit; `uv sync`.                                                                                          |
| Missing dependency | `pandas`                   | Score write-back path needs a pandas DataFrame; `pandas` is **not** a current dep. Decision: add `pandas>=2.0,<3.0`. Alternative (row-wise client method) is an implement-time confirmation that could drop it.                                                                                                                               | Add `pandas>=2.0,<3.0` in phase-1; re-evaluate if a non-DataFrame client path is confirmed.                                |
| Missing specialist | observability              | No observability specialist agent exists (registry: kb-architect, brainstorm/define/design-agent, code-reviewer). **Not warranted** — Phase 7 is a single additive module over a documented contract; no repeated specialist context-loading across sessions.                                                                                 | None now. Revisit only if Phase 8 (failure taxonomy) + Phase 9 (dashboard) create a recurring observability loop.          |

---

## Consistency Check

Scope: one new module (4 source files + seam split) + infra/config + an ADR edit — above
the trivial single-module bar, so a LIGHT six-pass cross-check was run (DEFINE↔DESIGN +
constitution: AGENTS.md Conventions/Engineering Behavior, ADR-0004/0006/0007, NFR-2
additive invariant).

**Verdict: 🟡 MINOR DRIFT** — one MEDIUM (test path convention) and one LOW (dep
introduction visibility); no CRITICAL/HIGH. Safe to implement; address D1 by following
the recommendation below.

| ID  | Severity | Pass            | Location                              | Finding                                                                                                                                                                                                                                                               | Suggested fix                                                                                                                                                                                                                            |
| --- | -------- | --------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | MEDIUM   | 6 Inconsistency | DEFINE FR-10/AC-10 vs repo convention | DEFINE names the test `tests/test_observability_exporter.py` (flat), but the repo mirrors `src/` into **subdirs** (`tests/eval/`, `tests/generation/`, `tests/retrieval/`, each with `__init__.py`). A flat file drifts from house layout (NFR-7 "tests mirror src"). | This DESIGN places it at `tests/observability/test_exporter.py` + `__init__.py` to honour the mirror convention. Functionally identical coverage; the path is the only change. Not a re-opening of DEFINE — a convention reconciliation. |
| D2  | LOW      | 4 Constitution  | NFR-4 vs `pyproject.toml`             | NFR-4 says new deps are "limited to the Phoenix client/instrumentation libraries"; the verified write-back path additionally requires `pandas`. Within NFR-4's spirit (a client-path dep) but worth explicit visibility so it is not read as scope creep.             | Surfaced in the manifest + infra-gap table; flagged as introduced-by-the-verified-API, with the row-wise alternative as an implement-time check. No DEFINE change.                                                                       |
| D3  | —        | 2 Ambiguity     | DEFINE Q5 / FR-8                      | "low-single-digit MB expected" baseline size is conditional ("sample fallback if it bloats"). Not a defect — DEFINE pre-resolved it as a config decision with a named fallback.                                                                                       | Carried as a Risk (size check at phase 4); no fix needed.                                                                                                                                                                                |

**Pass-by-pass notes (no findings → confirmations):**

1. **Duplication** — no overlapping requirements; FR-3 (attributes) and FR-5 (scores) are
   cleanly separated by span-attribute vs annotation. No drift.
2. **Ambiguity** — only D3 (resolved). No unresolved `TODO`/`???`/placeholder in DEFINE.
3. **Underspecification** — every manifest entry maps to a named FR/AC; every FR has a
   span/attribute/signature here. No dangling component.
4. **Constitution** — **no violations.** NFR-2 additive invariant holds: the manifest
   touches **no** `eval/`, **no** `configs/`, no Phase 6 module (AC-12); the exporter
   imports `EvalRecord` as a read-only type only. **ADR-0006 cassette/replay is correctly
   N/A** — the exporter issues no LLM calls, so there is nothing to record/replay; tests
   fake the Phoenix tracer/client, never a mocked LLM API (NFR-1). **No Langfuse remnants
   leak** — all Langfuse framing in the BRAINSTORM body is superseded by its § Resolved
   Decisions and the DEFINE; this DESIGN names Phoenix, `PHOENIX_COLLECTOR_ENDPOINT`,
   `arize-phoenix-*`, and reset-and-replay (not `create_trace_id(seed=)`) throughout.
   Stranger test holds (no career/personal content in any tracked file). Conventions:
   English, YYYY-MM-DD, Conventional Commits, mirrored test — all honoured.
5. **Coverage** — all 12 FRs + 7 NFRs map to ≥1 manifest entry (FR-1→compose/Makefile,
   FR-2→exporter, FR-3→attributes/phoenix_client, FR-4→phoenix_client/exporter,
   FR-5→attributes/phoenix_client, FR-6→cli/pyproject, FR-7→Makefile, FR-8→.gitignore +
   baseline commit, FR-9→ADR, FR-10→test, FR-11→cli, FR-12→attributes comment; NFRs are
   cross-cutting and satisfied by the seam split + offline tests + additive scope). No
   orphan manifest entries.
6. **Inconsistency** — only D1 (test path). Terminology consistent: "reset-and-replay",
   "span tree", "CHAIN/RETRIEVER/LLM", "score row" match DEFINE.

---

## Risks & Trade-offs

- **Phoenix API drift (the two `[CONFIRM @impl]` items).** Span-kind constant import path
  and the `log_span_annotations_dataframe` column contract are verified-to-exist but their
  exact spellings depend on the installed patch. Mitigation: both are isolated inside
  `phoenix_client.py` (the seam) — a wrong guess is a one-file fix, not a redesign. The
  implementer confirms against the installed package before the phase-2 commit.
- **pandas dependency.** Adds a heavyweight transitive dep to a thin exporter. Justified
  by the verified write-back path; the row-wise alternative (if confirmed) drops it.
  Trade-off accepted for implementer certainty over dep minimalism. No ADR warranted (a
  client-library dep, reversible, inside the seam).
- **Baseline JSONL clone footprint (FR-8 / AC-8).** ~999 records expected low-single-digit
  MB. **Size check at phase 4:** if it materially bloats clone time, fall back to a
  committed `results/baseline-sample.jsonl` as the demo default (negate that file instead)
  and keep the full file gitignored — DEFINE pre-authorized this fallback (Q5). The
  stranger test holds either way (same published numbers as the committed `.html`/`.md`).
- **Reset-and-replay robustness.** If the in-process project-clear proves fiddly, the
  `make trace-reset` volume-wipe fallback guarantees a clean slate for the demo — documented
  so the exit demo (AC-11) is never blocked on the REST-delete detail.
- **ADR-worthy decisions:** none new. ADR-0004 is _accepted_ (not amended) this phase;
  the exporter architecture, span-tree shape, and reset-and-replay idempotency are
  implementation details inside the boundary ADR-0004 already governs (BRAINSTORM §
  Suggested ADRs confirms no new ADR number). The fail-loud price-validation backlog item
  (ADR-0007 amendment) is explicitly out of scope.

---

## Next Step

→ `/implement sprint-3/phase-7-tracing`

The implement stage runs in **Antigravity / Gemini** against this DESIGN.md as the sole
contract (per AGENTS.md § Implement Contract); resolve the three `[CONFIRM @impl]` items
against the installed Phoenix packages before the phase-2 commit, then run `make lint test`
(offline, no Phoenix/network/key) as the gate.
