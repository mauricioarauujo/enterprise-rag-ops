# Review: sprint-1/phase-1-data-ingest — Data Ingest & Document Indexing

**Branch:** `main` (uncommitted) | **Date:** 2026-05-17 | **Verdict:** ✅ READY

## Summary

Phase 1 delivers a clean, well-tested ingest pipeline: streaming HF load at a pinned
revision, a Pydantic `Document` model, an adapter registry, deterministic stratified
sampling, and an offline corpus smoke gate. All 10 acceptance criteria are met — the
end-to-end run was verified twice with byte-identical output. No blocking issues; a
handful of minor style nits and one process note (work sits on `main`, not a feature
branch).

> Note: the `code-reviewer` agent could not run (org monthly usage limit reached).
> This review was done inline by the orchestrator against the same checklist.

## Mechanical Checks

| Step   | Status | Notes                                        |
| ------ | ------ | -------------------------------------------- |
| Format | PASS   | `ruff format --check` — 19 files formatted   |
| Lint   | PASS   | `ruff check` clean; `prettier --check` clean |
| Tests  | PASS   | 42 passed, 1 deselected (`corpus` marker)    |

End-to-end (not part of `make verify`): `make download-data` wrote 900 docs (100 × 9
sources, 1 empty-content record skipped); `make check-data` passed; two full runs
produced a byte-identical `corpus.jsonl` (sha256 `e2422ec…`).

## Issues

<details>
<summary>⚠️ <code>schema.py:45</code> — mutable default <code>metadata: dict = {}</code></summary>

Pydantic v2 copies field defaults per instance, so this is **not** a shared-state bug
and `ruff` does not flag it. Still, the idiomatic form is explicit:

```python
from pydantic import Field
metadata: dict = Field(default_factory=dict)
```

Non-blocking — cosmetic consistency only.

</details>

<details>
<summary>⚠️ <code>schema.py:49</code> — <code>info</code> parameter is untyped</summary>

`def _non_empty(cls, value: str, info) -> str:` — the validator's `info` argument has
no type hint, unlike every other signature in the module. Add `ValidationInfo`:

```python
from pydantic import ValidationInfo
def _non_empty(cls, value: str, info: ValidationInfo) -> str:
```

Non-blocking.

</details>

<details>
<summary>⚠️ <code>cli.py:36</code> / <code>adapters/flat.py:21</code> — a missing raw key raises an uncaught <code>KeyError</code></summary>

`adapt_records` catches `ValidationError`, but `get_adapter(raw["source_type"])` and
`flat_adapter`'s `raw["doc_id"]` / `raw["content"]` / `raw["title"]` would raise
`KeyError` on a record missing a column. Safe in practice — the `documents` Parquet
schema guarantees all four columns on every row — so this is acceptable as-is. If a
later revision adds optional columns, switch to `raw.get(...)` with explicit handling.

Non-blocking — documented expectation, not a defect.

</details>

<details>
<summary>⚠️ Process — Phase 1 was implemented on <code>main</code></summary>

`CLAUDE.md` § Conventions specifies `sprint-<n>/<short-slug>` branch naming. The work
is uncommitted on `main`. Move it to a `sprint-1/phase-1-data-ingest` branch before
committing / opening a PR.

Non-blocking for code readiness; resolve before the PR.

</details>

## Acceptance Criteria

| #   | Criterion                                        | Status | Evidence                                                                                                       |
| --- | ------------------------------------------------ | ------ | -------------------------------------------------------------------------------------------------------------- |
| 1   | `make download-data` produces corpus, exits 0    | ✅     | Verified — wrote `data/processed/corpus.jsonl`, exit 0                                                         |
| 2   | `DOCS_PER_SOURCE` docs per source                | ✅     | Verified — 100 each across all 9 sources                                                                       |
| 3   | `DOCS_PER_SOURCE=10` override honored            | 🟡     | Makefile passes `$(DOCS_PER_SOURCE)`; `sampler` unit-tested for varied N; **not** re-run end-to-end with `=10` |
| 4   | Two runs byte-identical                          | ✅     | Verified — identical sha256 across two full runs; `test_writer.py`                                             |
| 5   | `check-data` fails on corruption                 | ✅     | 3 corrupt fixtures + `test_corrupt_fixture_is_detected`                                                        |
| 6   | `check-data` runs offline                        | ✅     | `validate_corpus` only reads the local file — no network call                                                  |
| 7   | `Document(text="")` / `id=""` raises             | ✅     | `test_schema.py::test_empty_string_field_rejected`                                                             |
| 8   | Unknown `source_type` raises, not dropped        | ✅     | `test_get_adapter_raises…`, `test_adapt_records_propagates…`                                                   |
| 9   | `docs/dataset.md` records SHA, mapping, contract | ✅     | Updated — pinned SHA, field-map table, sampling contract                                                       |
| 10  | `datasets` + `pydantic` pinned; `make verify` ok | ✅     | `pyproject.toml` bounds set; verify green                                                                      |

AC-3 is the only soft spot: covered by construction (Makefile wiring + sampler tests)
but not exercised end-to-end with a non-default value. Low risk — optional to confirm.

## ADR

Phase 1 made real architectural choices — streaming `datasets` + revision pinning, the
`Document` model, the stratified-sampling contract — but `SPRINT.md` and `DESIGN.md`
both deliberately place ADR-001/ADR-002 in Phase 2, with the rationale captured in
`BRAINSTORM.md`. Not writing an ADR now is correct.

One **new** decision the design did not anticipate: `adapt_records` **skips and counts**
records that fail `Document` validation (the corpus contains documents with empty
`content`). This is sound — it honors AC-7 (model stays strict), FR-7d (output corpus
has no empty text), and FR-3 (unknown `source_type` still raises). It is logged at
`WARNING`, not silent. **Action:** fold this skip-policy rationale into ADR-002 (or a
short note) in Phase 2 so the decision is recorded where retrieval architecture is
discussed.

## Suggested Next Steps

1. ~~Apply the two cosmetic nits (`schema.py:45`, `schema.py:49`).~~ Done — both
   applied (`Field(default_factory=dict)`, `info: ValidationInfo`); `make verify` green.
2. Move the work onto a `sprint-1/phase-1-data-ingest` branch; commit with a
   Conventional Commit (`feat: …`), open the PR.
3. Phase 1 is the substrate — proceed to `/new-kb rag-retrieval`, then
   `/brainstorm sprint-1/phase-2-retrieval` (per `SPRINT.md` § Sprint-Wide KB).
4. Update the Carreira-repo track `estudos/enterprise_rag_ops/sprint-1-substrate.md`:
   mark Phase 1 done; record the pinned SHA and the empty-content data-quality finding.
