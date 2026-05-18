# Dataset — EnterpriseRAG-Bench

Notes on the evaluation dataset and how Sprint 1 ingests it.

Source: [`onyx-dot-app/EnterpriseRAG-Bench`](https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench)
on the Hugging Face Hub (Onyx, MIT licensed).

## Why this dataset

EnterpriseRAG-Bench provides enterprise-style documents drawn from nine workplace
sources, plus 500 questions with gold answers, atomic `answer_facts`, and
`expected_doc_ids` for retrieval scoring. The per-fact annotations and document-id
ground truth make it suitable for the eval-first focus of this project.

## Pinned revision

Ingest pins a Hugging Face commit SHA so the corpus is reproducible:

```
69916e31c68aa5963c00248fd7f0bc12d04fd235
```

Captured 2026-05-17 from the `main` branch (dataset last modified 2026-05-08). The SHA
is the single source of truth in `src/enterprise_rag_ops/ingest/config.py`
(`DATASET_REVISION`). Re-running ingest at the same SHA yields a byte-identical corpus.

## Structure

The dataset exposes two configs, each with a single `test` split:

| Config      | Rows    | Used by  | Notes                                                                              |
| ----------- | ------- | -------- | ---------------------------------------------------------------------------------- |
| `documents` | 511,962 | Sprint 1 | The corpus. ~1.3 GB Parquet — streamed, not held in memory.                        |
| `questions` | 500     | Sprint 2 | Eval set: `gold_answer`, `answer_facts`, `expected_doc_ids`. Out of Phase 1 scope. |

### `documents` schema

Every record shares one flat schema across all nine source types:

| Raw field     | Type   | → `Document` field  |
| ------------- | ------ | ------------------- |
| `doc_id`      | string | `id`                |
| `source_type` | string | `source_type`       |
| `content`     | string | `text`              |
| `title`       | string | `metadata["title"]` |

The schema is uniform, so a single adapter (`ingest/adapters/flat.py`) normalizes all
sources. The registry is keyed by `source_type` so a future revision can swap in a
per-source adapter without changing call sites.

### Source types and corpus distribution

Nine source types are present at the pinned revision (document counts in the full
corpus):

| Source type    | Documents |
| -------------- | --------- |
| `slack`        | 285,605   |
| `gmail`        | 121,390   |
| `linear`       | 35,308    |
| `google_drive` | 25,108    |
| `hubspot`      | 15,017    |
| `fireflies`    | 10,173    |
| `github`       | 8,052     |
| `jira`         | 6,120     |
| `confluence`   | 5,189     |

A `source_type` outside this set raises `UnknownSourceTypeError` rather than being
dropped silently.

## Sampling contract

`make download-data` does not ingest the full 512K-document corpus by default. It
builds a **deterministic stratified subset**:

- For each source type, documents are sorted by `id` and the first `DOCS_PER_SOURCE`
  are kept (no RNG).
- `DOCS_PER_SOURCE` defaults to 100 — overridable: `make download-data DOCS_PER_SOURCE=10`.
- Every source has at least 5,189 documents, so any `DOCS_PER_SOURCE ≤ 5189` yields
  exactly `9 × DOCS_PER_SOURCE` documents.
- The subset is written to `data/processed/corpus.jsonl` (gitignored), one
  JSON-serialized `Document` per line, with sorted keys for byte-stable output.

`make check-data` validates that file offline (no network): file present, all nine
source types represented, no empty `text`, unique `id`s, per-source counts within
range.
