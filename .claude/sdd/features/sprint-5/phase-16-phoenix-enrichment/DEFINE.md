# DEFINE: sprint-5/phase-16-phoenix-enrichment — Phoenix Trace Enrichment

**Sprint/Phase:** sprint-5/phase-16-phoenix-enrichment | **Date:** 2026-06-02
**Approach:** B (from BRAINSTORM) — post-process enrich step in `observability/exporter.py`;
`observability/attributes.py` is left **structurally unchanged** (no new imports, no signature
change — only the stale FR-12/AC-14 stub comment is updated). **No ADR** — the coupling is a
stdlib `Mapping[str, str]` passed at the exporter boundary (sprint "ADR only if non-trivial"
bar not met).

## Problem

The retriever span in Phoenix currently exposes only doc IDs and ranks. `build_span_attrs`
(`observability/attributes.py`, lines 35–37) writes exactly two keys per ranked document —
`retrieval.documents.{i}.document.id = doc_id` and `retrieval.documents.{i}.document.rank = i`
— and an explicit `# SEAM: --enrich-from-index (FR-12 / AC-14)` stub (lines 39–44) deliberately
omits `.content` / `.score`, declaring them "out of scope for Phase 7." The consequence: clicking
a failed trace in Phoenix shows opaque IDs, not the text that was retrieved, so the sprint's
"click a failed trace → see why" legibility goal is unanswerable visually.

The decisive code finding (BRAINSTORM) is that `EvalRecord.retrieval_ranked_ids: list[str]`
(`eval/records.py:92`) holds **doc-level** IDs identical to `Document.id` in `corpus.jsonl`.
Content enrichment therefore needs only a `{doc_id: text}` map built from `corpus.jsonl` via the
existing `read_corpus()` (`ingest/writer.py:33`) — **zero BM25/LanceDB/embedder import**. This
phase activates the seam at the exporter boundary: when `--enrich-from-index` is passed,
`rag-export-traces` builds the corpus map once and the exporter writes
`retrieval.documents.{i}.document.content` onto each retriever span after `build_span_attrs`
returns, preserving the existing `.id`/`.rank` keys. The enrichment must stay **opt-in** (default
off → byte-identical to today) and the corpus read must live at the boundary so `attributes.py`
keeps its zero-lock-in, unit-testable shape (NFR-3, sprint "observability coupling regression"
risk).

## Users / Stakeholders

- **Maintainer (Mauricio) debugging in Phoenix** — the primary actor. Runs
  `rag-export-traces --enrich-from-index` after an eval sweep, opens a failed trace, and reads
  the retrieved-doc **text** inline on the retriever span (not just IDs). Needs the enriched view
  to be legible and the default path (no flag) to stay exactly as it is today.
- **Public-repo reviewer / hiring signal** — sees that a single failed trace is legible
  end-to-end in Phoenix (the sprint's legibility headline) and that activating it did **not**
  pollute the pure attribute mapper.
- **`observability/attributes.py` (the pure mapper, NFR-3)** — the constraint to protect. It must
  remain import-light (stdlib + pydantic + `EvalRecord` only) and keep its current
  `build_span_attrs(record) -> dict[...]` signature unchanged; the only edit is the stub comment.
- **`ingest/writer.py::read_corpus` + `ingest/schema.py::Document` (shipped)** — the upstream
  content source, consumed read-only. `Document.id` → key, `Document.text` → value.
- **Sprint-Wide Knowledge Plan / future maintainers** — `/update-kb observability` lands **after**
  this impl to refresh `span-attribute-mapping` + `dashboard-phoenix-boundary` for the now-live
  seam (deferred by design, not a gap). No ADR is produced (coupling is trivial).

## Requirements

### Functional

- **FR-1 Opt-in CLI flag.** `rag-export-traces` (`observability/cli.py`, `_build_parser`) gains
  `--enrich-from-index` (`action="store_true"`, default off). When **absent**, no corpus is read
  and behavior is byte-identical to today. When **present**, the CLI builds the corpus map and
  passes it to `replay_jsonl`.
- **FR-2 Corpus map built once at the boundary.** When `--enrich-from-index` is set, the CLI
  builds a `{doc_id: text}` map exactly once **before** the replay loop by calling
  `read_corpus(CORPUS_PATH)` (import: `from enterprise_rag_ops.ingest.writer import read_corpus`;
  `from enterprise_rag_ops.retrieval.config import CORPUS_PATH`) and collecting
  `{doc.id: doc.text for doc in read_corpus(...)}` (`Document.id` / `Document.text` confirmed in
  `ingest/schema.py:42,44`). No per-record corpus read; no BM25/LanceDB/embedder import anywhere
  in this path.
- **FR-3 `doc_lookup` param on `replay_jsonl`.** `exporter.py::replay_jsonl` gains a new
  keyword-only parameter `doc_lookup: Mapping[str, str] | None = None`. Default `None` →
  enrichment skipped → the export is byte-identical to the current behavior. `Mapping` is a
  `collections.abc` stdlib type — **no retrieval/Phoenix/OTel import is added to `exporter.py`**
  for it.
- **FR-4 Boundary enrichment (Approach B).** Inside the per-record loop in `replay_jsonl`, after
  `span_attrs = build_span_attrs(record)` returns and **before** the retriever span is opened
  (line ~92, where `span_attrs["retriever"]` is passed as `attributes=`), if `doc_lookup is not
None`, the exporter post-processes `span_attrs["retriever"]`: for each
  `(i, doc_id)` in `enumerate(record.retrieval_ranked_ids)` it sets
  `span_attrs["retriever"][f"retrieval.documents.{i}.document.content"] = doc_lookup[doc_id]`
  when `doc_id` is present in the map. The existing `.id` and `.rank` keys (written by
  `build_span_attrs`) are preserved untouched.
- **FR-5 Missing-doc-id → omit + warn.** If a ranked `doc_id` is absent from `doc_lookup`, the
  exporter **omits** the `.content` key for that index entirely (it does not write an empty string
  or any placeholder), logs a `logging.warning` naming the missing `doc_id`, and continues. The
  enrichment path never raises on a missing id.
- **FR-6 `attributes.py` unchanged except the stub comment.** `build_span_attrs` keeps its exact
  signature `build_span_attrs(record: EvalRecord) -> dict[str, dict[str, Any]]` and its current
  imports (`typing.Any`, `enterprise_rag_ops.eval.records.EvalRecord`) — **no new import, no new
  parameter**. The **only** edit is replacing the stale stub comment block (lines 39–44, which
  references "a future phase" and "out of scope for Phase 7") with a brief note: enrichment is
  activated in Phase 16 and applied at the exporter boundary (`exporter.py`), not in this pure
  mapper. The `.id`/`.rank` loop is unchanged.
- **FR-7 Score is OUT in v1.** The exporter writes **no** `retrieval.documents.{i}.document.score`
  key. Scores are not persisted in `EvalRecord` (`retrieval_ranked_ids` is `list[str]`, no scores),
  and deriving them requires re-running retrieval (forbidden by the no-re-runs guard). Content +
  the already-present rank satisfy the legibility goal ("see what was retrieved, in order").
  Persisting score would require an upstream `EvalRecord` schema change (a future concern).
- **FR-8 `--corpus` override (Should, not Must).** Optionally add `--corpus PATH` to
  `rag-export-traces` defaulting to `CORPUS_PATH`, so a non-default corpus location can be used.
  This is a **Should**; if it complicates the diff, `CORPUS_PATH` alone is the acceptable v1.

### Non-functional

- **NFR-1 `attributes.py` purity preserved (sprint coupling-regression control).** Post-change,
  `observability/attributes.py` imports nothing from `retrieval/`, `ingest/`, Phoenix, or OTel —
  exactly as today (only `typing` + `eval.records`). The pure mapper stays fully unit-testable
  offline with a bare `EvalRecord`.
- **NFR-2 Opt-in / default-off / read-only.** Enrichment is never the default. The corpus is read
  **once, read-only**, only when `--enrich-from-index` is set. No eval sweep, no retrieval run, no
  classify/triage re-run is triggered (sprint no-re-runs guard). Default path performs zero corpus
  I/O.
- **NFR-3 Offline, no-heavy-import test path.** The enrichment is exercised by injecting a fake
  in-memory `{doc_id: text}` dict directly into `replay_jsonl(..., doc_lookup=...)` — no
  `corpus.jsonl` file I/O, no LanceDB, no Phoenix, no network. Tests use the existing
  `NoOpScoreSink` / a fake sink (mirroring `tests/observability/test_exporter.py`).
- **NFR-4 House structure + boundary rule.** The heavy/external read (`read_corpus`,
  `CORPUS_PATH`) lives at the CLI/exporter boundary (`cli.py` builds the map; `exporter.py`
  consumes a plain `Mapping`); the pure mapper is untouched. argparse + `logging` patterns inherit
  from the existing `cli.py`.
- **NFR-5 Test mirror.** Enrichment tests land in `tests/observability/test_exporter.py` (existing
  file, package has `__init__.py`); CLI-flag wiring may add a focused test there or in a sibling
  `tests/observability/test_cli.py`. No flat `tests/test_*.py`. `make lint test` is the gate.
- **NFR-6 Determinism.** Same JSONL + same `doc_lookup` → identical retriever-span `attributes`
  dicts across runs and hosts (the loop iterates `enumerate(retrieval_ranked_ids)` in list order;
  the `Mapping` lookup is positional, not iteration-order dependent).

## Acceptance Criteria

Each AC is checkable by a unit test in `tests/observability/test_exporter.py` (or
`tests/observability/test_cli.py`); FR-6/NFR-1 are checkable by a source/import assertion.

- **AC-1 Opt-in default = no behavior change.** Calling `replay_jsonl(path, sink, project=...)`
  **without** `doc_lookup` (default `None`) produces retriever-span attributes containing exactly
  the `.id` and `.rank` keys per ranked doc and **no** `.content` key — byte-identical to the
  pre-change output for the same input.
- **AC-2 Content hydration with a fake lookup.** Given a record with
  `retrieval_ranked_ids = ["d1", "d2"]` and `doc_lookup = {"d1": "alpha text", "d2": "beta text"}`,
  `replay_jsonl(..., doc_lookup=...)` yields retriever-span attributes where
  `retrieval.documents.0.document.content == "alpha text"` and
  `retrieval.documents.1.document.content == "beta text"`, while the corresponding `.id`
  (`"d1"`/`"d2"`) and `.rank` (`0`/`1`) keys remain present and unchanged. No file I/O occurs.
- **AC-3 Missing-doc-id → omit + warn (no crash).** Given `retrieval_ranked_ids = ["d1", "dX"]`
  and `doc_lookup = {"d1": "alpha text"}`, the run completes without raising; the retriever-span
  attributes contain `retrieval.documents.0.document.content` but **no**
  `retrieval.documents.1.document.content` key (omitted, not empty-string), and a warning naming
  `"dX"` is logged (assert via `caplog`).
- **AC-4 No `.score` in v1.** For any record and any `doc_lookup` (including a full map), the
  retriever-span attributes contain **no** key matching `retrieval.documents.{i}.document.score`.
- **AC-5 `attributes.py` purity + unchanged signature.** `build_span_attrs` keeps the signature
  `build_span_attrs(record: EvalRecord)` (assert via `inspect.signature` — one positional param,
  no `doc_lookup`), and `observability.attributes` imports nothing from `retrieval`, `ingest`,
  `phoenix`, or `opentelemetry`/`otel` (assert by scanning module imports / `inspect.getsource`).
  The `.id`/`.rank` keys it emits are unchanged.
- **AC-6 Offline guarantee — no LanceDB / no Phoenix.** The full enrichment test path runs with a
  fake in-memory `doc_lookup` and a no-op/fake sink: no `corpus.jsonl` is opened, no LanceDB store
  is instantiated, no Phoenix endpoint is contacted, no network access occurs.
- **AC-7 CLI flag wires the map.** `rag-export-traces --enrich-from-index --dry-run` parses
  successfully and (with `--enrich-from-index`) triggers a single `read_corpus(CORPUS_PATH)` →
  `{doc.id: doc.text}` build before replay; **without** the flag, `read_corpus` is **not** called
  (assert via patched `read_corpus` / call-count, no real corpus needed). `rag-export-traces --help`
  exits 0 and lists `--enrich-from-index`.
- **AC-8 Map shape from corpus.** Building the map from a fake corpus iterable of `Document`s
  yields `{doc.id: doc.text}` (keys = `Document.id`, values = `Document.text`), and that map drives
  AC-2 hydration end-to-end via the CLI path.

## Resolved Decisions

The 5 BRAINSTORM open questions — all resolved to their stated leanings from the artifacts
(decisive code finding + sprint Risks + MoSCoW). `AskUserQuestion` was **not** invoked: none is a
surviving blocking ambiguity — score-deferral, missing-id, corpus-path, stub-comment, and the
ADR call are each settled by the BRAINSTORM leanings and the sprint plan, so re-litigating them
was unnecessary.

1. **Score deferral (OQ-1).** **Confirmed: v1 hydrates content + rank only; `.score` is OUT.**
   `EvalRecord.retrieval_ranked_ids` is `list[str]` (no scores); the RRF fused score is never
   persisted, and offline derivation needs a retrieval re-run (forbidden by the no-re-runs guard).
   Rank (`retrieval.documents.{i}.document.rank = i`, already written) is the available ordering
   signal and content satisfies "see what was retrieved." Persisting score is a future upstream
   `EvalRecord` schema change. Encoded as FR-7 + AC-4.
2. **Missing-doc-id behavior (OQ-2).** **Confirmed: omit the `.content` attribute + log a
   warning** (the BRAINSTORM "omit + warn" leaning). Omitting keeps Phoenix spans clean (no
   empty/garbage value) and is cleaner than empty-string for the Phoenix UI; the path never
   crashes. Encoded as FR-5 + AC-3.
3. **Corpus path resolution (OQ-3).** **Confirmed: default to `retrieval.config.CORPUS_PATH`.**
   `--corpus` override is a **Should** (FR-8), added only if cheap; `CORPUS_PATH`-only is the
   acceptable v1. For reproducibility, the config path is the canonical default.
4. **`attributes.py` stub comment (OQ-4).** **Confirmed: replace the stale stub block (lines
   39–44).** The seam is now live at the exporter boundary, so the comment becomes a brief note —
   "enrichment activated in Phase 16; applied at the exporter boundary (`exporter.py`), not in this
   pure mapper." No code/signature change to `build_span_attrs`. Encoded as FR-6 + AC-5.
5. **ADR trigger (OQ-5).** **Confirmed: no ADR.** The coupling is a stdlib `Mapping[str, str]`
   passed as a function argument at the boundary — the sprint plan's "ADR only if the coupling
   proves non-trivial" condition is not met. No `docs/adr/00xx` deliverable for this phase.

## Dependencies + Infrastructure Readiness

| Dependency                                                                                                                 | Type   | KB domain                                    | Specialist   | Status                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `observability/attributes.py` (`build_span_attrs`, `.id`/`.rank` loop, FR-12/AC-14 stub at lines 39–44)                    | module | observability (`span-attribute-mapping`)     | —            | Ready — signature + key prefix `retrieval.documents.{i}.document.*` confirmed in source; only the stub comment changes |
| `observability/exporter.py` (`replay_jsonl`, `build_span_attrs(record)` call site ~line 79, retriever-span write ~line 92) | module | observability (`dashboard-phoenix-boundary`) | —            | Ready — gains the `doc_lookup` kw-param + boundary enrich; call site confirmed                                         |
| `observability/cli.py` (`rag-export-traces` parser, `_build_parser`)                                                       | module | observability                                | —            | Ready — append `--enrich-from-index` (and Should `--corpus`) alongside existing flags                                  |
| `ingest/writer.py::read_corpus` + `ingest/schema.py::Document` (`.id`, `.text`)                                            | module | rag-ingest                                   | —            | Ready — `read_corpus(path) -> Iterator[Document]`; `Document.id`/`Document.text` confirmed; read-only                  |
| `retrieval/config.py::CORPUS_PATH`                                                                                         | config | rag-retrieval                                | —            | Ready — canonical corpus path; default for `--enrich-from-index`                                                       |
| `eval/records.py::EvalRecord.retrieval_ranked_ids` (`list[str]`, doc-level, no scores)                                     | module | rag-eval (`eval-record-schema`)              | —            | Ready — confirms doc-level IDs + score-absence (FR-7)                                                                  |
| `tests/observability/` (`test_exporter.py`, `__init__.py`)                                                                 | tests  | —                                            | —            | Ready — existing package; enrichment + CLI tests mirror here (no flat test file)                                       |
| `/update-kb observability` (refresh `span-attribute-mapping` + `dashboard-phoenix-boundary`)                               | KB     | observability                                | kb-architect | **Correctly deferred (not a Phase-16 gap)** — Sprint-Wide Knowledge Plan lands it **after** this impl                  |

**No new KB, agent, command, or `--deep-research` needed for this phase.** The observability KB is
rich (`span-attribute-mapping` documents the OpenInference `retrieval.documents.*.document.content`
convention and the FR-12 seam; `dashboard-phoenix-boundary` documents the keep-heavy-import-at-the-
boundary rule; ADR-0004 records the 8 GB Phoenix-container constraint). The post-impl
`/update-kb observability` refresh is **deliberately deferred** per the sprint plan — so the absence
of an "activated seam" KB note today is expected, not a readiness gap.

## Out of Scope (Won't — Phase 16)

- **`retrieval.documents.{i}.document.score`** — scores are not persisted in `EvalRecord`; deriving
  them needs a retrieval re-run (no-re-runs guard). Future upstream `EvalRecord` schema change.
- **Re-running retrieval / the eval sweep / `rag-classify` / `rag-triage`** — enrichment consumes
  the already-published `corpus.jsonl` read-only (no-re-runs guard).
- **Importing `BM25Index`, `LanceDBStore`, `BGEEmbedder`, or any retrieval/index artifact** into
  the enrichment path — the doc-level-ID finding makes the `corpus.jsonl` map sufficient.
- **Any import from `retrieval/`, `ingest/`, Phoenix, or OTel into `observability/attributes.py`** —
  the pure mapper stays stdlib + pydantic + `EvalRecord` only (NFR-1).
- **A `DocContentLookup` Protocol or any added abstraction layer** — a stdlib `Mapping[str, str]`
  is sufficient (Approach B; Approach C rejected).
- **A signature/parameter change to `build_span_attrs`** — only its stub comment changes
  (Approach B, not Approach A).
- **Making enrichment the default** — it is explicit opt-in via `--enrich-from-index`.
- **Hydrating `retrieval.documents.{i}.document.metadata`** (title / source_type) — Could,
  deferred; v1 hydrates content only.
- **An ADR for this phase** — coupling is a trivial boundary `Mapping` (OQ-5 Confirmed).

## Clarity Score

| Dimension        | Score          | Note                                                                                                                                                                                                         |
| ---------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Problem          | 3              | Root cause + evidence: `attributes.py:35–44` writes only `.id`/`.rank` and stubs `.content`; doc-level-ID finding (`records.py:92`, `read_corpus`) makes the corpus-map fix concrete.                        |
| Users            | 3              | Named roles with workflow impact: maintainer debugging in Phoenix (primary), repo reviewer, the pure mapper as the constraint to protect, upstream corpus source, post-impl KB.                              |
| Success          | 3              | 8 falsifiable, unit-testable ACs: opt-in default-no-change, fake-lookup hydration, missing-id omit+warn, no-`.score`, `attributes.py` purity/unchanged-signature, offline no-LanceDB/no-Phoenix, CLI wiring. |
| Scope            | 3              | MoSCoW inherited from BRAINSTORM with an explicit Won't list; score-deferral, missing-id, corpus-path, stub-comment, and ADR-skip all resolved.                                                              |
| Constraints      | 3              | All named: `attributes.py` purity (no new import / unchanged signature), opt-in/default-off/read-only, no-re-run, boundary-only heavy read, offline test path, determinism.                                  |
| **Total: 15/15** | **PASS (≥12)** |                                                                                                                                                                                                              |

## Next Step

→ `/design sprint-5/phase-16-phoenix-enrichment`
