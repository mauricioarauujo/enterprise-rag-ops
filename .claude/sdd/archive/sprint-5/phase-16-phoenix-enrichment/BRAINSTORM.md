# BRAINSTORM: sprint-5/phase-16-phoenix-enrichment — Phoenix Trace Enrichment

**Sprint/Phase:** sprint-5/phase-16-phoenix-enrichment | **Date:** 2026-06-02

---

## Problem Statement

The retriever span in Phoenix currently shows only doc IDs and ranks — clicking a failed
trace gives no readable context about what was retrieved. The FR-12/AC-14 seam in
`attributes.py` was deliberately stubbed; this phase activates it so `--enrich-from-index`
hydrates `retrieval.documents.{i}.document.content` onto each retriever span, making the
"click a failed trace → see why" question answerable visually in Phoenix. The enrichment
must remain opt-in and the heavy import must stay at the CLI/exporter boundary so
`attributes.py` keeps its zero-lock-in, unit-testable shape (NFR-3).

---

## Decisive Code Finding: `retrieval_ranked_ids` Are Doc-Level IDs

Resolved from `hybrid_retriever.py::retrieve()` → `deduplicate_to_docs()` and
`pipeline.py` line 128 (`chunk_to_doc = {cid: cid.split("::", 1)[0] for cid in
chunk_order}`):

- `retrieve()` returns `list[tuple[doc_id, score]]` — **doc-level**, not chunk-level.
- `EvalRecord.retrieval_ranked_ids: list[str]` stores those doc-level IDs.
- `Document.id` in `corpus.jsonl` is the same key.

**Consequence:** content enrichment does NOT require the LanceDB chunk store. A simple
`{doc_id: text}` map built from `corpus.jsonl` via the existing `read_corpus()` function
is sufficient — the entire "heavy index import" risk the sprint flags is avoidable. The
feature can be implemented with **zero BM25/LanceDB dependency** in the enrichment path.

**Score finding:** `EvalRecord.retrieval_ranked_ids` is `list[str]` — no scores stored.
The RRF fused score exists during retrieval but is never persisted to the JSONL. Offline
score hydration requires re-running retrieval (forbidden by the no-re-runs guard). List
position (rank, already written as `retrieval.documents.{i}.document.rank = i`) is the
only ordering signal available. Score hydration is out of scope for v1 and would require
an upstream schema change to `EvalRecord` to persist it — a future concern.

---

## Suggested Research & KB Work

| Topic                                                                          | KB Coverage                                                                                                                                                       | Action          |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| OpenInference `retrieval.documents.{i}.document.content` / `.score` convention | Sufficient — `span-attribute-mapping.md` documents the convention and explicitly marks `.content` / `.score` as the stubbed seam (FR-12)                          | No new research |
| "Keep heavy import at the boundary" rule                                       | Sufficient — `dashboard-phoenix-boundary.md` (data.py purity seam) and the module docstring of `attributes.py` both express this                                  | No new research |
| Phoenix hardware constraint                                                    | Sufficient — ADR-0004 acceptance note: single lightweight container on 8 GB RAM                                                                                   | No new research |
| Doc-level vs chunk-level ID — corpus.jsonl lookup feasibility                  | Resolved from code (see above)                                                                                                                                    | No new research |
| Post-impl KB refresh                                                           | Deferred — sprint plan: `/update-kb observability` after Phase 16 impl to refresh `span-attribute-mapping` and `dashboard-phoenix-boundary` for the now-live seam | After impl      |

No `--deep-research` needed. The observability KB is rich; the decisive question was
resolvable from the codebase.

---

## Approaches Considered

| Axis                            | Approach A: Param injection on `build_span_attrs`                                                                                         | Approach B: Post-process enrich step in `exporter.py`                                                                                  | Approach C: `DocContentLookup` Protocol seam                                                                   |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Enrichment location             | Optional `doc_lookup: Mapping[str, str] \| None` parameter added to `build_span_attrs`; caller (exporter) builds the map and passes it in | `exporter.py` post-processes `span_attrs["retriever"]` after `build_span_attrs` returns, mutating the dict if `doc_lookup` is provided | A `DocContentLookup` Protocol class injected into `replay_jsonl` / `exporter.py`; `attributes.py` is untouched |
| Content source                  | `corpus.jsonl` doc-map (light, zero index) — feasible because IDs are doc-level                                                           | Same                                                                                                                                   | Same                                                                                                           |
| `attributes.py` purity          | Preserved — `doc_lookup` is `Mapping[str, str] \| None`, a stdlib type; zero new imports                                                  | Fully preserved — `attributes.py` never sees the lookup                                                                                | Fully preserved                                                                                                |
| Score                           | Deferred — content + rank only                                                                                                            | Same                                                                                                                                   | Same                                                                                                           |
| `attributes.py` change required | Yes — one optional param + 2-line body change                                                                                             | No                                                                                                                                     | No                                                                                                             |
| `exporter.py` change required   | Yes — builds map, passes param                                                                                                            | Yes — builds map, mutates dict after call                                                                                              | Yes — builds lookup, injects protocol                                                                          |
| Test surface                    | `build_span_attrs(record, doc_lookup={"id": "text"})` is directly unit-testable                                                           | Requires testing the exporter's post-processing separately                                                                             | Protocol seam is clean but adds an extra abstraction layer                                                     |
| Complexity                      | Lowest — one param, one `if doc_lookup` branch in the loop                                                                                | Low — clean separation; `attributes.py` untouched                                                                                      | Medium — Protocol definition, injected object, additional indirection                                          |
| Effort                          | S                                                                                                                                         | S                                                                                                                                      | M                                                                                                              |

### Approach A — Param injection on `build_span_attrs`

**Pros:** Keeps enrichment logic co-located with the attribute loop in `attributes.py`
where the seam comment already lives; directly unit-testable without involving the
exporter; `Mapping[str, str]` is a stdlib type so the purity promise is kept (no heavy
import added); minimal diff.

**Cons:** `attributes.py` does change (one new optional param); the seam comment
becomes active code in the pure mapper rather than at the boundary.

### Approach B — Post-process enrich step in `exporter.py`

**Pros:** `attributes.py` is completely untouched (the stub comment simply becomes
stale); enrichment lives entirely at the boundary where the heavy import is already
expected.

**Cons:** The mutation of `span_attrs["retriever"]` happens in two steps
(`build_span_attrs` then mutate), which is less discoverable; the seam comment in
`attributes.py` becomes misleading (the seam is no longer there). Requires clearing the
stub comment to avoid confusion.

### Approach C — `DocContentLookup` Protocol seam

**Pros:** Maximum extensibility; clean Protocol boundary for future swap (e.g. LanceDB
chunk lookup if IDs ever become chunk-level in a future schema revision).

**Cons:** Protocol + injected object is premature abstraction for what is effectively a
`dict.get()` call over a static `{doc_id: text}` map; adds two extra files and
indirection for no current benefit; the corpus.jsonl map is already the right
implementation and it is unlikely to be swapped.

---

## Recommended Approach

**Approach B** — post-process enrich in `exporter.py`, with `attributes.py` left
structurally unchanged.

Rationale:

1. The sprint risk "Observability coupling regression" is most clearly addressed by
   keeping `attributes.py` unmodified — the pure mapper never sees the lookup.
2. The seam comment in `attributes.py` (`# SEAM: --enrich-from-index`) gets replaced by
   a brief "activated in phase-16; enrichment lives in exporter.py" note, or removed
   entirely, which is honest documentation rather than a stub.
3. Post-processing `span_attrs["retriever"]` in `exporter.py` is straightforward: after
   `build_span_attrs(record)`, if `doc_lookup` is provided, iterate the ranked IDs and
   set `retrieval.documents.{i}.document.content = doc_lookup.get(doc_id, "")`.
4. The CLI adds `--enrich-from-index` (which triggers `read_corpus` → build the map once
   before the replay loop); `replay_jsonl` accepts an optional `doc_lookup` param that
   defaults to `None` — the default path is bit-for-bit identical to today.
5. Content source: `corpus.jsonl` via `read_corpus()` + `{doc.id: doc.text}` — zero
   BM25/LanceDB import; the finding that IDs are doc-level makes this the natural fit.
6. Testable offline: a fake `{doc_id: "text content"}` dict exercises the full
   enrichment path without any file I/O.

The `--enrich-from-index` flag name is kept from the sprint plan and the seam comment
(FR-12/AC-14) for traceability, even though the implementation uses `corpus.jsonl`
rather than the literal BM25/LanceDB index. The flag signals "enriched from the
published artifacts" which is accurate.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                        |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | `--enrich-from-index` flag on `rag-export-traces` CLI                                                                                                                                       |
| Must     | When flag is set: build `{doc_id: text}` map from `corpus.jsonl` via `read_corpus()` once before the replay loop                                                                            |
| Must     | Pass `doc_lookup: Mapping[str, str] \| None` into `replay_jsonl` (defaults to `None`)                                                                                                       |
| Must     | In `exporter.py`: if `doc_lookup` is set, write `retrieval.documents.{i}.document.content` for each ranked ID after `build_span_attrs` returns                                              |
| Must     | `attributes.py` remains structurally unchanged — no new imports, no param changes; only the stub comment is updated                                                                         |
| Must     | Rank is already written (`retrieval.documents.{i}.document.rank = i`); verify it is present in the current code (confirmed: it is)                                                          |
| Must     | Graceful skip when a doc-id is missing from `corpus.jsonl` — `doc_lookup.get(doc_id, "")` or omit the attribute; no crash                                                                   |
| Must     | Offline unit tests using a fake in-memory `{doc_id: "content"}` dict — no file I/O, no Phoenix, no LanceDB                                                                                  |
| Must     | No eval re-run; `corpus.jsonl` is read-only over an already-published artifact                                                                                                              |
| Should   | Log a warning when a doc-id is missing from the corpus map (aids debugging without crashing)                                                                                                |
| Should   | Accept a `--corpus` flag (default: `results/baseline.jsonl`-relative or `retrieval.config.CORPUS_PATH`) so the user can point to a non-default corpus location                              |
| Could    | Hydrate `retrieval.documents.{i}.document.metadata` (e.g. `source_type`, `metadata.title` from `Document.metadata`) for richer Phoenix display                                              |
| Could    | KB update (`/update-kb observability`) to refresh `span-attribute-mapping.md` to mark `.content` as activated                                                                               |
| Won't    | Re-running retrieval or the eval sweep to derive per-doc scores                                                                                                                             |
| Won't    | Importing BM25Index, LanceDBStore, BGEEmbedder, or any retrieval artifact into `attributes.py`                                                                                              |
| Won't    | Importing any retrieval module into `attributes.py` at all — the pure mapper stays stdlib+pydantic only                                                                                     |
| Won't    | Making enrichment the default (must be explicit opt-in via `--enrich-from-index`)                                                                                                           |
| Won't    | Writing `retrieval.documents.{i}.document.score` in v1 — scores are not persisted in `EvalRecord`; rank is the available signal                                                             |
| Won't    | A `DocContentLookup` Protocol or any additional abstraction layer — `Mapping[str, str]` is sufficient                                                                                       |
| Won't    | ADR-0010 for this phase — the coupling is trivial (a stdlib Mapping passed at the boundary); an ADR is only warranted if the coupling proves non-trivial (sprint plan condition is not met) |

---

## Open Questions

1. **Score deferral confirmation.** The sprint goal says "content (+ score)". This brainstorm
   confirms that score cannot be hydrated offline without a re-run (no scores in
   `retrieval_ranked_ids`, and static corpus lookup yields content but not
   query-dependent similarity scores). Should the DEFINE accept `content + rank` only,
   with a clear "score requires upstream schema change" note, and mark that as meeting AC-14?
   (Leaning: yes — rank is already present and the sprint risk explicitly forbids re-runs.)

2. **Missing-doc-id behavior.** Should a doc-id absent from `corpus.jsonl` silently omit
   the `.content` attribute (no key written), write an empty string, or warn+skip? The
   correct default is likely "omit + warn" to keep Phoenix spans clean, but this should
   be made explicit in DEFINE.

3. **Corpus path resolution.** `retrieval/config.py::CORPUS_PATH` is the canonical path.
   Should `--enrich-from-index` always use `CORPUS_PATH` from config, or should the CLI
   expose a `--corpus` override? For reproducibility and simplicity, defaulting to
   `CORPUS_PATH` is cleanest — flag only needed if a non-default corpus is used.

4. **`attributes.py` stub comment.** The seam comment at line 39–44 references "a future
   phase" and "out of scope for Phase 7". This phase IS that future phase. The comment
   should be updated or removed. DEFINE should specify the exact replacement (a brief
   "enrichment activated in Phase 16; see exporter.py" or simply removed since the seam
   is now live).

5. **ADR trigger.** Sprint plan says "ADR only if the coupling proves non-trivial". With the
   corpus.jsonl map approach, the coupling is `Mapping[str, str]` passed as a function
   argument — clearly trivial. No ADR is needed; confirm this explicitly in DEFINE so
   there is no ambiguity.

---

## Next Step

→ `/define sprint-5/phase-16-phoenix-enrichment`
