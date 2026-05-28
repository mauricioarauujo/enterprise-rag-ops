# DEFINE: sprint-3/phase-7-tracing — Phoenix Replay Exporter & ADR-0004 Acceptance

**Sprint/Phase:** sprint-3/phase-7-tracing | **Date:** 2026-05-27

## Resolved Open Questions

The BRAINSTORM's five open questions (Q1–Q5) are **all resolved** in its `§ Resolved
Decisions (2026-05-27)` block — the user reviewed them and made the calls. Those
decisions **supersede the Langfuse-specific framing** in the BRAINSTORM body (Decisions
1–2, 5, and the Scope MoSCoW). They are recorded here as **fixed inputs**; `/design` and
`/implement` treat them as settled — do **not** re-open them.

- **Q1 — Tool = Arize Phoenix, not Langfuse (fixed; overrides BRAINSTORM Decisions 1–2, 5).**
  The deployed observability backend is **Arize Phoenix**. Rationale: the dev machine is
  an 8 GB MacBook Air running concurrent workloads; the Langfuse self-host stack
  (ClickHouse + Postgres + Redis + MinIO, ~4–6 GB) is infeasible alongside daily work.
  This is a **reasoned resource decision documented honestly — NOT a failed empirical
  test.** Phoenix is the ADR-0004 pre-justified runner-up; the OTEL-GenAI / OpenInference
  wire format keeps the persisted schema identical, so the swap is a localized remap, not
  a rewrite. The BRAINSTORM's "validate footprint first" spike (Decision 5, Approach B) is
  **not executed**. ADR-0004 is **accepted** with deployed tool = Phoenix and a
  hardware-rationale acceptance note (FR-9, AC-9).
- **Q2 — Deployment = single Phoenix container (fixed).** `infra/phoenix/docker-compose.yml`
  with **one** `arizephoenix/phoenix` container, image pinned to a **specific stable
  version tag** (never `:latest`), persistence via **SQLite on a mounted volume** (no
  Postgres — over-engineering for a replay demo). `/design` pins the exact version tag and
  confirms the persistence env var (`PHOENIX_WORKING_DIR` → mounted volume path). Keeps the
  exit demo `docker-compose up` light enough for an 8 GB machine.
- **Q3 — Cost `None` = unknown, never 0 (fixed).** Per span: **omit** the cost attribute if
  `cost_usd` is `None` (never write `0`). Trace-level total: compute only if **both**
  generation and judge costs are known; if either is `None`, omit the total. Same "N/A
  never 0" convention as the Phase 6 HTML report. The exporter handles `None`
  **defensively regardless** of any upstream change — it reads an external JSONL artifact
  and must not assume the producer validated (FR-5, AC-5).
- **Q4 — Connection = env var + optional override (fixed).** The exporter reads the
  collector endpoint from the native env var **`PHOENIX_COLLECTOR_ENDPOINT`** (default
  `http://localhost:6006`), with an optional **`--endpoint`** CLI flag that overrides it.
  Local self-host needs **no credentials**; if auth is ever enabled, the key comes **only**
  via env var (`PHOENIX_API_KEY`) — never a CLI flag (shell-history leak) or committed YAML
  (FR-6, AC-6). Keeps `clone → docker-compose up → make export-traces` working with zero
  configuration.
- **Q5 — Results path = Make variable + committed baseline JSONL (fixed; `/define`
  reconciles the gitignore).** `make export-traces` uses a Make variable
  `RESULTS_FILE ?= results/baseline.jsonl` (default = the canonical Phase 6 baseline
  artifact), overridable in one line. **Gitignore reconciliation (the `/define` to-do):**
  `.gitignore` currently does `results/*` then negates **only** `!results/baseline.html`
  and `!results/baseline.md` — so `results/baseline.jsonl` exists on disk but is
  **untracked**. For the cloneable exit demo to run cost-free (clone → up → export, with no
  paid eval re-run), the baseline JSONL **must be committed**. **Decision:** add a third
  negation `!results/baseline.jsonl` and commit the existing Phase 6 baseline (~999 records,
  the published `gpt-5-nano` vs Haiku 4.5 sweep). The stranger test holds — the JSONL is the
  same published-numbers artifact the committed `.{html,md}` already expose, now in the
  machine-readable form the exporter consumes (FR-8, AC-8). `/design` confirms the file size
  is acceptable to commit (≈ low-single-digit MB expected; if it materially bloats clone
  time, fall back to a committed small **sample** JSONL — e.g. `results/baseline-sample.jsonl`
  — as the demo default and keep the full file gitignored).

**Idempotency — RESET-AND-REPLAY (fixed; supersedes BRAINSTORM Decision 2's Langfuse
seed mechanism).** Phoenix is OTEL-native and has **no upsert-by-seed** primitive
(Langfuse's `create_trace_id(seed=)` does **not** exist here; Phoenix even ships
`uniquify_spans_dataframe`, which does the opposite). Idempotency is therefore achieved by
**clearing the Phoenix project before ingesting** — each export run yields exactly one
trace per record, with no duplicates across re-runs. The exporter captures each `span_id`
**in-process at span-creation time** so it can attach offline scores in the **same run** —
no deterministic seed is needed (FR-4, AC-4).

**Backlog (NOT this phase) — fail-loud pre-flight price validation.** An upstream
improvement (the eval runner validates at config-load that every model declares a price,
requiring an explicit `$0` for local/free models, and refuses to start otherwise) would
let `cost_usd` become non-optional at the source. It touches ADR-0007 (accepted) + the
Phase 6 runner, so it is **out of Phase 7's additive-exporter scope** — logged as a
separate `fix/` + ADR-0007 amendment. It does **not** replace the exporter's defensive
`None` handling (boundary robustness, FR-5).

## Requirements

### Functional

- **FR-1 (Phoenix deployment + `make trace-up`)** — `infra/phoenix/docker-compose.yml`
  defines **one** `arizephoenix/phoenix` service, image pinned to a specific stable version
  tag (never `:latest`), exposing port **6006** (web UI / HTTP collector) and **4317** (OTLP
  gRPC), with **SQLite persistence on a mounted volume** (via `PHOENIX_WORKING_DIR`; no
  Postgres). A `make trace-up` target brings the backend up; the stack starts cleanly on an
  8 GB machine and needs no credentials (Q1, Q2).
- **FR-2 (Replay exporter — `replay_jsonl`)** — `src/enterprise_rag_ops/observability/exporter.py`
  exposes `replay_jsonl(path, ...)` that reads a `results/*.jsonl` line-by-line, parses each
  line into an `EvalRecord` (the unchanged Phase 6 Pydantic model — the exporter's **input
  contract**), and writes **one Phoenix trace per record** as a span tree. The exporter
  makes **no LLM calls** — it replays existing records — and touches **no eval-path code**
  (purely additive over the JSONL, NFR-2).
- **FR-3 (Span tree shape + OpenInference/OTEL attributes)** — Each `EvalRecord` produces a
  four-span tree built with Phoenix's OpenTelemetry registration
  (`phoenix.otel.register(project_name=..., endpoint=...)` → manual
  `tracer.start_as_current_span(name, openinference_span_kind=...)`):
  - **Root `chain` span (the question):** trace-level metadata — `question_id`, `category`,
    `run_id`, `k`, and the generator model (`gen_ai.request.model`, `gen_ai.system`,
    `gen_ai.operation.name`) per the ADR-0004 attribute mapping.
  - **Child `retriever` span:** `retrieval.documents.{i}.document.id` plus rank position
    for each id in `retrieval_ranked_ids` (OpenInference flattened retrieval attributes).
    **id + rank only** — **no** `document.content` and **no** per-doc `document.score`
    (the `EvalRecord` does not persist them, ADR-0007; this is the accepted id+rank-only
    fidelity from BRAINSTORM Decision 3). `--enrich-from-index` is the **named, unbuilt
    seam** for a future re-hydration path — documented in code, not implemented (Could,
    FR-12).
  - **Child `llm` "generation" span:** the `generation` `CallStats` — input/output tokens
    (`gen_ai.usage.input_tokens` / `output_tokens`), latency, and cost via the Q3 rule.
  - **Child `llm` "judge" span:** the `judge` `CallStats` — same token/latency/cost
    attributes.

  Attribute **names** follow the ADR-0004 OTEL-GenAI / OpenInference mapping table; `/design`
  pins any name not already in that table against the OpenInference spec.

- **FR-4 (Idempotency via reset-and-replay)** — Before ingesting, the exporter **clears the
  target Phoenix project** so a re-run of the same JSONL yields **exactly one trace per
  record** (no duplicates, no orphaned scores). The exporter captures each created span's
  `span_id` **in-process** to attach scores in the same run (no deterministic seed; Phoenix
  has no upsert-by-seed). The project name is configurable via `--project` (FR-6).
- **FR-5 (Offline-score write-back, semantically aligned, `None`-safe)** — Offline eval
  scores attach to their **semantically aligned** span via the current Phoenix client API
  `phoenix.client.Client().spans.log_span_annotations_dataframe(dataframe=df,
annotation_name=..., annotator_kind="CODE")` (the deprecated
  `px.Client().log_evaluations(SpanEvaluations(...))` path is **not** used). The dataframe
  is keyed on the in-process-captured `span_id` and carries `score` (float) / `label` (str)
  / `explanation` (str). `annotator_kind="CODE"` (these are pre-computed, not LLM-judged at
  export time). Placement:
  - `did_abstain_e2e` (**BOOLEAN**) → **root `chain`** span.
  - `did_abstain_retrieval` (**BOOLEAN**) → **`retriever`** span.
  - `faithfulness_ratio` (**NUMERIC**) → **`llm` "generation"** span.
  - `fact_recall` + `fact_precision` (**NUMERIC**) → **`llm` "judge"** span.

  **`None` floats skip their score row** — never write `0`/`None` as a score (mirrors the
  Q3 cost convention and the Phase 6 report's None=N/A rule).

- **FR-6 (`rag-export-traces` console script + `cli.py`)** —
  `src/enterprise_rag_ops/observability/cli.py:main` is wired as the **`rag-export-traces`**
  console script in `pyproject.toml [project.scripts]`. Flags: `--results <path>` (the JSONL
  to replay), `--endpoint <url>` (overrides `PHOENIX_COLLECTOR_ENDPOINT`, Q4), `--project
<name>` (target Phoenix project), and `--dry-run` (parses the JSONL and logs what **would**
  be exported, writing nothing to the backend — Should-leaning but cheap; FR-11). Credentials,
  if ever needed, come only from env (`PHOENIX_API_KEY`), never a flag (Q4).
- **FR-7 (`make export-traces` target)** — A `make export-traces` target runs
  `uv run rag-export-traces --results $(RESULTS_FILE)` with `RESULTS_FILE ?=
results/baseline.jsonl` (overridable in one line, e.g. `make export-traces
RESULTS_FILE=results/baseline-anthropic.jsonl`). Chains cleanly after `make trace-up`
  (Q5). The target name is added to the `.PHONY` list.
- **FR-8 (Committed baseline JSONL for the cloneable demo)** — `.gitignore` gains a third
  negation `!results/baseline.jsonl` alongside the existing `!results/baseline.html` /
  `!results/baseline.md`, and the existing Phase 6 baseline JSONL is committed so the exit
  demo runs **cost-free from a fresh clone** (no paid eval re-run). Run-specific JSONL
  (`results/<run_id>.jsonl`, e.g. `baseline-dev.jsonl`, `baseline-anthropic.jsonl`) stays
  gitignored. (Q5; if `/design` finds the full file bloats clone time, a committed
  `results/baseline-sample.jsonl` becomes the demo default instead — see Q5.)
- **FR-9 (ADR-0004 accepted)** — `docs/adr/0004-observability-tool.md` status changes
  **`proposed` → `accepted`** with an **Acceptance Note** recording: deployed tool =
  **Phoenix** (the pre-justified runner-up), the **hardware rationale** (8 GB Air +
  concurrent workloads make the Langfuse stack infeasible — a reasoned resource decision,
  **not** a failed empirical test), the **pinned image tag**, and that the OTEL-GenAI /
  OpenInference wire format keeps the persisted schema identical (the deviation from
  "primary = Langfuse" is a tool swap behind the same wire format, not a record-schema
  change). No new ADR number.
- **FR-10 (Offline exporter tests, mirrored)** — `tests/observability/test_exporter.py`
  (mirroring `src/.../observability/exporter.py`) is **fully offline** with a **fake/patched
  Phoenix tracer + client** — **no cassette** (the exporter issues no LLM calls; it replays
  existing records), **no network**, and **no running Phoenix**. Over a hand-built 2-record
  JSONL the tests assert: (a) the four-span tree shape and parent/child nesting; (b) the
  OpenInference/OTEL attribute **names** per ADR-0004 on each span; (c) each offline score
  attaches to the **correct** span (recall/precision→judge, faithfulness→generation,
  abstention flags→retriever/root) with the right `data_type` (NUMERIC vs BOOLEAN); (d) the
  Q3 cost-`None` handling (cost attribute omitted, never `0`; trace total omitted unless both
  costs known); (e) `None`-float scores skip their score row; (f) **reset-and-replay**
  behavior (the project is cleared before ingest; a second `replay_jsonl` over the same JSONL
  produces the same one-trace-per-record result). Passes under `make test` (`-m "not corpus
and not smoke"`).
- **FR-11 (`--dry-run`) — Should.** `rag-export-traces --dry-run` parses the JSONL and logs
  the planned export (record count, per-record span tree summary) **without** writing to the
  backend — useful for validating a JSONL before a live export. Absence does not fail the
  phase.
- **FR-12 (`--enrich-from-index` seam) — Could / not built.** The retrieval span's
  `document.content` / `document.score` re-hydration path (loading LanceDB + BM25 to look up
  each doc id) is **documented in code as the named extension point** (`--enrich-from-index`),
  **not implemented** in Phase 7. ADR-0004's `retrieval.documents.*` content/score attribute
  slots remain reserved. Building it is explicitly out of scope (keeps the exporter additive
  over the JSONL alone).

### Non-functional

- **NFR-1 (Offline `make test` — no network, no Phoenix, no key)** — Every Phase 7 test runs
  under `make test` (`-m "not corpus and not smoke"`) with **no network I/O, no running
  Phoenix backend, and no API keys**. The exporter makes **no LLM calls** (it replays
  records), so **no cassette is needed** (ADR-0006's cassette/replay rule applies to LLM-API
  paths; this exporter has none). The Phoenix tracer/client are **faked/patched** in tests —
  never a mocked LLM API (there is none to mock).
- **NFR-2 (Purely additive — no eval-path code touched)** — Phase 7 changes **no** existing
  module: not the `eval/` runner, not `EvalRecord`/`CallStats` (`eval/records.py`), not the
  configs, not any Phase 6 code. The new work lives entirely under
  `src/enterprise_rag_ops/observability/` + `infra/phoenix/` + Makefile/pyproject/gitignore
  additions + the ADR-0004 status edit. The `EvalRecord` JSONL is the read-only input
  contract.
- **NFR-3 (`observability/` is the tool-swap seam)** — All Phoenix-specific code (OTEL
  registration, OpenInference attribute mapping, the `log_span_annotations_dataframe`
  write-back, the reset-and-replay logic) is **localized inside `observability/`**, so a
  future tool swap (e.g. back to Langfuse on a larger machine, or the ADR-0004 Phase 3
  OTEL-Collector fan-out) stays a contained change behind the module boundary, not a
  rewrite. The OTEL-GenAI wire format is the shared contract that makes this localized.
- **NFR-4 (Dependency hygiene)** — New runtime dependencies are limited to the Phoenix
  **client/instrumentation** libraries (`arize-phoenix` for the client + OTEL helpers, plus
  the OpenInference/OpenTelemetry instrumentation libs needed for manual span construction).
  The Phoenix **server** is the docker image, **not** a Python dependency. `/design` pins the
  **exact package names and version specifiers** (e.g. `arize-phoenix`, the
  `openinference-*` / `opentelemetry-*` packages) — flagged here as an infra item, not yet
  pinned. No eval-framework library, no LangChain.
- **NFR-5 (Cloneable exit demo on 8 GB)** — The full demo runs from a fresh clone on an 8 GB
  machine: `clone → docker-compose up (make trace-up) → make export-traces → open a failed
trace in the Phoenix UI → see why it failed` (retrieval miss vs hallucination vs format),
  using the committed `results/baseline.jsonl` (FR-8) — **no paid eval re-run, no managed
  service**. This is the Sprint 3 portfolio bar applied to Phase 7.
- **NFR-6 (Budget — ~5h)** — The phase fits a ~5h budget: one docker-compose file, one
  exporter module + CLI, one test file, Makefile/pyproject/gitignore wiring, and the ADR-0004
  status edit. Minimal-scope / clean-structure ethos; Shoulds/Coulds (FR-11/12) slot in only
  after the Must spine and their absence does not fail the phase.
- **NFR-7 (Conventions + mirrored tests + stranger test)** — English; YYYY-MM-DD dates in
  docs; Conventional Commits; the new module gets its mirrored `tests/observability/test_exporter.py`;
  `make lint test` passes with no network/key. No career/personal content in any tracked
  Phase 7 file.

## Acceptance Criteria

1. `infra/phoenix/docker-compose.yml` defines a single `arizephoenix/phoenix` service with a
   **pinned version tag** (not `:latest`), ports 6006 + 4317 exposed, and SQLite persistence
   on a mounted volume; `make trace-up` starts it cleanly on an 8 GB machine with no
   credentials. Verified by inspecting the compose file (pinned tag, single service, volume
   mount) and a maintainer `make trace-up` smoke (the UI is reachable at the configured
   endpoint). (FR-1)
2. `replay_jsonl(path, ...)` in `observability/exporter.py` parses each JSONL line into an
   `EvalRecord` and emits **exactly one trace per record**. Verified by an offline unit test
   over a hand-built 2-record JSONL asserting two traces are built (against the fake tracer),
   with no import of or change to `eval/` code. (FR-2, NFR-2)
3. Each record produces the four-span tree — root `chain` (question) → child `retriever` →
   child `llm` "generation" → child `llm` "judge" — with parent/child nesting and the
   ADR-0004 OpenInference/OTEL attribute **names** on each span; the `retriever` span carries
   `retrieval.documents.{i}.document.id` + rank for each `retrieval_ranked_ids` entry and
   **no** `document.content` / `document.score`. Verified by an offline test asserting span
   kinds, nesting, attribute names/keys, and the absence of content/score keys. (FR-3)
4. **Reset-and-replay idempotency:** the exporter clears the target Phoenix project before
   ingest, and running `replay_jsonl` twice over the same JSONL yields the same
   one-trace-per-record result (no duplicates). Span `span_id`s are captured in-process and
   reused for score attachment in the same run. Verified by an offline test asserting the
   project-reset call precedes ingestion and that a second run reproduces the same trace count
   / span structure. (FR-4)
5. Offline scores attach to the **correct** spans via
   `Client().spans.log_span_annotations_dataframe(..., annotator_kind="CODE")` (not the
   deprecated `log_evaluations`): `did_abstain_e2e` (BOOLEAN) on root, `did_abstain_retrieval`
   (BOOLEAN) on `retriever`, `faithfulness_ratio` (NUMERIC) on `generation`, `fact_recall` +
   `fact_precision` (NUMERIC) on `judge`. A `None` float **skips** its score row. Cost
   attribute is **omitted** when `cost_usd` is `None` (never `0`); the trace-level cost total
   is written only when **both** generation and judge costs are known. Verified by an offline
   test over a fixture JSONL containing at least one `None` cost and one `None` metric float,
   asserting score→span mapping, data types, skipped rows, and omitted cost. (FR-5)
6. `rag-export-traces` (the console script in `pyproject.toml`) accepts `--results`,
   `--endpoint`, `--project`, and `--dry-run`; the endpoint defaults to
   `PHOENIX_COLLECTOR_ENDPOINT` (default `http://localhost:6006`) and `--endpoint` overrides
   it; no credential flag exists (any key is env-only). Verified by an offline CLI test
   driving the entry point against the fake client and asserting flag parsing + endpoint
   resolution precedence. (FR-6, Q4)
7. `make export-traces` runs `uv run rag-export-traces --results $(RESULTS_FILE)` with
   `RESULTS_FILE ?= results/baseline.jsonl`, overridable on the command line, and is listed in
   `.PHONY`. Verified by inspecting the Makefile target and the variable default + override.
   (FR-7)
8. `.gitignore` gains `!results/baseline.jsonl` (alongside the existing `.html`/`.md`
   negations) and the Phase 6 baseline JSONL is committed; run-specific
   `results/<run_id>.jsonl` stays untracked. Verified by inspecting `.gitignore` and
   `git status` (baseline JSONL tracked; `baseline-dev.jsonl` / `baseline-anthropic.jsonl`
   untracked). If `/design` substitutes a committed sample, the negation targets the sample
   file instead. (FR-8, Q5)
9. `docs/adr/0004-observability-tool.md` status reads **accepted** with an Acceptance Note
   recording deployed tool = Phoenix, the hardware rationale (reasoned resource decision, not
   a failed test), the pinned image tag, and the unchanged OTEL-GenAI wire format. Verified by
   inspecting the ADR (status line + note section). (FR-9)
10. `tests/observability/test_exporter.py` passes under `make test` with **no network, no
    running Phoenix, and no API key**, using a fake/patched Phoenix tracer + client (no
    cassette). It covers span-tree shape, attribute names, score→span mapping + data types,
    cost-`None` handling, `None`-float skipped score rows, and reset-and-replay. Verified in
    CI on the PR (`make lint test` green, offline). (FR-10, NFR-1, NFR-7)
11. **Exit demo (NFR-5):** from a fresh clone on an 8 GB machine, `make trace-up` →
    `make export-traces` ingests the committed `results/baseline.jsonl` with **no paid eval
    re-run**, and a reviewer can open a failed trace in the Phoenix UI and read **why** it
    failed (retrieval miss vs hallucination vs format) from the span tree + attached scores.
    Verified by the maintainer's end-to-end demo run. (NFR-5, FR-1, FR-7, FR-8)
12. **Additive invariant (NFR-2):** the Phase 7 diff touches **no** file under
    `src/enterprise_rag_ops/eval/`, **no** `configs/`, and **no** existing Phase 6 module —
    only new `observability/` + `infra/phoenix/` files plus Makefile / pyproject / `.gitignore`
    additions and the ADR-0004 status edit. Verified by inspecting the PR diff file list.
13. (Should) `--dry-run` (FR-11) parses the JSONL and logs the planned export without writing
    to the backend. Verified by an offline test asserting no write-back calls fire under
    `--dry-run`. Absence does not fail the phase.
14. (Could) `--enrich-from-index` (FR-12) is **documented in code as a named seam**, not
    implemented; the retrieval span carries id + rank only in Phase 7. Verified by a code
    comment / docstring naming the seam and the absence of LanceDB/BM25 imports in the
    exporter. Absence does not fail the phase.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit with evidence: Phase 6 produces a durable `results/*.jsonl` shaped to OTEL-GenAI per ADR-0004/0007, but nothing **renders it as a navigable trace** — a reviewer cannot open a failed answer and see _where_ it broke (retrieval miss vs hallucination vs format) or what it cost. Phase 7 closes the observability loop with an additive replay exporter and formally accepts ADR-0004 against a live deployment.                                                                                                                           |
| Users       | 2     | Consumers are the maintainer (`make trace-up` / `make export-traces`, diagnosing failures) and the reviewer/hiring manager who clones the repo and opens a failed trace in the Phoenix UI. Internal observability phase — no external end-user workflow — so workflow-impact is inherently thin, scored honestly and consistently with the Phase 1–6 DEFINEs (which also scored Users 2).                                                                                                                                                                        |
| Success     | 3     | 14 numbered, falsifiable acceptance criteria covering every FR/NFR: single-pinned-container compose + `make trace-up`, one-trace-per-record, the four-span tree + OpenInference attribute names, reset-and-replay idempotency, score→span mapping with NUMERIC/BOOLEAN data types + `None`-skip, the cost-`None` rule, CLI flags + endpoint precedence, the committed-baseline `.gitignore` negation, ADR-0004 acceptance, the offline test suite, the additive invariant, and the cloneable exit demo. Shoulds/Coulds marked "absence does not fail the phase." |
| Scope       | 3     | Full MoSCoW carried from the BRAINSTORM and re-pointed to Phoenix: Musts (compose + exporter + span tree + idempotency + score write-back + CLI + Make target + committed JSONL + ADR acceptance + offline tests), Should (`--dry-run`), Could (`--enrich-from-index` named-not-built), explicit Won't (Langfuse/cloud, OTEL-Collector fan-out, failure classifier→Phase 8, dashboard→Phase 9, any `EvalRecord`/eval-path change, content/score re-hydration). The fail-loud price-validation backlog item is explicitly out-of-scope.                           |
| Constraints | 3     | All constraints named as NFRs: offline `make test` with no network/Phoenix/key and no cassette needed (NFR-1), purely additive — no eval-path code touched (NFR-2), `observability/` as the tool-swap seam (NFR-3), dependency hygiene with exact package pinning deferred to `/design` (NFR-4), cloneable 8 GB exit demo (NFR-5), ~5h budget (NFR-6), conventions + mirrored tests + stranger test (NFR-7). Plus the pinned-not-`:latest` image tag and env-only credentials.                                                                                   |

**Total: 14/15 — PASS (≥12).** Users scored 2 for the same structural reason as Phases
1–6: an internal observability phase whose "users" are the maintainer and a portfolio
reviewer, so workflow-impact is inherently thin — acceptable, not a blocker, and
consistent across the whole DEFINE history. **All five BRAINSTORM open questions (Q1–Q5)
were resolved by the user before `/define`** (the `§ Resolved Decisions` block), plus the
reset-and-replay idempotency call — no design ambiguity remains to invent. The one residual
the BRAINSTORM flagged (Q5's gitignore / committed-baseline reconciliation) is **closed in
this DEFINE as an explicit decision** (FR-8 / AC-8: add `!results/baseline.jsonl`, commit
the Phase 6 baseline, with a sample-JSONL fallback if size warrants) rather than left open —
it gates the cloneable demo, not the design, and is reversible config. No `AskUserQuestion`
round was needed; nothing was passed forward below the gate.

## Infrastructure Readiness

| Dependency                                              | KB domain       | Specialist | Status                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------- | --------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EvalRecord` / `CallStats` schema (`eval/records.py`)   | `rag-eval`      | none       | **Ready — the exporter's read-only input contract.** ADR-0007 (accepted) + the Pydantic model define every field the exporter consumes; the `rag-eval` KB (`eval-record-schema`, `cost-accounting`, `stats-capture-seam` concepts) is sufficient to understand it. Reused unchanged (NFR-2).                                                                   |
| ADR-0004 (observability tool + OTEL field conventions)  | `observability` | none       | **Accepted this phase (FR-9, AC-9).** Status `proposed → accepted` with the Phoenix/hardware note; the OTEL-GenAI attribute mapping table is the exporter's span-attribute spec (FR-3). No new ADR number.                                                                                                                                                     |
| Arize Phoenix server (docker image)                     | `observability` | none       | **Infra to add at implement time.** Single `arizephoenix/phoenix` container, **version tag pinned at `/design`** (never `:latest`), SQLite-on-volume persistence (`PHOENIX_WORKING_DIR`), ports 6006 + 4317. Not a Python dependency. Footprint fits 8 GB (the reason Phoenix was chosen over Langfuse, Q1).                                                   |
| `arize-phoenix` client + OpenInference/OTEL instrument. | `observability` | none       | **New runtime deps — exact packages/versions pinned at `/design` (NFR-4).** The Phoenix client (`phoenix.client.Client`, `phoenix.otel.register`) + the OpenInference/OpenTelemetry instrumentation libs for manual span construction. Flagged here for visibility; Context7 was already consulted (current API verified).                                     |
| Phoenix score write-back API                            | `observability` | none       | **Ready (current API verified).** `Client().spans.log_span_annotations_dataframe(dataframe=df, annotation_name=..., annotator_kind="CODE")` keyed on `span_id` (the deprecated `log_evaluations(SpanEvaluations(...))` path is avoided). `/design` confirms the exact dataframe column contract. (FR-5)                                                        |
| `pydantic` (`EvalRecord` parsing)                       | none needed     | none       | Ready — already a runtime dep (`pydantic>=2.6,<3.0`). No new dep.                                                                                                                                                                                                                                                                                              |
| `results/baseline.jsonl` (committed demo artifact)      | none needed     | none       | **Decision pending commit (FR-8, AC-8).** The file exists on disk but is gitignored (only `.html`/`.md` are negated); Phase 7 adds `!results/baseline.jsonl` and commits it (≈ low-MB; sample fallback if `/design` finds it bloats clone time). Enables the cost-free cloneable demo (NFR-5).                                                                 |
| `observability` KB domain                               | `observability` | none       | **MISSING — deferred, NOT blocking.** SPRINT.md schedules `/new-kb observability` **after** ADR-0004 is accepted (post-implement, at phase close) — it documents the _decided_ exporter pattern, span-tree shape, score attachment, reset-and-replay, and Phoenix footprint, not pre-decision research. Not registered in `_index.yaml`. Build at phase close. |
| Observability specialist agent                          | n/a             | none       | **Optional — not warranted.** Phase 7 is a single additive module (one exporter + CLI + compose) over a well-documented input contract; no repeated specialist context-loading across sessions. Revisit only if Phase 8 (failure taxonomy) + Phase 9 (dashboard) create a recurring observability-context loop.                                                |

**Gaps and recommendations.** No `/new-kb` or `/new-agent` **blocks** `/design` — the
exporter's input contract (`rag-eval` KB + ADR-0007) and the Phoenix API grounding are
sufficient. Three non-blocking items are logged for the orchestrator: (1) the **new runtime
deps** (`arize-phoenix` + OpenInference/OTEL instrumentation) are infra to pin at `/design`
and add at implement time (NFR-4); (2) **`/new-kb observability`** is **deferred to phase
close** (after ADR-0004 acceptance) per SPRINT.md — recommend running it at `/review` /
sprint-close to capture the decided design; (3) **no specialist agent** is recommended yet.
The one config decision that gates the demo (not the design) is the Q5 committed-baseline
JSONL (FR-8) — reversible `.gitignore` change.

## Sequencing Notes (not requirements)

- **One phase / one PR** on `sprint-3/phase-7-tracing`, with a disciplined commit sequence:
  (1) `infra/phoenix/docker-compose.yml` + `make trace-up` + the new runtime deps in
  `pyproject.toml`; (2) `observability/exporter.py` (`replay_jsonl`, span tree, reset-and-replay,
  score write-back, `None`-safe cost) + `tests/observability/test_exporter.py` (fully offline,
  fake Phoenix); (3) `observability/cli.py` + `rag-export-traces` console script + `make
export-traces`; (4) `.gitignore` negation + commit `results/baseline.jsonl`; (5) ADR-0004
  status `proposed → accepted` + Acceptance Note. Shoulds/Coulds (FR-11 `--dry-run`, FR-12
  `--enrich-from-index` seam) slot in after the Must spine; their absence does not fail the phase.
- **No live call during development** — the exporter replays records and issues no LLM calls,
  so there is no cassette to record (unlike Phase 6's Anthropic cassette). The only live step
  is the maintainer's one-time exit-demo `make trace-up` + `make export-traces` against the
  committed baseline JSONL (no paid eval re-run).
- **`/design` decisions to make:** the exact Phoenix image **version tag** + the persistence
  env var (`PHOENIX_WORKING_DIR`) and volume mount; the **exact package names + version
  specifiers** for `arize-phoenix` + the OpenInference/OTEL instrumentation libs (NFR-4); any
  OpenInference attribute key not already in the ADR-0004 mapping table; the
  `log_span_annotations_dataframe` dataframe column contract; whether the committed demo
  artifact is the full `results/baseline.jsonl` or a `results/baseline-sample.jsonl` (Q5
  size check). None reopen a DEFINE-level question.

## Next Step

→ `/design sprint-3/phase-7-tracing`
