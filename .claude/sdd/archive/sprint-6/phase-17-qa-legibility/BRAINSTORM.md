# BRAINSTORM: phase-17-qa-legibility — Question + Answer Legibility (No Re-run)

**Sprint/Phase:** sprint-6/phase-17-qa-legibility | **Date:** 2026-06-02

---

## Problem Statement

A failed Phoenix trace today shows metadata (IDs, metrics, model names, retrieved-doc
content since Phase 16) but the **question text** and the **generated answer** are
invisible in Phoenix's Info tab — a reviewer must leave Phoenix and grep the raw JSONL.
Both values are already available without a re-run (`record.answer` is in EvalRecord;
question text is joined from gold via `load_questions` keyed by `question_id`). This
phase closes that gap by mapping them to the OpenInference `input.value` / `output.value`
attributes so the Info tab renders them inline.

---

## Suggested Research & KB Work

| Topic                                                                                                      | Coverage                                                                                                                                                                                                          | Action                      |
| ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| OpenInference `input.value` / `output.value` vs `llm.*_messages` — which keys make Phoenix Info tab render | **Sufficient** — confirmed this session via Context7/arize-ai/openinference: `input.value` + `input.mime_type` on chain span; `output.value` + `output.mime_type` on generation span. No further research needed. | None                        |
| Gold-question join at the boundary (`load_questions` + `question_id` map)                                  | **Sufficient** — `rag-eval` KB (`eval-record-schema`, `questions.py`), `rag-triage` precedent confirms the pattern                                                                                                | None                        |
| Boundary-enrichment rule (`attributes.py` purity, heavy reads at CLI/exporter edge)                        | **Sufficient** — `observability/dashboard-phoenix-boundary` KB (boundary-enrichment rule section) + Phase 16 precedent live in `cli.py`/`exporter.py`                                                             | None — reuse Phase 16 shape |
| `AnswerWithSources` serialization — text-only vs. JSON for `output.value`                                  | **Sufficient** — `record.answer` is already a `str` (the text field of `AnswerWithSources`); no deserialization needed                                                                                            | None                        |
| Phase 18 raw-payload architecture                                                                          | **Sufficient** — `docs/planning/sprint-6-raw-payload-note.md`; Phase 17 is explicitly decoupled (uses gold join + `record.answer` regardless of bronze)                                                           | None                        |

Coverage is sufficient across all topics. No `--deep-research` needed.

---

## Approaches Considered

| Approach                                                                                | Description                                                                                                                                                                                                                             | Pros                                                                                                                                                                                     | Cons                                                                                                                                                                                                                          | Effort                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| A — Asymmetric: answer in pure mapper, question at boundary                             | `record.answer` → `output.value` set directly inside `build_span_attrs` (no new import, no lookup); question text requires a `{question_id: str}` lookup built at the CLI boundary and injected like `doc_lookup` in Phase 16           | Minimal diff on the mapper — one new attribute in `gen_attrs`; boundary pattern only for the part that actually needs it (gold join); mapper stays trivially testable without any lookup | Two slightly different code paths for answer vs. question (one in mapper, one at boundary), which is less consistent and may confuse future contributors — "why does answer live in the mapper but question at the boundary?" | S                                                                                                                                                                                                                   |
| B — Symmetric: both at boundary via `question_lookup`                                   | Neither answer nor question is set in `build_span_attrs`; both are injected by the exporter post-processing step using a `question_lookup: Mapping[str, str]                                                                            | None`(question text by`question_id`) and `record.answer`directly. Mirrors Phase 16's`doc_lookup` shape exactly                                                                           | Perfectly consistent with Phase 16's boundary pattern — both enrichments follow the same data flow; `build_span_attrs` is truly zero-enrichment; single mental model for contributors reading `exporter.py`                   | Slightly more ceremony for the answer (it is already on `record`, so passing it through a lookup feels synthetic); slightly larger diff (two lookups instead of one, or one lookup + one direct access in exporter) | S   |
| C — Always-on for answer, opt-in for question (separate flag `--enrich-from-questions`) | Answer is always set in `build_span_attrs` (no lookup, already in record); question is opt-in with a dedicated `--enrich-from-questions` flag (own argument group in CLI, own code path in exporter), paralleling `--enrich-from-index` | Clearest user-facing semantics: answer is free, always-on; question costs a file/HF load, opt-in. Default export still has the answer visible                                            | Two flags in the CLI for two enrichment paths adds surface area; increases test matrix (was-it-always-on? was-it-opt-in?); the flag asymmetry ("some enrichments are flags, answer is not") can also confuse                  | M                                                                                                                                                                                                                   |

---

## Recommended Approach

**Approach C — always-on for answer, opt-in (`--enrich-from-questions`) for question** — with
the simplification that "always-on" for the answer means the mapper sets it directly (no new CLI
argument, no lookup, no exporter post-processing step for the answer).

Rationale:

1. **The data boundary is real and asymmetric.** `record.answer` is already in `EvalRecord`
   — setting it in the pure mapper costs zero extra imports and zero extra CLI surface. The
   question is genuinely external data (gold HF dataset or local cache) that requires a build-once
   read at the boundary. Pretending they are symmetric (Approach B) to achieve visual consistency
   adds ceremony that the codebase does not need.

2. **The always-on answer is safe.** Unlike `--enrich-from-index` (reads a potentially large
   corpus.jsonl from disk), writing `record.answer` to a span attribute needs no I/O. Always-on
   behaviour with no runtime cost is preferable to an opt-in flag that users forget to pass.

3. **The opt-in question flag is the correct user-facing API.** `load_questions()` hits HF
   (or a local cache); it is a real external dependency — the same justification that made
   `--enrich-from-index` opt-in in Phase 16. A dedicated `--enrich-from-questions` flag (or a
   combined `--enrich-from-gold`) makes the cost explicit and keeps the default export byte-
   identical to the pre-phase-17 result for users who do not pass the flag.

4. **Purity of `attributes.py` is maintained either way.** Adding `record.answer` to `gen_attrs`
   inside `build_span_attrs` imports nothing new — `record` is already the parameter.

5. **`input.value` lives on the chain span; `output.value` lives on the generation span.** This
   matches OpenInference semantics: the chain span is the "what was asked" root; the generation
   span is the "what was produced" node. (The generation span's `input.value` — the assembled
   prompt — is not available without a re-run; that is Phase 18/19 territory.)

Implementation shape (no commitment yet — for `/define` to ratify):

- `build_span_attrs`: add `output.value = record.answer` + `output.mime_type = "text/plain"` to
  `gen_attrs`. No mapper change needed for question.
- `exporter.py`: accept `question_lookup: Mapping[str, str] | None = None`; when non-None,
  post-process `span_attrs["chain"]` to add `input.value = question_lookup[record.question_id]`
  - `input.mime_type = "text/plain"` (warn-and-skip if missing, mirroring Phase 16 behaviour).
- `cli.py`: add `--enrich-from-questions` flag + optional `--questions-revision` (defaulting to
  the existing `DATASET_REVISION` constant); when flag is set, build the `{question_id: str}` map
  from `load_questions()` at the boundary before calling `replay_jsonl`.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                                                                                                                    |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | `record.answer` → `output.value` + `output.mime_type = "text/plain"` on generation span (always-on, set in mapper)                                                                                                                                      |
| **Must**   | `--enrich-from-questions` CLI flag: build `{question_id: question_text}` map from `load_questions()` at boundary; inject as `input.value` + `input.mime_type = "text/plain"` on chain span                                                              |
| **Must**   | Warn-and-skip (not crash) when a `question_id` is missing from the lookup, mirroring Phase 16's missing-doc handling                                                                                                                                    |
| **Must**   | `attributes.py` stays import-light (no new imports beyond what is already there) — NFR-1                                                                                                                                                                |
| **Must**   | Default `rag-export-traces` (no new flags) remains byte-identical to pre-phase-17 output (except the always-on answer enrichment on generation span)                                                                                                    |
| **Should** | `--questions-revision` optional argument (default `DATASET_REVISION`) so callers can pin the same HF SHA that produced the results                                                                                                                      |
| **Should** | Unit test for the answer attribute in `build_span_attrs` (no lookup required — pure function, trivial to test)                                                                                                                                          |
| **Should** | Integration test for `--enrich-from-questions` using a small stubbed `question_lookup` (mirrors Phase 16's `doc_lookup` test)                                                                                                                           |
| **Could**  | `--enrich-from-questions` also works in `--dry-run` mode (validates the lookup build without hitting Phoenix) — useful for CI                                                                                                                           |
| **Could**  | A single `--enrich-from-gold` umbrella flag that activates both `--enrich-from-index` and `--enrich-from-questions` for convenience, keeping the individual flags for fine-grained control                                                              |
| **Won't**  | Generation span `input.value` (the assembled prompt) — not persisted in EvalRecord; requires re-run (Phase 18/19)                                                                                                                                       |
| **Won't**  | Judge span `output.value` (verdict reasoning) — not persisted in EvalRecord; requires re-run (Phase 18/19)                                                                                                                                              |
| **Won't**  | `llm.input_messages` / `llm.output_messages` richer format — `input.value` + `output.value` is the minimal convention that makes the Info tab render; the messages format adds no visible benefit for a plain question string and a plain answer string |
| **Won't**  | Any `EvalRecord` schema change — this phase consumes only already-published artifacts                                                                                                                                                                   |
| **Won't**  | Any eval re-run                                                                                                                                                                                                                                         |
| **Won't**  | Raw-payload / bronze-layer capture — Phase 18 decision; Phase 17 is decoupled from it                                                                                                                                                                   |
| **Won't**  | Answer serialization as JSON (AnswerWithSources full object) — `record.answer` is already a `str`; the citations are already on `sources`; the plain string is more readable in Phoenix                                                                 |

---

## Open Questions

1. **Flag naming: `--enrich-from-questions` vs `--enrich-from-gold`?** The `--enrich-from-gold`
   umbrella would activate both question and (optionally) index enrichments in one flag, reducing
   cognitive load. But it changes the existing `--enrich-from-index` UX and makes the two
   enrichments inseparable. Which matters more — simplicity (`--enrich-from-gold`) or
   independent control (`--enrich-from-questions` alongside `--enrich-from-index`)?

2. **Should `--enrich-from-questions` be silently skipped in `--dry-run` mode (like
   `--enrich-from-index` is today), or should dry-run build the lookup and validate it without
   hitting Phoenix?** Dry-run validation of the gold join would catch HF availability issues
   early in CI, but it also means `--dry-run` incurs an HF dataset load, which is a non-obvious
   cost for what users expect to be "just parse the JSONL."

3. **Where is `mime_type` set — in the mapper or the exporter?** `output.mime_type` for the answer
   belongs naturally beside `output.value` in `build_span_attrs`. But `input.mime_type` for the
   question is injected at the exporter boundary (where `input.value` is also set). Does
   `attributes.py` pre-set placeholder `mime_type` keys (anticipating enrichment) or does the
   exporter set both `input.value` and `input.mime_type` together? Pre-setting them in the mapper
   would mean the mapper knows about a key it does not fill — the exporter-sets-both approach is
   cleaner.

4. **The `--enrich-from-questions` code path in `exporter.py`: does it mutate `span_attrs` in-
   place (consistent with Phase 16's `doc_lookup` post-processing) or does it pass
   `question_lookup` into a new `build_span_attrs` overload?** The Phase 16 precedent is
   mutation of `span_attrs["retriever"]` in `exporter.py` after `build_span_attrs` returns.
   Keeping the same pattern is the obvious choice for consistency, but `/define` should ratify it
   to avoid two different enrichment shapes co-existing in `exporter.py`.

---

## Next Step

-> `/define sprint-6/phase-17-qa-legibility`
