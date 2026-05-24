# Per-`doc_id` Faithfulness Isolation

> **Purpose**: Why rendering each cited doc as its own named block is the minimal
> unit that catches spurious citations, and why a merged context blob cannot.
> **Confidence**: HIGH (codebase + MCP)
> **MCP Validated**: 2026-05-24

## Overview

Citation faithfulness asks: "does this document actually support the claim the answer
made when it cited it?" The answer is only resolvable at the per-`doc_id` level — you
need to inspect one doc's text against one specific claim. A merged context blob
erases doc identity, making it impossible for a judge to say "doc X is the culprit."

This is what distinguishes the custom thin judge from RAGAs / DeepEval: both score
a merged `context` string, so a citation to a completely unrelated doc is invisible
as long as _some_ retrieved doc supports the claim. The per-`doc_id` block is the
direct discriminator for the anchor case.

## The Mechanism

`eval/prompt.py` renders cited docs as separately named blocks:

```python
# eval/prompt.py — build_judge_user_prompt
for doc_id, text in cited_docs:
    if text is None:
        doc_blocks.append(f"=== doc {doc_id} (text unavailable) ===")
    else:
        doc_blocks.append(f"=== doc {doc_id} ===\n{text}")
cited_block = "\n\n".join(doc_blocks)
```

`eval/openai_judge.py` builds the `cited_docs` list by resolving each
`answer_with_sources.sources` entry against the retrieved chunks:

```python
# eval/openai_judge.py — judge()
doc_chunks: dict[str, list[str]] = defaultdict(list)
for c in retrieved_docs:
    doc_chunks[c.doc_id].append(c.text)
doc_text = {doc_id: "\n\n".join(texts) for doc_id, texts in doc_chunks.items()}
cited_docs = [(doc_id, doc_text.get(doc_id)) for doc_id in answer_with_sources.sources]
```

A doc split across multiple chunks is joined before rendering — the judge sees the
whole doc, not just the last-seen chunk for that `doc_id`.

## The Anchor Case

The motivating failure: an answer states "the capital of France is Paris" and cites
`gd_unrelated`, a Google Drive doc about a Q3 offsite. The prompt renders:

```
=== doc doc_real ===
Paris is the capital and most populous city of France.

=== doc gd_unrelated ===
Q3 marketing offsite agenda: budget review and team lunch logistics.
```

The judge has exactly the information to return `CitationVerdict(doc_id="gd_unrelated",
verdict="unsupported")`, dragging `faithfulness_ratio` below 1.0. A merged blob
would concatenate both docs; the "Paris" fact would be found and the spurious citation
would never be surfaced.

## The `(text unavailable)` fallback

A cited `doc_id` not in the retrieved set (the answer cited something the retriever
never returned) is rendered explicitly rather than silently dropped:

```
=== doc missing_doc (text unavailable) ===
```

The rubric explicitly maps "unavailable" to `unsupported`, so the citation is still
scored rather than silently disappearing. This prevents a false faithfulness boost
from unresolvable citations.

## Contrast with Merged-Blob Approaches

| Approach                               | Faithfulness unit                | Catches spurious `doc_id`?  |
| -------------------------------------- | -------------------------------- | --------------------------- |
| RAGAs / DeepEval                       | Merged `context` string          | No — doc identity erased    |
| Per-sentence NLI                       | Each sentence vs. merged context | No — still no `doc_id` link |
| **Per-`doc_id` block** (this codebase) | One named block per cited doc    | Yes — direct discriminator  |

Per-sentence NLI would be more granular but requires additional machinery (an NLI
model) and still does not map to `doc_id`-level accountability.

## Related

- [../patterns/per-fact-judge-call.md](../patterns/per-fact-judge-call.md)
- [../concepts/judge-determinism.md](judge-determinism.md)
- `eval/prompt.py`, `eval/openai_judge.py`
- `tests/eval/test_judge_anchor.py`
