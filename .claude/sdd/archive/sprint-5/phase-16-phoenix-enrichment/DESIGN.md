# DESIGN: sprint-5/phase-16-phoenix-enrichment — Phoenix Trace Enrichment

**Sprint/Phase:** sprint-5/phase-16-phoenix-enrichment | **Date:** 2026-06-02
**Branch:** `sprint-5/phase-16-phoenix-enrichment`
**Approach:** B (post-process enrich at the `exporter.py` boundary; `attributes.py`
structurally unchanged except its stub comment) — **no ADR** (trivial stdlib `Mapping`
coupling at the boundary; OQ-5 Confirmed).

---

## Architecture

The feature activates the long-stubbed `retrieval.documents.{i}.document.content` seam by
hydrating doc text **at the exporter boundary**, never in the pure attribute mapper. The
decisive code finding (BRAINSTORM): `EvalRecord.retrieval_ranked_ids: list[str]`
(`eval/records.py:92`) holds **doc-level** IDs identical to `Document.id` in
`corpus.jsonl`, so a `{doc_id: text}` map built via the shipped `read_corpus()` is
sufficient — **zero BM25/LanceDB/embedder import** anywhere on this path.

### Data flow (opt-in path, `--enrich-from-index` set)

```
rag-export-traces --enrich-from-index [--corpus PATH]
        │
        ▼  cli.py::main
  read_corpus(corpus_path)               # from enterprise_rag_ops.ingest.writer
  corpus_path default = CORPUS_PATH      # from enterprise_rag_ops.retrieval.config
        │
        ▼  built ONCE, before the replay loop (FR-2)
  doc_lookup = {doc.id: doc.text for doc in read_corpus(corpus_path)}
        │
        ▼  passed as keyword-only arg (FR-3)
  replay_jsonl(path=..., sink=..., project=..., dry_run=..., doc_lookup=doc_lookup)
        │
        ▼  per record, inside the existing for-loop (exporter.py:78)
  span_attrs = build_span_attrs(record)          # exporter.py:79 — UNCHANGED
        │
        ▼  NEW post-process step, inserted between line 79 and the retriever
        │  span open at line 92 (FR-4)
  if doc_lookup is not None:
      for i, doc_id in enumerate(record.retrieval_ranked_ids):
          if doc_id in doc_lookup:
              span_attrs["retriever"][
                  f"retrieval.documents.{i}.document.content"
              ] = doc_lookup[doc_id]
          else:
              logger.warning(...)            # FR-5: omit + warn, never raise
        │
        ▼  retriever span opens UNCHANGED (exporter.py:92–96)
  with sink.start_span(name="retriever", openinference_span_kind="retriever",
                       attributes=span_attrs["retriever"]) as retriever_span: ...
```

### Default path (no flag — `doc_lookup=None`) is byte-identical (AC-1)

When `--enrich-from-index` is absent, `cli.py::main` never calls `read_corpus` and passes
**no** `doc_lookup` to `replay_jsonl`; the new keyword-only param defaults to `None`. The
post-process block is guarded by `if doc_lookup is not None:` — so for `None` it is
**not entered at all**, and `span_attrs["retriever"]` reaches `sink.start_span` exactly as
`build_span_attrs(record)` produced it. No corpus I/O occurs (NFR-2). The retriever-span
`attributes` dict therefore contains exactly the `.id` and `.rank` keys the current code
emits and **no** `.content` key — bit-for-bit identical to today's output. This is why
AC-1 holds purely structurally, not by re-deriving the old output.

### `attributes.py` is structurally untouched (NFR-1 / AC-5)

`build_span_attrs(record: EvalRecord) -> dict[str, dict[str, Any]]`
(`attributes.py:11`) keeps its exact signature, its imports (`typing.Any` at line 6,
`EvalRecord` at line 8), and its `.id`/`.rank` loop (lines 35–37). The **only** edit is
replacing the now-stale stub comment block (lines 39–44, "out of scope for Phase 7") with
a brief note that enrichment is live and applied at the exporter boundary. No import is
added; no parameter is added; no key emitted by the loop changes. The seam **moved** to
the boundary, so the comment is load-bearing documentation pointing a future reader to
`exporter.py`.

---

## File Manifest

| File                                                 | Change                                                                                                                                                                                                                                                         | Owner  | Phase order    |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------- |
| `src/enterprise_rag_ops/observability/exporter.py`   | edit — add keyword-only `doc_lookup: Mapping[str, str] \| None = None` to `replay_jsonl`; add `from collections.abc import Mapping`; insert the FR-4/FR-5 post-process block between line 79 and line 92                                                       | direct | 3 (core)       |
| `src/enterprise_rag_ops/observability/cli.py`        | edit — add `--enrich-from-index` (`store_true`) and Should `--corpus` (default `CORPUS_PATH`) to `_build_parser`; in `main`, build `doc_lookup` via `read_corpus` when the flag is set and pass it to `replay_jsonl`; add imports `read_corpus`, `CORPUS_PATH` | direct | 4 (CLI wiring) |
| `src/enterprise_rag_ops/observability/attributes.py` | edit — replace the stale stub comment block (lines 39–44) **only**; no import / signature / key change                                                                                                                                                         | direct | 5 (doc)        |
| `tests/observability/test_exporter.py`               | extend — add enrichment tests (AC-1, AC-2, AC-3, AC-4, AC-6, AC-8) + the `attributes.py` purity assertion (AC-5) + the CLI-wiring test (AC-7)                                                                                                                  | direct | 6 (tests)      |
| `tests/observability/__init__.py`                    | no change (exists) — confirms package layout, no flat `tests/test_*.py` (NFR-5)                                                                                                                                                                                | direct | 6 (tests)      |

**No new src modules. No new package. No `tests/observability/test_cli.py`** — that file
does **not** exist today; the existing CLI tests (`test_cli_endpoint_precedence`,
`test_cli_dry_run`) already live in `test_exporter.py`, so AC-7 folds there (NFR-5 permits
either; consistency with the current layout favors `test_exporter.py`).

---

## Implementation Phases

Ordered per the convention: core module (`exporter.py`) → CLI wiring (`cli.py`) → docs
(`attributes.py` comment) → tests. No data-schema/config/eval/observability-hook phases
apply (no schema or config change; the observability module _is_ the core here).

### Phase 3 — Core: `exporter.py` signature + boundary enrichment (FR-3, FR-4, FR-5)

1. **Import.** Add `from collections.abc import Mapping` (stdlib — `exporter.py` already
   imports `logging` at line 3 and `from typing import Any` at line 6; `logger` exists at
   line 12). **No** retrieval/Phoenix/OTel import is added (FR-3).
2. **Signature.** Extend `replay_jsonl` (line 24) to:
   ```python
   def replay_jsonl(
       path: str | Path,
       sink: ScoreSink,
       *,
       project: str,
       dry_run: bool = False,
       doc_lookup: Mapping[str, str] | None = None,
   ) -> ReplaySummary:
   ```
   Keyword-only (after the existing `*`), default `None`. Update the docstring with a
   one-line note for `doc_lookup`.
3. **Post-process block.** Inside the `for record in records:` loop (line 78),
   immediately after `span_attrs = build_span_attrs(record)` (line 79) and **before** the
   chain/retriever spans open (line 83/92), insert:

   ```python
   if doc_lookup is not None:
       for i, doc_id in enumerate(record.retrieval_ranked_ids):
           if doc_id in doc_lookup:
               span_attrs["retriever"][
                   f"retrieval.documents.{i}.document.content"
               ] = doc_lookup[doc_id]
           else:
               logger.warning(
                   "doc_id %r in retrieval_ranked_ids not found in corpus map; "
                   "omitting .content for retrieval.documents.%d", doc_id, i
               )
   ```

   - FR-4: writes `.content` per present ranked ID; preserves the `.id`/`.rank` keys
     `build_span_attrs` already set (the block only _adds_ keys).
   - FR-5: on a miss, **omit** the `.content` key (no empty string, no placeholder), log a
     `logging.warning` naming the missing `doc_id`, continue; never raise.
   - FR-7: writes **no** `.score` key.
   - Determinism (NFR-6): iterates `enumerate(record.retrieval_ranked_ids)` in list order;
     the `in`/`[]` lookups are positional, not iteration-order dependent.

4. Everything from line 83 onward (chain → retriever → generation → judge spans, score
   rows, flush) is **unchanged**; the retriever span at line 92–96 still passes
   `attributes=span_attrs["retriever"]`, now optionally enriched.

### Phase 4 — CLI wiring: `cli.py` flag + map build (FR-1, FR-2, FR-8)

1. **Imports.** Add `from enterprise_rag_ops.ingest.writer import read_corpus` and
   `from enterprise_rag_ops.retrieval.config import CORPUS_PATH`.
2. **`_build_parser`** — append two arguments after the existing `--dry-run` (line 70):
   ```python
   parser.add_argument(
       "--enrich-from-index",
       action="store_true",
       help="Hydrate retrieval.documents.{i}.document.content on retriever spans "
            "from corpus.jsonl (opt-in; default off).",
   )
   parser.add_argument(           # FR-8 Should — may be dropped to CORPUS_PATH-only
       "--corpus",
       default=str(CORPUS_PATH),
       help="Path to corpus.jsonl for --enrich-from-index (default: CORPUS_PATH).",
   )
   ```
3. **`main`** — before the `replay_jsonl(...)` call (line 103), build the map only when
   the flag is set:
   ```python
   doc_lookup = None
   if args.enrich_from_index:
       doc_lookup = {doc.id: doc.text for doc in read_corpus(Path(args.corpus))}
   ```
   (If FR-8 `--corpus` is dropped, use `read_corpus(CORPUS_PATH)`.) Then pass
   `doc_lookup=doc_lookup` into the existing `replay_jsonl(path=..., sink=..., project=...,
dry_run=...)` call. FR-2: the map is built **once**, before the replay loop. NFR-2:
   when the flag is absent, `read_corpus` is never called → zero corpus I/O.

### Phase 5 — Doc: `attributes.py` stub comment (FR-6)

Replace lines 39–44 (the `# SEAM: --enrich-from-index (FR-12 / AC-14)` block referencing
"a future phase" / "out of scope for Phase 7") with a brief note, e.g.:

```python
# Enrichment activated in Phase 16: retrieval.documents.{i}.document.content is
# hydrated at the exporter boundary (observability/exporter.py), not in this pure
# mapper, to keep attributes.py free of retrieval/ingest imports (NFR-1). Score
# (.score) remains out — not persisted in EvalRecord (FR-7).
```

No code/signature/import change. The `.id`/`.rank` loop (lines 35–37) is untouched.

### Phase 6 — Tests: `tests/observability/test_exporter.py` (AC-1..AC-8)

Reuse the existing offline harness: `FakeScoreSink` (in-memory, captures `span.attributes`)
and the `two_record_jsonl_content` fixture (record 1 has
`retrieval_ranked_ids = ["doc_1", "doc_2"]`). Inject a fake `{doc_id: text}` dict straight
into `replay_jsonl(..., doc_lookup=...)` — **no `corpus.jsonl`, no LanceDB, no Phoenix, no
network** (NFR-3 / AC-6).

| AC       | Test                                   | Mechanism                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **AC-1** | `test_enrich_default_off_no_content`   | `replay_jsonl(jsonl, sink, project=...)` with **no** `doc_lookup`; assert retriever span has `.id`/`.rank` keys and `"retrieval.documents.0.document.content" not in attributes`.                                                                                                                                                                                                                                                                                                                                         |
| **AC-2** | `test_enrich_hydrates_content`         | record with ids `["d1","d2"]` (write a focused 1-record JSONL), `doc_lookup={"d1":"alpha text","d2":"beta text"}`; assert `...0.document.content=="alpha text"`, `...1.document.content=="beta text"`, and `.id`/`.rank` unchanged.                                                                                                                                                                                                                                                                                       |
| **AC-3** | `test_enrich_missing_id_omit_and_warn` | ids `["d1","dX"]`, `doc_lookup={"d1":"alpha text"}`, run under `caplog.at_level(logging.WARNING)`; assert no raise, `...1.document.content` absent, warning text contains `"dX"`.                                                                                                                                                                                                                                                                                                                                         |
| **AC-4** | `test_enrich_no_score_key`             | any record + full `doc_lookup`; assert no key matching `retrieval.documents.{i}.document.score` on the retriever span.                                                                                                                                                                                                                                                                                                                                                                                                    |
| **AC-5** | `test_attributes_purity_and_signature` | `inspect.signature(build_span_attrs)` has exactly one positional param (`record`), no `doc_lookup`; scan `inspect.getsource`/module to assert no import of `retrieval`, `ingest`, `phoenix`, `opentelemetry`/`otel`.                                                                                                                                                                                                                                                                                                      |
| **AC-6** | covered by AC-2/AC-3 construction      | fake in-memory `doc_lookup` + `FakeScoreSink`; no file/LanceDB/Phoenix/network touched.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **AC-7** | `test_cli_enrich_wires_corpus_map`     | patch `enterprise_rag_ops.observability.cli.read_corpus` to return a fake `Document` iterable and patch `replay_jsonl`; run `cli.main([..., "--enrich-from-index", "--dry-run"])` → assert `read_corpus` called **once** and `replay_jsonl` received a non-`None` `doc_lookup`; run **without** the flag → assert `read_corpus` **not** called and `doc_lookup is None`. Also `cli.main(["--help"])` raises `SystemExit(0)` and help text lists `--enrich-from-index` (capture via `capsys`/`pytest.raises(SystemExit)`). |
| **AC-8** | `test_corpus_map_shape`                | fake iterable of `Document(id=..., text=..., source_type=..., metadata={})`; assert `{doc.id: doc.text for doc in fake}` shape, then drive AC-2 hydration through the patched CLI path.                                                                                                                                                                                                                                                                                                                                   |

`make lint test` is the gate (NFR-5).

---

## Infrastructure Gaps

Three-layer check vs `.claude/kb/_index.yaml` and `.claude/agents/`.

| Gap Type           | Area | Detail                                                                                                                                                                                                                                                                                                                                                                             | Recommendation |
| ------------------ | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| Missing domain     | —    | **None.** The `observability` domain exists (`_index.yaml:114`).                                                                                                                                                                                                                                                                                                                   | —              |
| Missing concept    | —    | **None.** `span-attribute-mapping` (`_index.yaml:140`) documents the OpenInference `retrieval.documents.*.document.content` convention and the FR-12 seam; `dashboard-phoenix-boundary` (`_index.yaml:162`) documents the keep-heavy-import-at-the-boundary rule. `eval-record-schema` (rag-eval) confirms `retrieval_ranked_ids: list[str]`. Coverage is complete for this phase. | —              |
| Missing specialist | —    | **None needed.** No observability specialist agent exists (`.claude/agents/` holds only workflow + kb-architect agents); per the manifest, every file is `direct`. The change is small (3 edits + tests) and within the existing module — no recurring specialist context to justify a new agent.                                                                                  | —              |

**Deferred-by-design (not a gap):** `/update-kb observability` to refresh
`span-attribute-mapping` + `dashboard-phoenix-boundary` for the now-live seam lands
**after** this impl per the Sprint-Wide Knowledge Plan (DEFINE Dependencies row;
BRAINSTORM "after impl"). Its absence today is expected.

**No new KB, agent, command, or `--deep-research` for this phase.**

---

## Consistency Check

Multi-file but small (3 src edits + tests, 8 ACs, no new module). Full 6-pass check run.

**Verdict: ✅ CONSISTENT** — no CRITICAL/HIGH drift; one MEDIUM clarification (the `--corpus`
Should is optional, already labeled) and one LOW note.

| ID  | Severity | Pass                      | Location               | Finding                                                                                                                                                                                                                                               | Suggested fix                                                                                                                                |
| --- | -------- | ------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | LOW      | 1 Duplication             | FR-4 vs FR-7 / AC-4    | "no `.score`" stated in both FR-7 and AC-4; complementary (requirement vs test), not contradictory.                                                                                                                                                   | None — keep both.                                                                                                                            |
| C-2 | MEDIUM   | 2 Ambiguity / 3 Underspec | FR-8 `--corpus`        | Marked a **Should** ("if it complicates the diff, `CORPUS_PATH` alone is acceptable v1"). No AC tests `--corpus` directly.                                                                                                                            | Implementer note: `--corpus` may be dropped without failing any AC; AC-7 uses `CORPUS_PATH` via the patched `read_corpus`. Flagged in Risks. |
| C-3 | — (pass) | 4 Constitution            | `attributes.py` purity | **NFR-1/AC-5 invariant honored** — no manifest entry adds an import or parameter to `attributes.py`; the only edit is the stub comment. Approach-B purity preserved.                                                                                  | None.                                                                                                                                        |
| C-4 | — (pass) | 4 Constitution            | `Mapping` import       | Sourced from `collections.abc` (stdlib) — not a new heavy dependency; consistent with "boundary-only heavy read" (NFR-4) and § Engineering Behavior "minimal scope".                                                                                  | None.                                                                                                                                        |
| C-5 | — (pass) | 4 Constitution            | seam justification     | The activated seam is a _named, shipped_ change (FR-12 stub → live), not speculative "in case." No stranger-test leak in new files/tests (all about the system).                                                                                      | None.                                                                                                                                        |
| C-6 | — (pass) | 5 Coverage                | FR-1..8 / NFR-1..6     | Every requirement maps to ≥1 manifest entry (see table below). No orphan requirement; no manifest entry without a backing requirement.                                                                                                                | None.                                                                                                                                        |
| C-7 | LOW      | 6 Inconsistency           | flag name vs impl      | `--enrich-from-index` names "index" but the impl reads `corpus.jsonl` (no BM25/LanceDB). BRAINSTORM §Recommended (point at flag name) resolves this: the name signals "enriched from published artifacts," kept for traceability with the FR-12 seam. | None — intentional, documented.                                                                                                              |

**Requirement → manifest coverage (pass 5):**
FR-1→cli.py; FR-2→cli.py; FR-3→exporter.py (signature); FR-4→exporter.py (block);
FR-5→exporter.py (warn/omit); FR-6→attributes.py (comment); FR-7→exporter.py (no `.score`
written) + AC-4 test; FR-8→cli.py (`--corpus`, Should). NFR-1→attributes.py untouched +
AC-5; NFR-2→cli.py guard + default `None`; NFR-3/AC-6→test harness (fake dict, FakeSink);
NFR-4→cli.py builds / exporter.py consumes `Mapping`; NFR-5→`test_exporter.py` mirror;
NFR-6→list-order loop. All ACs map to a Phase-6 test row.

No CRITICAL/HIGH findings; safe to implement.

---

## Risks & Trade-offs

- **The stub-comment update is load-bearing (FR-6).** The seam **moved** from
  `attributes.py` to the exporter boundary. If the comment still pointed "here, in a
  future phase," a future maintainer would look for enrichment in the pure mapper and not
  find it. The replacement must explicitly redirect to `exporter.py`. This is the one
  place Approach B trades discoverability (two-step: build attrs, then mutate) for
  `attributes.py` purity — the comment is how that trade-off is paid back.
- **`--corpus` Should can be cut (FR-8 / C-2).** If it complicates the diff, ship
  `CORPUS_PATH`-only; **no AC fails** (AC-7 patches `read_corpus`, never depending on a
  `--corpus` flag value). Decide at implement time; default to including it (one argparse
  line) unless it adds friction.
- **No ADR — and that is correct (OQ-5).** Unlike Phase 15 (which produced an ADR), this
  phase's coupling is a stdlib `Mapping[str, str]` passed at a function boundary — the
  sprint's "ADR only if the coupling proves non-trivial" bar is **not** met. No
  `docs/adr/00xx` deliverable. Recording this explicitly prevents a reviewer from flagging
  a missing ADR.
- **Coupling-regression risk (sprint Risk) is structurally closed.** Because nothing in
  `attributes.py` changes but a comment, and `exporter.py` only gains a stdlib
  `Mapping` + a guarded loop, the pure mapper's unit-testability and zero lock-in are
  preserved by construction (AC-5 asserts it).
- **No-re-runs guard honored.** The path reads `corpus.jsonl` read-only via `read_corpus`;
  no eval sweep / retrieval / classify / triage is triggered. `EvalRecord` is consumed
  as-published.

---

## Next Step

→ `/implement sprint-5/phase-16-phoenix-enrichment`

Implement normally runs in **Antigravity / Gemini** against this `DESIGN.md` as the
cross-tool contract (AGENTS.md § Implement Contract). Given the prior Antigravity hang, it
**may** instead be done directly in **Claude Code** — the manifest above (exact signatures,
the post-process block, line anchors, and the AC→test table) is equally implementable
either way from `DESIGN.md` + `DEFINE.md` alone. Confirm the branch
`sprint-5/phase-16-phoenix-enrichment`, then implement phases 3→4→5→6 and run
`make lint test`.
