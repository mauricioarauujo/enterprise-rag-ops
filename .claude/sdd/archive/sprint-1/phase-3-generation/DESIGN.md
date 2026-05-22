# DESIGN: sprint-1/phase-3-generation — Generation Layer with Source Attribution

**Sprint/Phase:** sprint-1/phase-3-generation | **Date:** 2026-05-20

> **Implementation revision (2026-05-21).** The live `make smoke` run exposed
> that the design's context-assembly policy (fetch all chunks by `doc_id`, keep
> the top-1 by lexicographically smallest `chunk_id`) fed the LLM the document's
> _title_ chunk, not the relevant passage — so the model abstained on answerable
> questions. The as-built design instead surfaces the **winning chunk per doc**
> from the retriever: `HybridRetriever.retrieve_chunks` returns
> `(chunk_id, doc_id, score)`, and the `VectorStore` extension is
> `fetch_chunks_by_chunk_ids` (not `_by_doc_ids`). The skeletons below show the
> original design; **ADR-0003 and REVIEW.md record the as-built chunk-level
> flow.** Everything else (Generator seam, structured-output attribution,
> abstention short-circuit, StubGenerator CI) is unchanged.

## Architecture

Phase 3 closes the Sprint 1 substrate by adding a `generation` package alongside
`retrieval`, consuming the Phase 2 `HybridRetriever`'s `(doc_id, fused_score)` output
and producing an `AnswerWithSources` JSON payload. The design is the four components
called out in BRAINSTORM's Recommended Approach: (1) a **`ContextAssembler`** that
translates `(doc_id, score)` pairs into a deduplicated, rank-preserving `list[Chunk]`,
(2) a **`Generator` Protocol** with one production implementation (`OpenAIGenerator`,
default model `gpt-5-nano-2025-08-07`, OpenAI structured outputs) and one CI stub
(`StubGenerator`), (3) a deterministic **prompt builder** (system role + JSON schema;
user numbered context block + question), and (4) a **`rag-ask` CLI** wiring
`HybridRetriever → ContextAssembler → OpenAIGenerator → stdout JSON`. A `make smoke`
target executes the CLI on 10 inline `SMOKE_QUESTIONS` against a real OpenAI call and
asserts a valid non-empty `answer` on every question plus `len(sources) >= 1` on the
3 answerable ones (two-tier, revised during `/implement` — see DEFINE RQ-5); the
offline `make verify` gate uses `StubGenerator` through the same Protocol seam. The only retrieval-side
change is exactly one new method on `VectorStore` (`fetch_chunks_by_doc_ids`) with its
`LanceDBStore` implementation; `Retriever` and the existing two `VectorStore` methods
are unchanged. ADR-003 records the generation seam, attribution format, abstention
behavior, and the same-family judge/generator carry-forward flag.

### Two execution paths

**Offline pipeline-contract path (`make verify`)**:

```
fixture retriever ──► [(d1, s1), (d2, s2)]
                              │
                              ▼
                     ContextAssembler.assemble()
                              │
                              ├─► VectorStore.fetch_chunks_by_doc_ids([d1, d2])  (fixture store)
                              │
                              ▼
                   dedup top-1/doc_id, preserve order, truncate max_chunks
                              │
                              ▼
                       list[Chunk]  ──►  StubGenerator.generate(context, question)
                                                       │
                                                       ▼
                                  AnswerWithSources(answer="stub", sources=[d1, d2])
```

No network, no API key, no model download — exercises the full wiring through the
`Generator` seam (NFR-1, NFR-2).

**Real-call path (`make smoke` / `rag-ask` CLI)**:

```
question ──► HybridRetriever.retrieve(question)
                       │
            ┌──────────┴──────────┐
       [] (abstain)         [(d1, s1), ...]
            │                    │
            │                    ▼
            │           ContextAssembler.assemble()
            │                    │ (fetches via LanceDBStore.fetch_chunks_by_doc_ids)
            │                    ▼
            │             prompt_builder.build(context_chunks, question)
            │                    │   (system + user strings)
            │                    ▼
            │           OpenAIGenerator.generate(context_chunks, question)
            │                    │   (chat.completions.create + response_format json_schema strict)
            ▼                    ▼
   AnswerWithSources(            AnswerWithSources(answer=..., sources=[doc_ids])
     answer="I don't have                          │
     enough information...",                       ▼
     sources=[])                          rag-ask prints JSON to stdout
            │                                      │
            └────────────────────┬─────────────────┘
                                 ▼
                       INFO log: post-assembler doc_ids + final sources (NFR-5)
```

The abstention short-circuit (FR-8) is a Python branch in the CLI **before** any
context assembly or `Generator` call — it must not issue an OpenAI request.

### The fourth seam (NFR-2 — the central architectural addition)

ADR-002 named three seams (`Embedder`, `VectorStore`, `Retriever`). Phase 3 adds a
fourth that follows the same engineering posture — name the boundary, ship one
implementation behind it, do **not** pre-build alternatives:

- **`Generator`** — `generate(context_chunks: list[Chunk], question: str) -> AnswerWithSources`.
  Phase 3 ships `OpenAIGenerator` (production, `gpt-5-nano-2025-08-07`) and
  `StubGenerator` (CI). The Protocol is the named seam ADR-005 (LLM matrix) will swap
  behind: a `ClaudeGenerator` or `OllamaGenerator` is a new file plus a one-line
  wiring change in `rag-ask`, not a rewrite.

In addition, the `VectorStore` Protocol widens by **exactly one** method:
`fetch_chunks_by_doc_ids(doc_ids: list[str]) -> list[Chunk]`. This is justified by use
(the assembler needs chunk text it cannot get from `(doc_id, score)`), not "in case".
The existing `add` and `dense_search` are untouched (FR-4).

The `ContextAssembler` is **not** behind a Protocol. It is a single concrete class
whose only collaborator is `VectorStore` (already a seam); a Protocol there would be
seam "in case" and the engineering guidance rejects it. Sprint 2 sweeps will configure
it via the `max_chunks` constructor parameter (FR-6, RQ-14).

## File Manifest

| File                                                    | Change  | Owner  | Phase order |
| ------------------------------------------------------- | ------- | ------ | ----------- |
| `src/enterprise_rag_ops/generation/__init__.py`         | created | direct | 3           |
| `src/enterprise_rag_ops/generation/schema.py`           | created | direct | 1           |
| `src/enterprise_rag_ops/generation/interfaces.py`       | created | direct | 1           |
| `src/enterprise_rag_ops/generation/context.py`          | created | direct | 3           |
| `src/enterprise_rag_ops/generation/prompt.py`           | created | direct | 4           |
| `src/enterprise_rag_ops/generation/openai_generator.py` | created | direct | 6           |
| `src/enterprise_rag_ops/generation/stub_generator.py`   | created | direct | 5           |
| `src/enterprise_rag_ops/generation/cli.py`              | created | direct | 6           |
| `src/enterprise_rag_ops/retrieval/interfaces.py`        | changed | direct | 1           |
| `src/enterprise_rag_ops/retrieval/vector_store.py`      | changed | direct | 2           |
| `tests/generation/__init__.py`                          | created | direct | 5           |
| `tests/generation/conftest.py`                          | created | direct | 5           |
| `tests/generation/test_schema.py`                       | created | direct | 5           |
| `tests/generation/test_context_assembler.py`            | created | direct | 5           |
| `tests/generation/test_prompt.py`                       | created | direct | 5           |
| `tests/generation/test_stub_generator.py`               | created | direct | 5           |
| `tests/generation/test_generation_contract.py`          | created | direct | 5           |
| `tests/generation/test_cli.py`                          | created | direct | 6           |
| `tests/generation/test_generation_smoke.py`             | created | direct | 6           |
| `tests/retrieval/test_vector_store.py`                  | changed | direct | 2           |
| `pyproject.toml`                                        | changed | direct | 2           |
| `Makefile`                                              | changed | direct | 6           |
| `docs/adr/0003-generation.md`                           | created | direct | 7           |
| `docs/adr/README.md`                                    | changed | direct | 7           |

Owner is `direct` for every file: no generation specialist agent exists, and DEFINE's
Infrastructure Readiness explicitly confirms one is not required for Phase 3 (a
conventional single-turn prompt + structured output is small and well-bounded; no
repeated specialist context-loading is anticipated). The two retrieval-side touches
(`interfaces.py` and `vector_store.py`) are surgical extensions of the Phase 2 contract,
not redesigns — they live under `retrieval/` for locality of the `VectorStore` seam.

### Module responsibilities

- **`generation/schema.py`** — `AnswerWithSources` Pydantic model with exactly two
  fields (`answer: str`, `sources: list[str]`); FR-1. Also exposes the JSON schema
  dict consumed by both the OpenAI `response_format` payload and the system prompt's
  schema fragment (single source of truth: `AnswerWithSources.model_json_schema()`).
- **`generation/interfaces.py`** — the `Generator` Protocol (FR-2); no logic. Mirrors
  `retrieval/interfaces.py` in shape and docstring tone.
- **`generation/context.py`** — `ContextAssembler` (FR-6, RQ-9, RQ-14): fetches all
  chunks for the retrieved `doc_id` set via `VectorStore.fetch_chunks_by_doc_ids`,
  deduplicates to top-1 chunk per `doc_id` (lexicographically smallest `chunk_id`),
  preserves doc-level fused-rank order from the retriever, truncates to
  `max_chunks` (default 5).
- **`generation/prompt.py`** — pure functions `build_system_prompt()` and
  `build_user_prompt(context_chunks, question)` (FR-7, NFR-4). Deterministic: same
  inputs → byte-identical outputs (AC-7).
- **`generation/openai_generator.py`** — `OpenAIGenerator` (FR-3) — calls
  `client.chat.completions.create(...)` with `response_format={"type": "json_schema",
"json_schema": {...}, "strict": true}` and `temperature=0`; re-validates the
  returned JSON through `AnswerWithSources.model_validate_json` defensively; reads
  `RAG_GEN_MODEL` env var with `gpt-5-nano-2025-08-07` default; raises a clean
  `RuntimeError` (not an SDK stack trace) when `OPENAI_API_KEY` is unset (NFR-7).
- **`generation/stub_generator.py`** — `StubGenerator` (FR-10) — deterministic
  `AnswerWithSources(answer="stub", sources=[c.doc_id for c in context_chunks])`.
  The CI-safe drop-in through the `Generator` seam; no API key, no network.
- **`generation/cli.py`** — `rag-ask` console-script (FR-9). Argparse → `load_retriever`
  → `HybridRetriever.retrieve` → empty-result short-circuit (FR-8) → `ContextAssembler`
  → `OpenAIGenerator` → `print(answer.model_dump_json())` → exit 0. Logging at INFO
  for post-assembler `doc_id`s and final `sources` (NFR-5, AC-18).
- **`retrieval/interfaces.py`** (changed) — one-method extension of `VectorStore`
  (FR-4); existing two methods untouched.
- **`retrieval/vector_store.py`** (changed) — `LanceDBStore.fetch_chunks_by_doc_ids`
  implementation (FR-5) — a LanceDB read with `where(..., prefilter=True)` on a
  SQL-style `doc_id IN ('...')` filter, returning all matching chunks.

## Interfaces & Contracts

The skeletons below are real signatures with real bodies for the load-bearing parts —
not `pass # TODO` stubs. They specify the exact contract `/implement` will satisfy.

### `AnswerWithSources` (`generation/schema.py`)

```python
"""Canonical generation output — the single schema shared by the Generator
Protocol return type, the OpenAI structured-output JSON schema, and the
`rag-ask` CLI stdout payload (FR-1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnswerWithSources(BaseModel):
    """An LLM-produced answer with cited document identifiers.

    Fields:
        answer: The natural-language answer string. Empty string is allowed by
            the schema but flagged by the smoke gate (FR-13).
        sources: List of `doc_id` strings cited as evidence. Order is the
            order the model emitted them; deduplication is the LLM's
            responsibility (not enforced at the schema layer).

    Invariants enforced by Pydantic:
        - Both fields are required; `ValidationError` on missing/wrong type
          (AC-1).

    The schema is closed (`additionalProperties: false` in the JSON Schema
    consumed by OpenAI `strict: true` mode) — the model cannot emit extra
    fields.
    """

    model_config = {"extra": "forbid"}

    answer: str = Field(description="Natural-language answer to the user question.")
    sources: list[str] = Field(
        description="doc_id values cited as evidence for the answer."
    )
```

### `Generator` Protocol (`generation/interfaces.py`)

```python
"""The Phase 3 generation seam (FR-2, NFR-2).

Mirrors the shape of `retrieval/interfaces.py`'s three Protocols. The named
future swap is ADR-005's LLM matrix — a `ClaudeGenerator` or `OllamaGenerator`
is a new file implementing this Protocol plus a one-line wiring change in
`generation/cli.py`."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


@runtime_checkable
class Generator(Protocol):
    """Produces an `AnswerWithSources` from assembled context + question."""

    def generate(
        self,
        context_chunks: list[Chunk],
        question: str,
    ) -> AnswerWithSources:
        """Return an `AnswerWithSources` for the question grounded in context.

        Callers handle abstention upstream (the empty-retrieval short-circuit in
        `rag-ask`); implementations may assume `context_chunks` is non-empty.
        """
        ...
```

### `OpenAIGenerator` (`generation/openai_generator.py`) — key methods

```python
"""OpenAI-backed `Generator` using structured outputs (FR-3, RQ-11)."""

from __future__ import annotations

import logging
import os

from openai import OpenAI

from enterprise_rag_ops.generation.interfaces import Generator
from enterprise_rag_ops.generation.prompt import build_system_prompt, build_user_prompt
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

logger = logging.getLogger("enterprise_rag_ops.generation")

DEFAULT_MODEL = "gpt-5-nano-2025-08-07"


class OpenAIGenerator:
    """`Generator` implementation calling OpenAI chat completions with
    `response_format={"type": "json_schema", ..., "strict": true}` (FR-3).

    Default model is `gpt-5-nano-2025-08-07`; override via env var
    `RAG_GEN_MODEL`. Temperature is fixed at 0 (NFR-4). The env-var-only
    override avoids any new config knob — the CLI does not expose a model flag
    in Phase 3.
    """

    def __init__(self, model: str | None = None, client: OpenAI | None = None) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                # NFR-7: clean error, not an SDK stack trace.
                raise RuntimeError(
                    "OPENAI_API_KEY is not set — required for OpenAIGenerator. "
                    "Set it in your shell or .env before running `make smoke` "
                    "or the `rag-ask` CLI."
                )
            client = OpenAI()
        self._client = client
        self._model = model or os.environ.get("RAG_GEN_MODEL", DEFAULT_MODEL)

    def generate(
        self, context_chunks: list[Chunk], question: str
    ) -> AnswerWithSources:
        """Call OpenAI structured outputs and return an `AnswerWithSources`."""
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(context_chunks, question)

        # The JSON schema is owned by AnswerWithSources — single source of truth.
        json_schema = {
            "name": "AnswerWithSources",
            "schema": AnswerWithSources.model_json_schema(),
            "strict": True,
        }

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        # Defensive re-validation: OpenAI's strict mode validates server-side,
        # but Pydantic gives us a typed object and a second line of defense
        # against schema drift (Risk #1).
        result = AnswerWithSources.model_validate_json(raw)
        logger.info(
            "generation.openai sources=%s context_doc_ids=%s",
            result.sources,
            [c.doc_id for c in context_chunks],
        )
        return result
```

### `StubGenerator` (`generation/stub_generator.py`)

```python
"""CI-safe `Generator` (FR-10) — no API key, no network. Used by
`tests/generation/test_generation_contract.py` to exercise the full pipeline
wiring through the `Generator` seam (NFR-2, AC-10)."""

from __future__ import annotations

from enterprise_rag_ops.generation.interfaces import Generator
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk


class StubGenerator:
    """Returns deterministic `AnswerWithSources(answer="stub", sources=[doc_ids])`."""

    def generate(
        self, context_chunks: list[Chunk], question: str
    ) -> AnswerWithSources:
        return AnswerWithSources(
            answer="stub",
            sources=[chunk.doc_id for chunk in context_chunks],
        )
```

### `ContextAssembler` (`generation/context.py`)

```python
"""Translate `(doc_id, fused_score)` pairs into a `list[Chunk]` for the prompt.

Policy lives here, not in `VectorStore` (RQ-9). The store does the mechanical
SQL-style read; the assembler enforces:
  - top-1 chunk per doc_id (lexicographically smallest chunk_id wins),
  - preservation of the doc-level fused-rank order from the retriever,
  - truncation to `max_chunks` (default 5)."""

from __future__ import annotations

from enterprise_rag_ops.retrieval.interfaces import VectorStore
from enterprise_rag_ops.retrieval.schema import Chunk

DEFAULT_MAX_CHUNKS = 5


class ContextAssembler:
    """Fetch + dedup + order + truncate (FR-6)."""

    def __init__(self, store: VectorStore, max_chunks: int = DEFAULT_MAX_CHUNKS) -> None:
        if max_chunks <= 0:
            raise ValueError(f"max_chunks must be positive, got {max_chunks}")
        self._store = store
        self._max_chunks = max_chunks

    def assemble(self, retrieved: list[tuple[str, float]]) -> list[Chunk]:
        """Return up to `max_chunks` chunks, one per distinct doc_id, in fused-rank order.

        - `retrieved` is the `HybridRetriever.retrieve` output (already
          doc-deduplicated upstream; the input order is the fused-rank order).
        - Returns `[]` when `retrieved == []` — abstention is the CLI's
          responsibility, but the assembler is defensive.
        """
        if not retrieved:
            return []

        ordered_doc_ids = [doc_id for doc_id, _score in retrieved]
        # One SQL-style read for all requested doc_ids (RQ-9).
        all_chunks = self._store.fetch_chunks_by_doc_ids(ordered_doc_ids)

        # Group by doc_id, then pick the lexicographically smallest chunk_id
        # (deterministic top-1 policy).
        by_doc: dict[str, list[Chunk]] = {}
        for chunk in all_chunks:
            by_doc.setdefault(chunk.doc_id, []).append(chunk)

        selected: list[Chunk] = []
        for doc_id in ordered_doc_ids:
            chunks = by_doc.get(doc_id)
            if not chunks:
                # Defensive: a doc_id with no chunks in the store is silently
                # skipped (would only happen on a stale index — Risk #4).
                continue
            selected.append(min(chunks, key=lambda c: c.chunk_id))

        return selected[: self._max_chunks]
```

### `VectorStore.fetch_chunks_by_doc_ids` — Protocol addition (`retrieval/interfaces.py`)

```python
# Added to the existing `VectorStore` Protocol (FR-4). The other two methods
# (`add`, `dense_search`) are unchanged.

def fetch_chunks_by_doc_ids(self, doc_ids: list[str]) -> list[Chunk]:
    """Return every chunk whose `doc_id` is in the requested set.

    No filtering, no deduplication, no ordering guarantee at the store layer
    (RQ-9). Policy is owned by `generation.context.ContextAssembler`.
    """
    ...
```

### `LanceDBStore.fetch_chunks_by_doc_ids` (`retrieval/vector_store.py`)

```python
def fetch_chunks_by_doc_ids(self, doc_ids: list[str]) -> list[Chunk]:
    """LanceDB read filtered by `doc_id IN (...)` (FR-5).

    Uses `where(..., prefilter=True)` SQL-style — same idiom as
    `dense_search`'s `source_type` pre-filter. We deliberately scan rather
    than search (no vector ranking); LanceDB's `.search()` requires a query
    vector, so we go through the table directly.
    """
    if self._table is None:
        raise RuntimeError(
            f"LanceDB table {self._table_name!r} not initialized — call add() first"
        )
    if not doc_ids:
        return []
    # SQL-escape single quotes — same defensive pattern as dense_search.
    quoted = ", ".join(f"'{d.replace('\\'', '\\'\\'')}'" for d in doc_ids)
    where_clause = f"doc_id IN ({quoted})"
    # `to_arrow` over the table with a where clause is the documented LanceDB
    # idiom for non-vector reads; equivalent: `.search().where(..., prefilter=True)`
    # with no query vector — we use the explicit table scan for clarity.
    records = self._table.search().where(where_clause, prefilter=True).limit(
        len(doc_ids) * 64  # generous cap: corpus has 3-5 chunks per doc
    ).to_list()
    return [
        Chunk(chunk_id=r["chunk_id"], doc_id=r["doc_id"], text=r["text"])
        for r in records
    ]
```

### Prompt builder (`generation/prompt.py`)

```python
"""Deterministic prompt construction (FR-7, NFR-4).

Two pure functions — no LLM client, no state, no env reads. AC-7 asserts
byte-identical output for identical inputs across two invocations."""

from __future__ import annotations

import json

from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval.schema import Chunk

_ROLE = (
    "You are an enterprise knowledge assistant. Answer the user's question "
    "using only the numbered context provided. Cite the doc_id of every "
    "context entry you used in the `sources` field. If the context is "
    "insufficient, say so plainly in `answer` and return an empty `sources` list."
)


def build_system_prompt() -> str:
    """System prompt = role + JSON output instruction + schema (FR-7, Decision 4)."""
    schema_json = json.dumps(AnswerWithSources.model_json_schema(), indent=2, sort_keys=True)
    return (
        f"{_ROLE}\n\n"
        f"Respond with a single JSON object matching this schema:\n"
        f"{schema_json}"
    )


def build_user_prompt(context_chunks: list[Chunk], question: str) -> str:
    """User turn = numbered context block + question (FR-7).

    Format: `[1] {doc_id}: {text}\\n[2] {doc_id}: {text}\\n...\\n\\n{question}`.
    Numbering is 1-based and matches the order of `context_chunks` (already in
    fused-rank order from the assembler).
    """
    lines = [
        f"[{i}] {chunk.doc_id}: {chunk.text}"
        for i, chunk in enumerate(context_chunks, start=1)
    ]
    context_block = "\n".join(lines)
    return f"{context_block}\n\n{question}"
```

### `rag-ask` CLI (`generation/cli.py`)

```python
"""`rag-ask` — end-to-end question → AnswerWithSources JSON (FR-9).

The empty-retrieval short-circuit (FR-8) lives here, before any context
assembly or `Generator` call — no LLM request is issued in the abstention
branch (AC-8)."""

from __future__ import annotations

import argparse
import logging
import sys

from enterprise_rag_ops.generation.context import ContextAssembler
from enterprise_rag_ops.generation.openai_generator import OpenAIGenerator
from enterprise_rag_ops.generation.schema import AnswerWithSources
from enterprise_rag_ops.retrieval import pipeline
from enterprise_rag_ops.retrieval.vector_store import LanceDBStore
from enterprise_rag_ops.retrieval import config

logger = logging.getLogger("enterprise_rag_ops.generation.cli")

ABSTAIN_ANSWER = "I don't have enough information to answer this question."


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints AnswerWithSources JSON."""
    parser = argparse.ArgumentParser(
        prog="rag-ask",
        description="Answer a question using the built RAG index + OpenAI generation.",
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="The question to answer. Reads from stdin if omitted.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    question = args.question if args.question is not None else sys.stdin.read().strip()
    if not question:
        parser.error("question must be provided via argv or stdin")

    retriever = pipeline.load_retriever()
    retrieved = retriever.retrieve(question)

    if not retrieved:
        # FR-8 abstention short-circuit — no Generator call.
        result = AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[])
        logger.info("generation.cli abstain doc_ids=[] sources=[]")
        print(result.model_dump_json())
        return 0

    store = LanceDBStore.open(config.LANCEDB_DIR)
    assembler = ContextAssembler(store=store)
    context_chunks = assembler.assemble(retrieved)

    generator = OpenAIGenerator()
    result = generator.generate(context_chunks=context_chunks, question=question)
    logger.info(
        "generation.cli context_doc_ids=%s sources=%s",
        [c.doc_id for c in context_chunks],
        result.sources,
    )
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Data Flow

```
              ┌────────────────────────────────────────────────────────────────┐
              │                       rag-ask CLI                              │
              │                                                                │
   question ──┼──► HybridRetriever.retrieve(question)                          │
              │              │                                                  │
              │   ┌──────────┴──────────┐                                       │
              │   │                     │                                       │
              │   ▼                     ▼                                       │
              │  []          [(d1, s1), (d2, s2), ...]                          │
              │   │                     │                                       │
              │   │ ◄────── FR-8 short-circuit: no LLM call (AC-8) ────┐        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │           ContextAssembler.assemble()               │        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │     VectorStore.fetch_chunks_by_doc_ids([d1, d2])  │        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │       dedup top-1 / doc_id, preserve order,        │        │
              │   │       truncate max_chunks                          │        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │             list[Chunk]                            │        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │        prompt.build_system_prompt()                │        │
              │   │        prompt.build_user_prompt(ctx, q)            │        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │       OpenAIGenerator.generate(ctx, q)             │        │
              │   │            (chat.completions.create                │        │
              │   │             response_format=json_schema strict     │        │
              │   │             temperature=0)                         │        │
              │   │                     │                              │        │
              │   │                     ▼                              │        │
              │   │           AnswerWithSources(answer, sources)       │        │
              │   ▼                     │                              │        │
              │  AnswerWithSources(     │                              │        │
              │    answer=ABSTAIN_ANSWER, sources=[]) ◄────────────────┘        │
              │   │                     │                                       │
              │   └──────────┬──────────┘                                       │
              │              ▼                                                  │
              │   stdout: result.model_dump_json()                              │
              │   INFO log: context doc_ids + final sources (NFR-5, AC-18)      │
              └────────────────────────────────────────────────────────────────┘
```

The short-circuit intercept (annotated `FR-8 short-circuit`) is the only branch in the
CLI flow. It is exercised by AC-8 with a stub or spy `Generator` that asserts
`.generate` is never called.

## Implementation Phases

Ordered per the harness convention (data schema → config → core src → eval/observability →
tests → docs/ADR). Phase 3 has no `eval/` or `observability/` work in scope. Each phase
is independently testable — `/implement` runs `uv run pytest tests/generation -k <phase>`
before moving on.

1. **Data schema + `Generator` Protocol + `AnswerWithSources`** —
   `generation/schema.py`, `generation/interfaces.py`, `generation/__init__.py`. The
   Pydantic model + the Protocol are the two contracts every later phase depends on.
   Smallest-first validation: `uv run pytest tests/generation/test_schema.py`.

2. **Config — `VectorStore` extension + `LanceDBStore` impl + `pyproject.toml` deps** —
   one method added to `retrieval/interfaces.py`, one method body added to
   `retrieval/vector_store.py`, one test method added to
   `tests/retrieval/test_vector_store.py`. `pyproject.toml`: add `openai` (one new dep,
   NFR-3, AC-16 — pin `openai>=1.50,<2.0` for the Pydantic-2-friendly client surface);
   add the `rag-ask` console-script entry; no new pytest marker (the `smoke` marker
   from Phase 2 is reused per AC-12). Validation:
   `uv run pytest tests/retrieval/test_vector_store.py` (fetch-by-doc-ids case).

3. **`ContextAssembler`** — `generation/context.py` and
   `tests/generation/test_context_assembler.py`. Unit tests for the top-1-per-doc-id
   policy (AC-6), the lex-smallest `chunk_id` selection, the rank-order preservation,
   the `max_chunks` truncation, and the empty-input case. No network. The assembler is
   the load-bearing policy unit; isolate-and-test it before any prompt or LLM code.

4. **Prompt builder** — `generation/prompt.py` and `tests/generation/test_prompt.py`.
   Tests assert byte-identical output across two invocations (AC-7) and the
   `[N] {doc_id}: {text}` format. No imports of openai. This is pure-Python and the
   determinism gate must hold before any LLM call is wired.

5. **`StubGenerator` + pipeline-contract test (offline gate)** —
   `generation/stub_generator.py`, `tests/generation/test_stub_generator.py`,
   `tests/generation/test_generation_contract.py`, `tests/generation/conftest.py`. The
   contract test wires a fixture retriever (returns two `(doc_id, score)` pairs), a
   fixture in-memory `VectorStore` implementation, `ContextAssembler`,
   `StubGenerator`, and asserts `result.sources == [d1, d2]` in fused-rank order
   (AC-11, FR-11). Runs offline under `make verify` (NFR-1). Validation:
   `uv run pytest tests/generation -m "not smoke"`.

6. **`OpenAIGenerator` + `rag-ask` CLI + `make smoke` + smoke test** —
   `generation/openai_generator.py`, `generation/cli.py`,
   `tests/generation/test_cli.py`, `tests/generation/test_generation_smoke.py`,
   `Makefile`. The CLI test uses a stub generator injection point or monkeypatches the
   loader for the abstention-branch coverage (AC-8) and the no-key error message
   coverage (AC-14). `Makefile`: add `smoke` target invoking
   `uv run pytest tests/generation/test_generation_smoke.py -m smoke`; add a help-doc
   line. The smoke test's first `/implement` step is the streamed dataset inspection
   to pick the 10 `SMOKE_QUESTIONS` (RQ-10) — mirrors Phase 2's RQ-2 resolution.
   Validation: `uv run pytest tests/generation/test_cli.py` offline first, then
   `make smoke` locally with `OPENAI_API_KEY` set and a built index.

7. **ADR-003 + planned-ADR renumber + grep** — `docs/adr/0003-generation.md`,
   `docs/adr/README.md`. Run the one-time `rg -i "ADR-003|ADR-004"` (RQ-12) across
   `docs/`, `.claude/`, and the Carreira `portfolio/enterprise_rag_ops/`; update any
   stale references in the same commit. Update Carreira `adrs_planned.md`:
   observability → ADR-004, LLM matrix → ADR-005 (FR-14, AC-15). The ADR is written
   last so it captures the as-shipped decisions, not predicted ones.

Per Engineering Behavior: validate smallest-first
(`uv run pytest tests/generation -k <module>`), then `make verify`, then the local-only
`make smoke` on a real checkout with `OPENAI_API_KEY` exported.

## ADR-003 Scope

`docs/adr/0003-generation.md` must contain the following sections, matching
ADR-002's headings and tone (concise; the "why" lives here, the "what" lives in code):

- **Title + Status + Date** — `# ADR-0003: Generation Layer — OpenAI Structured
Outputs with Source Attribution`, `Status: accepted`, `Date: 2026-05-20`.
- **Context** — Phase 2 retriever returns `(doc_id, score)`-only; Phase 3 must close
  the loop. Substrate sprint, deliberately conventional generation. Sprint 2 will
  consume the `AnswerWithSources` schema as its eval surface; Sprint 3 will
  instrument the `Generator` seam.
- **Decision** — five numbered components matching ADR-002's structure:
  1. **`Generator` Protocol seam** — Phase 3 ships `OpenAIGenerator`
     (`gpt-5-nano-2025-08-07`, `RAG_GEN_MODEL` override) and `StubGenerator` (CI).
  2. **Attribution format** — structured JSON via OpenAI `response_format`
     (`json_schema`, `strict: true`); `AnswerWithSources` Pydantic model
     (`answer: str`, `sources: list[str]`) is the single schema source of truth.
  3. **`VectorStore` extension** — one new method (`fetch_chunks_by_doc_ids`),
     justified by use; existing two methods unchanged.
  4. **`ContextAssembler`** — standalone class; top-1 chunk per `doc_id`
     (lex-smallest `chunk_id`); preserves fused-rank order; default
     `max_chunks=5`.
  5. **Abstention** — Python short-circuit on empty retriever result; fixed
     "no information" `AnswerWithSources` with `sources=[]`; **no LLM call**.
- **Consequences** — three subsections matching ADR-002 ("What we accept", "What
  changes when it changes", "Build-time invariants"):
  - _What we accept:_ one new dep (`openai`); `make smoke` requires
    `OPENAI_API_KEY` and a built index (local-only); cost of `gpt-5-nano-2025-08-07`
    is well under $0.05 per smoke run at default settings.
  - _What changes when it changes:_ the named future swap is **ADR-005 LLM
    matrix** behind the `Generator` Protocol — a new file plus a one-line wiring
    change in `generation/cli.py`. `MAX_CONTEXT_CHUNKS` is a constructor parameter,
    not an env var — Sprint 2 sweeps configure it at the call site.
  - _Build-time invariants:_ temperature is fixed at 0; prompt construction is
    deterministic (byte-identical for identical inputs); `AnswerWithSources` is
    schema-validated by the OpenAI API (`strict: true`) and defensively
    re-validated through Pydantic.
- **Carry-forward flag — same-family judge/generator** — explicit subsection
  recording the Decision 2 trade-off (RQ-2): using OpenAI for both the Phase 3
  generator and the Sprint 2 judge reduces eval independence. **ADR-005 must
  address it** — likely by routing generation to a different family (Anthropic
  Haiku/Sonnet, or local Ollama for spot-checks) while keeping
  `gpt-5-nano-2025-08-07` as the judge.
- **Planned-ADR renumber** — single-line note: observability → ADR-004; LLM matrix
  → ADR-005; the `rg -i "ADR-003|ADR-004"` grep was run during `/implement` and
  any stale references were updated in the same commit (RQ-12).
- **Alternatives Considered** — short table mirroring ADR-002: vector store extension
  vs. retriever extension vs. standalone assembler; structured JSON vs. inline
  `[doc_id]` vs. inline numbered citations; Anthropic Haiku vs. OpenAI for the
  generator default. Picked / Rejected / Why columns.
- **References** — `.claude/sdd/features/sprint-1/phase-3-generation/` (all three
  artifacts); ADR-002; the `rag-retrieval` KB (and a forward reference to a
  planned `rag-generation` KB, post-Phase 3).

`docs/adr/README.md` is updated to list ADR-003 in its index and note the planned
ADR-004 / ADR-005 numbering (the Carreira `adrs_planned.md` change is private and
does not appear in the public README).

## Infrastructure Gaps

Three-layer deep check. DEFINE found one non-blocking gap (`rag-generation` KB); this
design confirms that finding and refines the assessment.

| Layer            | Dependency                                                                                        | KB domain               | Specialist | Status                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------- | ----------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Domain existence | retrieval contract carry-over                                                                     | `rag-retrieval`         | n/a        | Pass. `_index.yaml` lists `rag-retrieval` with 7 concepts + 2 patterns. The `VectorStore` extension and `Chunk` reuse are covered by the existing domain — no new domain required for the Phase 3 retrieval-side changes.                                                                                                                                                                     |
| Domain existence | generation (structured outputs, prompt, abstention)                                               | `rag-generation` (none) | n/a        | **Gap, non-blocking.** No `rag-generation` KB exists. DEFINE classified it as a post-Phase 3 action; this design confirms: the OpenAI SDK docs + the BRAINSTORM/DEFINE artifacts are sufficient grounding for `/implement`. Recommend `/new-kb rag-generation` after `/review` lands.                                                                                                         |
| Concept coverage | `rag-retrieval` concepts vs. Phase 3 needs                                                        | `rag-retrieval`         | n/a        | Pass. Phase 3 does not introduce new retrieval concepts — it consumes the existing `Retriever` contract and extends `VectorStore` by one mechanical read method. Pattern files (`hybrid-retrieve-fuse`, `expected-doc-ids-smoke`) are unchanged.                                                                                                                                              |
| Concept coverage | generation concepts (structured outputs, prompt template, abstention pattern, source attribution) | (none)                  | n/a        | **Gap, non-blocking.** These would live in the (currently missing) `rag-generation` domain. None are blocking — DEFINE's RQ-3, RQ-4, RQ-11 already pin the design choices; `/implement` does not need KB concepts to execute.                                                                                                                                                                 |
| Agent alignment  | retrieval-engineer                                                                                | `rag-retrieval`         | none       | Pass with a noted absence (carried over from Phase 2's gap table). No retrieval specialist exists; the surgical `VectorStore` extension is assigned to `direct`.                                                                                                                                                                                                                              |
| Agent alignment  | generation-engineer                                                                               | `rag-generation` (none) | none       | **Gap, non-blocking.** No generation specialist exists. DEFINE explicitly rejects scaffolding one — a conventional single-turn prompt + structured output is small and well-bounded; no repeated specialist context-loading is anticipated. Revisit only if `/implement` shows repeated friction (would surface a post-phase `**Harness suggestion:**` for `/new-agent generation-engineer`). |

**Summary:** zero blocking gaps. Two non-blocking gaps (missing `rag-generation` KB
and missing `generation-engineer` agent) are both deferred post-Phase 3 with the same
reasoning DEFINE used: the BRAINSTORM/DEFINE artifacts + OpenAI SDK docs give
`/implement` sufficient grounding to ship Phase 3 cleanly. `/review` should re-raise
the `/new-kb rag-generation` recommendation if Phase 3 introduces repeated reasoning
that would have benefited from prior KB scaffolding.

## Risks & Mitigations

| Risk                                                                                                                                                                                                                 | Mitigation                                                                                                                                                                                                                                                                                                                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **OpenAI structured-outputs schema validation failure** — `strict: true` rejects responses that drift from the schema; could surface as an SDK error mid-smoke.                                                      | Server-side `strict: true` enforces the schema; the `OpenAIGenerator` defensively re-validates the JSON through `AnswerWithSources.model_validate_json` so the failure mode is a typed Pydantic `ValidationError`, not an opaque SDK exception. Unit test in `test_cli.py` covers a malformed-payload monkeypatched client. |
| **`gpt-5-nano-2025-08-07` rate-limit or model-availability surprise** — model name pinning may drift; OpenAI could deprecate or rate-limit.                                                                          | `RAG_GEN_MODEL` env var (FR-3) is the documented override — no code change required to swap models for a smoke run. Default model name is set in `generation/openai_generator.py` as `DEFAULT_MODEL = "gpt-5-nano-2025-08-07"`; that single constant is the change site if pinning needs to move.                           |
| **Same-family judge/generator (Decision 2 carry-forward)** — using OpenAI for the Phase 3 generator and the Sprint 2 judge reduces eval independence; may inflate measured faithfulness.                             | ADR-003 records the concern explicitly as a "Carry-forward flag" subsection (per RQ-2). ADR-005 (LLM matrix) is the resolution venue — likely a Haiku/Sonnet generator default with `gpt-5-nano-2025-08-07` retained as the judge. The `Generator` seam makes the swap a localized change.                                  |
| **`load_retriever` re-chunking drift (Phase 2 gotcha)** — `pipeline.load_retriever()` re-reads `corpus.jsonl` and re-chunks at startup to rebuild `chunk_to_doc`. Same drift risk if the chunker changes underneath. | Opportunistic harden only if `/implement` touches `load_retriever`; otherwise leave for Sprint 2 (DEFINE's carry-forward flag). Phase 3 does not need to rebuild the retriever — it calls the existing loader unchanged.                                                                                                    |
| **Empty retriever result must not call OpenAI** — the AC-8 invariant is the load-bearing abstention behavior; a regression here would burn API calls on every off-topic query and skew Sprint 2 cost baselines.      | Explicit `if not retrieved:` branch in `generation/cli.py` (FR-8); the CLI test in `test_cli.py` uses a spy `Generator` (e.g., a `StubGenerator` subclass that tracks calls) and asserts `.generate` was **not** called when the retriever returns `[]`. AC-8 verifies.                                                     |
| **`fetch_chunks_by_doc_ids` SQL-style filter escaping** — single quotes inside `doc_id` would break the `IN (...)` clause and could enable SQL-injection-style misbehavior.                                          | SQL-escape single quotes (`replace("'", "''")`) — same defensive pattern Phase 2 used in `dense_search`'s `source_type_filter`. Sprint 3 should replace both with a parameterized LanceDB filter once exposed via the official API (REVIEW non-blocking #3 carry-over).                                                     |
| **`ContextAssembler` empty store result** — `fetch_chunks_by_doc_ids` could return `[]` for a stale or partial index, causing the assembler to silently drop chunks and pass an empty `context_chunks` to the LLM.   | Defensive `if not chunks: continue` per-doc_id in the assembler; unit test covers the empty-store case. The CLI logs the post-assembler `doc_id`s at INFO (NFR-5), so a stale-index regression is observable in smoke output before it ships.                                                                               |
| **CI offline invariant** — a stray `from openai import OpenAI` at import time of any non-OpenAIGenerator module would let `make verify` pass on a developer machine with the SDK cached but fail on a clean clone.   | The `openai` import lives only inside `generation/openai_generator.py`. Other modules (`schema.py`, `interfaces.py`, `context.py`, `prompt.py`, `stub_generator.py`) have zero `openai` imports. `make verify` runs `tests/generation -m "not smoke"`; the smoke file is the only one that imports `OpenAIGenerator`.       |

## Next Step

→ `/implement sprint-1/phase-3-generation` — no infrastructure gaps to address first;
proceed directly. First implementation step is the one-time
`rg -i "ADR-003|ADR-004"` grep (RQ-12) followed by the streamed dataset inspection to
fix the 10 `SMOKE_QUESTIONS` (RQ-10) — both mirror Phase 2's setup patterns.
