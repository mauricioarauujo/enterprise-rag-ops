# ADR 0010: Persist Judge Reasoning in Gold and Design Bronze Archive

## Status

accepted

## Date

2026-06-02

## Context

Failed evaluation traces require legibility to explain why a RAG pipeline did not meet expectations. In ADR-0007, we established a strict footprint discipline and excluded detailed verdict checklists from the evaluation records. However, this leaves a visibility gap, making it impossible to audit individual fact or citation level failures directly from the persisted records without re-running sweeps. We need a way to store detailed judge reasoning and generator prompt inputs without causing excessive disk bloat in the main repository.

## Decision

We split the persistence of diagnostic information into two storage layers based on footprint size:

### 1. Gold Schema Amendment (Scoped Amendment)

We introduce a scoped amendment to ADR-0007. Specifically, ADR-0007 Section 1 stated that we:

> "exclude the raw verdict checklists ... Only python-derived aggregate metrics are persisted"

We narrow this exclusion to admit the small discrete lists `per_fact` and `per_citation` into the gold evaluation records (`EvalRecord`), while keeping the bulky generation prompt and raw payloads excluded from gold. These lists are already computed in memory by the judge during evaluations, so populating them in `EvalRecord` adds zero additional LLM API cost.

### 2. Bronze Archive Design (Designed here, BUILT + wired + gitignored in Phase 19)

The bulky generation input prompt (which embeds the $k=10$ retrieved context chunks) and raw LLM API response payloads will be stored in a gitignored bronze archive.

- **Bronze Key Scheme:** `data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json`
- **Idempotency:** Overwrite-by-key idempotency is enforced, where running evaluations with the same keys overwrites the existing files.
- **Opt-in Flag:** An opt-in configuration flag (`persist_bronze`, default `False`) controls whether bronze records are written.
- **Thread-Safety & Flush:** Writing is designed to be thread-safe and matching the runner's per-record-flush model.
- **Gitignore Status:** The bronze path `data/raw_eval/` is not covered by the existing gitignored patterns `data/raw/` or `results/*`. An explicit `data/raw_eval/` line will be added to `.gitignore` when Phase 19 builds the bronze writer.

### 3. Footprint Numbers

- **Gold Delta:** Very small. The additional gold fields consist only of small, discrete label lists (`FactVerdict` and `CitationVerdict` structures), scaling on the order of existing `sources` or `retrieval_ranked_ids` lists.
- **Bronze Footprint:** Large. For a sweep of ~1500 records with 2 API calls each, storing full prompt structures and raw payloads consumes ~25–30 MB raw (~5–8 MB gzipped).

### 4. Privacy and Secrets

Bronze request payloads will only serialize the model ID, request messages, and sampling parameters. Authentication credentials, API keys, and bearer tokens live only in request headers or client configurations and are never serialized, ensuring no secrets leak into the bronze storage.

### 5. Cassette (ADR-0006) Overlap Resolution

We distinguish between the offline testing and production evaluation layers:

- **vcrpy Cassettes (ADR-0006):** Test-only fixtures keyed by request hash, managed by test runner lifecycles, and committed to git for offline CI testing.
- **Bronze Archive:** Distinct production-sweep artifacts written during live sweeps, keyed by `question_id`, and gitignored.
  While the underlying response-serialization shape may be shared between the two layers, their lifecycles and target locations remain completely decoupled.

### 6. B2-Gold-Only Fallback

If the Phase 19 bronze writer implementation exceeds time or complexity budgets, we fall back to a B2-gold-only option: verdicts are persisted in gold, no bronze writer is built, and the bulky generation input prompt is simply not persisted this sprint.

## Consequences

- The `EvalRecord` schema now persists `per_fact` and `per_citation` fields.
- Backward compatibility is maintained because the new fields are optional and default to `None`.
- Phase 19 can build the bronze writer matching this specification exactly.
- **Phase 19 obligations before activating the writer:** add an explicit `data/raw_eval/` line to `.gitignore` (the path is not covered by the existing `data/raw/` / `results/*` entries), and sanitize/validate `run_id` so it cannot contain path separators (the key scheme `data/raw_eval/{run_id}/...` would otherwise create unintended nested directories).
- The `rag-eval` KB (`eval-record-schema`) refresh for the new fields is deferred to after this ADR, per the sprint-wide knowledge plan — until then the ADR-0007 §1 schema table remains the historical record, narrowed by this ADR's pointer.
