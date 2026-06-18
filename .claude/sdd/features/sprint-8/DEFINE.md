# DEFINE: sprint-8/phase-3-trace-surfacing — Per-Fact Root-Cause on the Judge Span

**Sprint/Phase:** sprint-8/phase-3-trace-surfacing | **Date:** 2026-06-17

---

## Context & Grounding Invariant

Phases 1–2 produced the per-fact signal: phase-1 added `FactVerdict.supporting_doc_id:
str | None` (`eval/schema.py`), and phase-2 added the pure leaf
`eval/root_cause.py::classify_fact_gap(fact_verdict, retrieval_ranked_ids) ->
Literal["retrieval_gap","generation_gap"] | None` plus `FAILED_VERDICTS = {"absent",
"contradicted"}`. Phase 3 makes that signal **visible inside a single failed trace in
Phoenix**, so the trace is self-diagnosing without cross-referencing the aggregate report.

This phase serves **SC-4**: "A failed trace in Phoenix shows, per fact, the doc it was
judged against."

**The single change site** is the judge-span block of `observability/attributes.py`
(lines ~63–82). Today it builds `output.value` from:

```
fact: <fact text> -> <verdict>     # one line per FactVerdict in record.per_fact
citation: <doc_id> -> <verdict>    # one line per CitationVerdict in record.per_citation
```

Phase 3 enriches each **fact** line (not citation lines) with the per-fact
`supporting_doc_id` (Must) and the phase-2 root-cause label (Should). The chosen path is
**Approach A** from BRAINSTORM: enrich the existing `output.value` free-text block. This
is the smallest diff that satisfies SC-4 — no new attribute keys, no exporter change, no
annotation-model change, no span-tree change, no schema change, no new ADR.

**Verified purity invariant.** `attributes.py` imports only `eval.records.EvalRecord`
today; it must not import phoenix/otel. `eval/root_cause.py` is a pure leaf (imports only
`eval.schema` + `eval.records`), so importing `classify_fact_gap` / `FAILED_VERDICTS`
into `attributes.py` preserves mapper purity.

**Verified null discipline.** `record.per_fact` is `list[FactVerdict] | None`;
`FactVerdict.supporting_doc_id` is `str | None`. When `per_fact is None` (and
`per_citation` is None/empty), `output.value`/`output.mime_type` are already omitted
entirely — this null-vs-absent behavior (phases 1–2) is preserved unchanged.

---

## Requirements

### Functional

**FR-1 — Per-fact doc-id suffix on the judge span (Must, SC-4).** In `attributes.py`,
each fact line in the judge span's `output.value` is extended from
`fact: <fact text> -> <verdict>` to additionally carry the fact's `supporting_doc_id`.
The doc id (or a sentinel when it is `None`, FR-3) appears on **every** fact line
(present and failed alike — a present fact's supporting doc is still informative). The
existing `fact: <text> -> <verdict>` prefix is preserved verbatim. Citation lines are
**not** modified. The exact rendering is **locked** (A1, user-confirmed):
` [doc: <id or —>]` on every fact line, plus ` | <label>` inside the bracket on failed
facts. The contract: the doc-id token (or `—` sentinel) is present on each fact line and
the `fact: <text> -> <verdict>` prefix is byte-for-byte unchanged before the suffix begins.

**FR-2 — Root-cause label suffix on failed facts (Should).** For a fact whose
`verdict ∈ FAILED_VERDICTS`, the fact line additionally carries the phase-2 root-cause
label (`retrieval_gap` / `generation_gap`), obtained by calling
`classify_fact_gap(fv, record.retrieval_ranked_ids)`. For a `present` fact
(`classify_fact_gap` returns `None`), the root-cause label suffix is **omitted** (the
doc-id suffix from FR-1 still appears). This surfaces the phase-2 artifact onto the trace
and reuses the phase-2 predicate verbatim — no reimplementation of the gap logic.

**FR-3 — Null sentinel discipline (Must).** When `fv.supporting_doc_id is None`, the
doc-id token renders as the `—` (em-dash) sentinel — never an empty string, never the
literal word `"None"`. This mirrors the exporter-boundary null discipline documented in
`span-attribute-mapping.md` (a missing id is shown as a sentinel, never blank).

**FR-4 — Zero-lines case unchanged (Must).** When `record.per_fact is None` (and
`per_citation` is None/empty so the line set is empty), `output.value` and
`output.mime_type` remain **omitted** from the judge attrs dict — the existing guard
(`if lines:`) is preserved. A `per_fact=None` record produces no fact lines at all. The
null-vs-absent distinction from phases 1–2 is preserved end to end.

**FR-5 — Import is the only new coupling (Must).** The sole new import added to
`attributes.py` is from `eval/root_cause.py` (`classify_fact_gap` and/or
`FAILED_VERDICTS`). No phoenix, otel, retrieval, ingest, or generation import is added.
`build_score_rows` and the chain/retriever/generation span blocks are untouched.

**FR-6 — Mirrored offline tests (Must).** `tests/observability/test_attributes.py` is
updated in place (its package `__init__.py` already exists): existing fact-line
assertions are updated to the new format, and new cases are added — (a) a failed fact
with a non-None `supporting_doc_id` (asserting doc id + `generation_gap`), (b) a failed
fact with `supporting_doc_id=None` (asserting the `—` sentinel + `retrieval_gap`), (c) a
present fact (asserting the doc-id suffix present, root-cause suffix absent), and the
existing `per_fact=None` and `per_fact=[]` zero-lines cases retained. All tests are
offline over hand-built `EvalRecord`s — no network, no API key, no mocked LLM, no
cassette (the mapper makes no LLM call).

### Non-functional

**NFR-1 — Mapper purity.** `attributes.py` must not import phoenix or opentelemetry.
Importing the pure leaf `eval/root_cause.py` is the only permitted new dependency and
keeps the mapper unit-testable offline with zero tool lock-in.

**NFR-2 — Additive, no contract breakage.** No schema field is added or changed; no new
span, span kind, or span-tree shape change; no exporter (`exporter.py`) change; no
annotation-model change; no new ADR. The change is additive within ADR-0004's already
decided observability architecture and edits exactly one production file
(`attributes.py`) plus its mirrored test.

**NFR-3 — Determinism & offline.** All new code is pure and deterministic; the full
affected test surface runs under `make test` with no network, no API key, no model
download, no mocked LLM.

**NFR-4 — No new attribute keys.** The enrichment lives entirely inside the existing
`output.value` string on the judge span. No new OTEL/OpenInference attribute key is
introduced (no `eval.fact.{i}.*`); the judge attrs dict keeps the same key set.

**NFR-5 — Gate.** `make lint test` is green.

---

## Acceptance Criteria

1. **(FR-1 / SC-4, doc suffix present)** For a record with at least one fact carrying a
   non-None `supporting_doc_id`, `build_span_attrs(record)["judge"]["output.value"]`
   contains, on that fact's line, the `supporting_doc_id` value — asserted by substring.
   This is the SC-4 acceptance: a single trace's judge `output.value` shows, per fact,
   the doc it was judged against.
2. **(FR-1, prefix preserved)** For every fact line, the substring
   `fact: <fact text> -> <verdict>` appears unchanged as the line prefix (the new suffix
   is appended after it, never altering the prefix) — asserted by a startswith/substring
   check on each fact line.
3. **(FR-1, doc suffix on present facts too)** A `present` fact's line also carries its
   `supporting_doc_id` (or the `—` sentinel) suffix — asserted, confirming the doc suffix
   is symmetric across all verdicts.
4. **(FR-2 / Should, generation_gap label)** For a failed fact (`verdict == "absent"`
   and `verdict == "contradicted"`, both exercised) whose `supporting_doc_id` IS in
   `record.retrieval_ranked_ids`, the fact line contains `generation_gap` — asserted by
   substring, matching `classify_fact_gap`'s output.
5. **(FR-2 / Should, retrieval_gap label)** For a failed fact whose `supporting_doc_id`
   is `None` (or not in `retrieval_ranked_ids`), the fact line contains `retrieval_gap`.
6. **(FR-2 / Should, present omits label)** A `present` fact's line does **not** contain
   `retrieval_gap` or `generation_gap` (the root-cause suffix is gated on
   `verdict ∈ FAILED_VERDICTS`; `classify_fact_gap` returns `None` for present).
7. **(FR-3, null sentinel)** For a fact with `supporting_doc_id is None`, the fact line's
   doc token is the `—` sentinel — and the line contains neither an empty doc token nor
   the literal `"None"` — asserted explicitly.
8. **(FR-4, zero-lines unchanged)** For a record with `per_fact=None` and
   `per_citation=None`, the judge attrs dict contains neither `output.value` nor
   `output.mime_type` (existing behavior preserved). A second case with `per_fact=[]` and
   `per_citation=[]` asserts the same omission.
9. **(FR-1 regression, citation lines unchanged)** For a record with both fact and
   citation verdicts, every `citation: <doc_id> -> <verdict>` line appears byte-for-byte
   unchanged (no doc/root-cause suffix), and citation lines follow all fact lines in the
   same order as today — asserted against an expected citation-line block.
10. **(FR-5 / NFR-1, mapper purity)** `attributes.py`'s import set adds only
    `eval.root_cause` symbols; a test (or static assertion) confirms no `phoenix` /
    `opentelemetry` import is present in the module, and `exporter.py` has no diff for
    this phase.
11. **(FR-2, predicate reuse)** The root-cause label rendered for each failed fact equals
    `classify_fact_gap(fv, record.retrieval_ranked_ids)` for that fact — asserted by
    constructing a record whose facts span both gap labels and checking each line against
    the predicate's return value (no reimplemented gap logic in `attributes.py`).
12. **(NFR-4, no new keys)** The judge attrs dict's key set is unchanged from before this
    phase (still `gen_ai.*`, `latency_s`, `output.value`, `output.mime_type`, and
    conditionally `cost_usd`) — no `eval.fact.*` or other new key is emitted.
13. **(NFR-2, additive)** No diff to `eval/schema.py`, `eval/records.py`,
    `observability/exporter.py`, or `docs/adr/`; no new file under `docs/adr/`; the only
    production diff is `observability/attributes.py`.
14. **(FR-6 / NFR-3, mirrored offline tests)** `tests/observability/test_attributes.py`
    carries the updated + new cases, runs offline (no network, no API key, no mocked LLM,
    no cassette), and its package `__init__.py` is present.
15. **(NFR-5)** `make lint test` is green.

---

## Resolved Open Questions (A1–A2 CONFIRMED by user; A3–A4 aligned assumptions)

A1 and A2 were **confirmed by the user** (2026-06-17) via `AskUserQuestion` with rendered
previews — they are now **locked decisions**, not assumptions, and `/design` MUST use the
exact string below for the test fixtures. A3–A4 are minor priority/scope choices resolved
to SPRINT/code-aligned defaults and flagged as assumptions per protocol; neither blocks
`/design`.

- **A1 — Suffix format (OQ-1) — CONFIRMED: bracket + pipe.** Each fact line gains a
  ` [doc: <id or —>]` suffix; failed facts additionally carry ` | <label>` inside the
  same bracket. The **canonical rendered form** (design uses verbatim) is:

  ```
  fact: Paris is the capital -> present [doc: doc-12]
  fact: Population is 5M -> contradicted [doc: doc-12 | generation_gap]
  fact: Founded in 200BC -> absent [doc: — | retrieval_gap]
  ```

  i.e. `fact: <text> -> <verdict> [doc: <supporting_doc_id or —>]` for present facts and
  `fact: <text> -> <verdict> [doc: <supporting_doc_id or —> | <retrieval_gap|generation_gap>]`
  for failed facts. The `fact: <text> -> <verdict>` prefix is byte-for-byte unchanged; the
  `—` em-dash is the None sentinel; the separator before the label is `|` (space-pipe-space)
  inside the `[doc: …]` bracket.

- **A2 — Symmetric doc suffix, failed-only label (OQ-2) — CONFIRMED: symmetric.** The
  `[doc: …]` suffix appears on **all** fact lines (present and failed); the root-cause
  **label** appears **only** on failed facts (gated on `verdict ∈ FAILED_VERDICTS`, since
  `classify_fact_gap` returns `None` for present). A present fact shows its supporting doc
  but no gap label (it has no gap). This delivers SC-4's literal "per fact, the doc"
  wording. The asymmetric alternative (no suffix on present facts) was rejected by the user.

- **A3 — Root-cause label is Should, not Must (OQ-3).** Assumed SC-4's literal wording
  ("the doc it was judged against") is satisfied by the doc id alone (FR-1, Must); the
  `retrieval_gap`/`generation_gap` label (FR-2) is a **Should** that surfaces the phase-2
  artifact at near-zero cost (one predicate call per fact, already a pure leaf). It has
  an explicit cut line: if the budget runs tight, FR-1+FR-3 alone close SC-4.

- **A4 — Post-phase KB scope (OQ-4).** Assumed the only post-phase KB action is an
  on-branch `/update-kb observability` updating the judge-span `output.value` format
  example/text in `span-attribute-mapping.md` (the Judge-Span section + the fenced
  format block). No structural mapping change, no other KB section affected (verified:
  no other file references the old fact-line format), no `/new-kb`, no new ADR. Matches
  the SPRINT.md note: "update-kb observability after phase 3 only if the mapping changes"
  — here the rendered string changes, so the documented example must be refreshed.

---

## Won't (explicit, this phase)

- **No structured per-fact span attributes** (`eval.fact.{i}.supporting_doc_id`,
  `eval.fact.{i}.root_cause`, etc.) — no established OpenInference key, zero filtering
  benefit at this harness's scale (BRAINSTORM Approach B rejected).
- **No per-fact annotations** — the annotation model expects one scalar per metric per
  span; emitting one annotation row per fact is unsupported by the current `log_scores`
  shape (BRAINSTORM Tension 2). `build_score_rows` is untouched.
- **No record-level rollup annotation** (`retrieval_gap_count` / `generation_gap_count`,
  BRAINSTORM Approach C / Could) — SC-4 is met by Approach A alone; the counts already
  live in the report.
- **No exporter change** — `observability/exporter.py`'s replay loop and boundary
  enrichment are untouched.
- **No span-tree change** — no new span, span kind, or change to the chain → retriever /
  generation / judge shape.
- **No schema change** — `eval/schema.py` and `eval/records.py` are unmodified.
- **No new ADR** — additive within ADR-0004's already-decided observability architecture.

---

## Clarity Score

| Dimension       | Score | Note                                                                                                                                                                                                                               |
| --------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**     | 3     | Root cause stated with code evidence: phases 1–2 produced the per-fact signal; phase 3's single change site (`attributes.py` judge block, lines ~63–82) is identified verbatim.                                                    |
| **Users**       | 3     | Named role: the eval operator reading a single failed trace in Phoenix's Info tab (SC-4 self-diagnosis), no longer cross-referencing the aggregate report. Workflow impact explicit.                                               |
| **Success**     | 3     | 15 falsifiable ACs mapped to FRs; SC-4 has a dedicated AC (1), the Should root-cause label (4–6), the `—` sentinel (7), mapper-purity/no-exporter-change (10/13), and the `per_fact=None` no-lines case (8) each have one.         |
| **Scope**       | 3     | MoSCoW inherited from BRAINSTORM (Must = doc suffix + null discipline; Should = label; Won't = structured attrs / annotations / rollup / exporter / span-tree / schema / ADR), with an explicit Won't list.                        |
| **Constraints** | 3     | All constraints named: mapper purity (no phoenix/otel; root_cause leaf import allowed), null `—` discipline, additive/no-schema/no-exporter/no-ADR, offline/no-mocked-LLM, mirrored test layout + `__init__.py`, `make lint test`. |

**Total: 15/15** — PASS (≥12). Of the four BRAINSTORM open questions, A1 (exact rendering)
and A2 (symmetric vs asymmetric) were **confirmed by the user** via `AskUserQuestion` with
rendered previews (2026-06-17) and are now locked decisions; A3 (label is Should) and A4
(post-phase KB scope) remain aligned assumptions, neither blocking `/design`.

---

## Infrastructure Readiness

| Dependency                                                             | KB domain       | Specialist      | Status                                                                                         |
| ---------------------------------------------------------------------- | --------------- | --------------- | ---------------------------------------------------------------------------------------------- |
| `observability/attributes.py` (judge-span `output.value` block)        | `observability` | (obs workflow)  | Ready — single change site verified (lines ~63–82); pure mapper, no phoenix/otel.              |
| `eval/root_cause.py` (`classify_fact_gap`, `FAILED_VERDICTS`)          | `rag-eval`      | (eval workflow) | Ready — phase-2 pure leaf; importable into `attributes.py` without breaking purity.            |
| `eval/schema.py` `FactVerdict.supporting_doc_id`                       | `rag-eval`      | (eval workflow) | Ready — phase-1 field; `str \| None`, drives the `—` sentinel branch.                          |
| `eval/records.py` `EvalRecord` (`per_fact`, `retrieval_ranked_ids`)    | `rag-eval`      | (eval workflow) | Ready — `per_fact: list[FactVerdict] \| None`; fields verified.                                |
| `tests/observability/test_attributes.py` (offline seam, `__init__.py`) | `observability` | (obs workflow)  | Ready — offline hand-built-record pattern in place; extend in situ, no cassette.               |
| `span-attribute-mapping.md` (judge-span format example)                | `observability` | (obs workflow)  | Will go stale on the fact-line format string — post-phase on-branch `/update-kb`.              |
| `make lint test` gate                                                  | —               | —               | Ready — standard gate.                                                                         |
| Post-phase `/update-kb observability`                                  | `observability` | (obs workflow)  | Pending — run AFTER phase lands, on-branch (judge-span `output.value` example). Not a blocker. |

No infrastructure gaps. KB domains `observability` and `rag-eval` are sufficient; no
`/new-kb`, `/new-agent`, or new ADR is required. The only KB drift is the judge-span
format example in `span-attribute-mapping.md`, repaired by the post-phase on-branch
`/update-kb observability` per the SPRINT.md convention.

---

## Next Step

→ `/design sprint-8/phase-3-trace-surfacing`
