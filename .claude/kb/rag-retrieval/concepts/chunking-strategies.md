# Chunking Strategies

> **Purpose**: Mapping the 9-source enterprise corpus to chunk shapes for Phase 2.
> **Confidence**: HIGH — research (pillar 3) is the primary source; numeric defaults
> recovered from PDF rendering (child 256 tokens / overlap 32 tokens / parent 1024
> tokens). Qualitative guidance is HIGH confidence.
> **MCP Validated**: 2026-05-17

## Overview

Chunking is Phase 2's first step: `Document` objects from `corpus.jsonl` are split
into `Chunk` objects that are embedded and indexed. Chunk identity must carry
`Document.id` so the eval harness can deduplicate hits back to `expected_doc_ids`.
Phase 1 deliberately deferred all chunking; the choice is an ADR-002 input.

## Strategy Comparison

| Strategy        | Precision   | Context completeness | Effort     | Best for                               |
| --------------- | ----------- | -------------------- | ---------- | -------------------------------------- |
| Fixed-size      | Low         | Low                  | Negligible | Uniform, short documents               |
| Structure-aware | High        | Medium-High          | Medium     | Headings/sections (Confluence, GDrive) |
| Semantic        | Medium-High | Medium               | High       | Poor fit for code/chat                 |
| Parent-child    | Very High   | Excellent            | Medium     | Heterogeneous enterprise sources       |

**Recommended default**: parent-child. The 9-source corpus (Slack chat, Jira tickets,
Confluence docs, Gmail threads, code) is maximally heterogeneous — parent-child
preserves generator context without sacrificing vector match precision.

## Source-Specific Guidance

| Source type                   | Document count   | Chunking note                                              |
| ----------------------------- | ---------------- | ---------------------------------------------------------- |
| `slack`                       | 285,605          | Temporal windowing by thread/gap; keep participant IDs     |
| `gmail` / `hubspot`           | 121,390 / 15,017 | Group by thread; strip signatures; prepend sender+date     |
| `jira` / `linear`             | 6,120 / 35,308   | Preserve field-value pairs; group description + comments   |
| `confluence` / `google_drive` | 5,189 / 25,108   | H1-H3 heading hierarchy; orphan-free sections              |
| `github`                      | 8,052            | AST or bracket-matching splitters; preserve function/class |
| `fireflies`                   | 10,173           | Transcript windowing by speaker turn                       |

## Parent-Child Pattern

- **Parent block**: semantically complete unit (section, thread, ticket). Default:
  **1024 tokens** or logical section boundary (research cites 800–1200 token range
  for complete sections, email threads, and full Jira tickets).
- **Child chunk**: dense-search unit. Only children are embedded and stored in the
  vector index. Default: **256 tokens** (fallback 512 tokens — use only for
  extremely long, narrative-heavy documents). Align to sentence/structural boundaries.
- **Overlap**: **32 tokens (12.5% of 256-token child)**; fallback 50 tokens (10% of
  512-token child). Always align to sentence or structural boundaries.
- **Mapping**: child carries `parent_id` (= `Document.id`) as a foreign key; eval
  deduplicates on this key against `expected_doc_ids`.

## Structure Protection Rules (confidence: HIGH)

- **Lists**: treat as atomic; if split, repeat the heading and list header.
- **Tables**: repeat column headers in every chunk; split on row groups.
- **Headings**: prepend breadcrumb path (Title > H1 > H2) to each child chunk text.

## Codebase Grounding

- `src/enterprise_rag_ops/ingest/schema.py` — `Document(id, source_type, text, metadata)` is the chunk input contract.
- `data/processed/corpus.jsonl` — the Phase 2 index source; 9 × `DOCS_PER_SOURCE` documents.
- `docs/dataset.md` — source type counts and field mapping (title in `metadata`).

## Related

- [lexical-vs-semantic.md](lexical-vs-semantic.md)
- [patterns/hybrid-retrieve-fuse.md](../patterns/hybrid-retrieve-fuse.md)
