# ADR-0003: Generation Layer — OpenAI Structured Outputs with Source Attribution

**Status:** accepted
**Date:** 2026-05-20

## Context

Sprint 1 Phase 3 closes the substrate loop. ADR-002's hybrid retriever returns
`list[(doc_id, fused_score)]` — doc identifiers only, no chunk text. Phase 3
must turn that into an answer with cited sources: fetch chunk text, build a
prompt, call an LLM, and return a structured payload Sprint 2's eval harness
can score against `answer_facts`.

The generation layer is deliberately conventional. The differentiator of this
project is the eval + observability layers in Sprints 2–3, not the
single-turn RAG. Phase 3's job is to ship the smallest correct substrate with
the right seams, then move on.

Constraints:

- `make test` stays offline and free — no API key, no model download in CI
  (carries the NFR-3 invariant from ADR-002).
- The retriever contract from ADR-002 is the input contract; do not reshape it.
- Sprint 2 will evaluate this layer; ADR-004 (observability, formerly ADR-003)
  will instrument it; ADR-005 (LLM matrix, formerly ADR-004) will swap models.
- Phase 3 must pick a default LLM without pre-empting ADR-005.

## Decision

A four-component generation layer behind one new Protocol seam plus a
one-method extension to an existing seam:

1. **`Generator` Protocol seam** (the fourth seam, joining ADR-002's
   `Embedder` / `VectorStore` / `Retriever`). Single method
   `generate(context_chunks, question) -> AnswerWithSources`. Phase 3 ships
   `OpenAIGenerator` (production, default model `gpt-5-nano-2025-08-07`,
   override via env var `RAG_GEN_MODEL`) and `StubGenerator` (CI). The
   Protocol is the named swap surface for ADR-005's LLM matrix — a
   `ClaudeGenerator` or `OllamaGenerator` is a new file plus a one-line
   wiring change in `generation/cli.py`.
2. **Attribution format: structured JSON.** OpenAI structured outputs via
   `response_format={"type": "json_schema", "json_schema": <schema>, "strict": true}`.
   `AnswerWithSources` is a Pydantic model with `answer: str` and
   `sources: list[str]`; its `model_json_schema()` is the single source of
   truth shared by the OpenAI call, the system-prompt schema fragment, and
   the CLI's stdout payload. The model re-validates the response through
   Pydantic as a second line of defense against schema drift.
3. **Chunk-level retrieval for generation.** `HybridRetriever.retrieve_chunks`
   returns `(chunk_id, doc_id, fused_score)` — the **winning** (highest-ranked)
   chunk per doc, in fused-rank order — alongside the doc-level `retrieve` that
   eval uses. Generation must feed the LLM the _relevant_ chunk, not an
   arbitrary one: the doc-dedup in `retrieve` discards which chunk ranked, and
   feeding a doc's first chunk (often a title) starves the model of the answer.
   `retrieve_chunks` is added to the `Retriever` Protocol (justified by use —
   the same reasoning as the `VectorStore` extension). The `VectorStore`
   Protocol gains exactly one method — `fetch_chunks_by_chunk_ids(chunk_ids) ->
list[Chunk]` — to read those specific chunks' text; `add` and `dense_search`
   are untouched. `LanceDBStore` implements it as a SQL-style `chunk_id IN (...)`
   filter (same defensive single-quote escaping as `dense_search`).
4. **`ContextAssembler`** — standalone class, not behind a Protocol (its only
   collaborator is `VectorStore`, already a seam — adding another would be
   "in case"). Takes the ranked `(chunk_id, doc_id, score)` hits, fetches those
   chunks' text via `VectorStore.fetch_chunks_by_chunk_ids`, preserves
   fused-rank order, and truncates to `max_chunks` (default 5, configurable at
   construction time — no env var, to keep the config surface narrow).
5. **Abstention via Python short-circuit.** When
   `Retriever.retrieve_chunks()` returns `[]` (top-1 cosine below the ADR-002
   threshold of 0.45), the CLI returns a fixed
   `AnswerWithSources(answer="I don't have enough information to answer this
question.", sources=[])` **without an LLM call**. The short-circuit is a
   Python branch in `generation/cli.py` — not a prompt instruction — so the
   OpenAI cost on an off-topic query is exactly zero.

> **Update (Sprint 2, Phase 5):** the sentinel is no longer gate-only. The
> Phase-5 abstention work found that the retrieval gate rarely fires for
> unanswerable questions (their best dense score sits above the 0.45 threshold),
> so the **generator prompt now also instructs the model to emit the exact
> `ABSTAIN_ANSWER` sentinel** (with empty `sources`) when the context is
> insufficient. Abstention is thus a single canonical contract enforced at
> **both** the gate and the generator, which is what makes end-to-end abstention
> machine-checkable by exact match. The sentinel constant moved to
> `generation/schema.py` (shared by `cli.py` and `prompt.py`, no import cycle).
> See ADR-0006 (cassette/replay) and the Phase-5 review.

The prompt has two parts (Decision 4-B). System prompt carries the role, the
JSON output instruction, and the JSON schema. The user turn carries a
numbered context block (`[1] doc_id: text\n[2] doc_id: text\n...`) followed
by the question. Temperature is fixed at 0; prompt construction is
deterministic (byte-identical for identical inputs).

## Consequences

### What we accept

- **One new runtime dependency** — `openai>=1.50,<2.0` in `pyproject.toml`.
  Adds the SDK to the offline test path's import surface, but the `openai`
  import lives only inside `generation/openai_generator.py`; nothing else in
  the package imports it, so `make test` exercises the full pipeline
  through `StubGenerator` without touching the SDK at runtime.
- **`make smoke` requires `OPENAI_API_KEY` + a built index** — local-only,
  excluded from `make test` via the existing `smoke` pytest marker (the
  same marker `make retrieval-smoke` uses). Cost at default settings:
  10 questions × `gpt-5-nano-2025-08-07` (~$0.05/1M in, ~$0.40/1M out) with
  short context blocks ≈ well under $0.05 per smoke run.
- **No agentic / multi-hop / reranker integration** — Phase 2 left the
  `reranker=None` composability hook; Phase 3 does not activate it.
  Multi-hop is Sprint 2+ if at all.
- **Faithful abstention dominates on the dev subset.** The default
  100-docs/source subset contains the gold documents for only 3 of the 500
  benchmark questions, and of those only some have an answer self-contained in
  the single top-ranked chunk the assembler feeds. For everything else the
  retriever returns vocabulary-similar but wrong (or only partially relevant)
  docs, and the generator correctly answers "the context does not contain this"
  with `sources=[]`. This is the desired, thesis-aligned behavior — so the smoke
  gate asserts `len(sources) >= 1` only on the attribution subset (`qst_0104`,
  `qst_0258`), and a valid non-empty `answer` (wiring + faithful behavior) on all 10. `qst_0252` is answerable-in-corpus but its decision rule spans chunks
  beyond the top-1 fed, so it abstains — a multi-chunk / completeness retrieval
  concern for Sprint 2's eval harness, not the substrate. A full-corpus index or
  multi-chunk-per-doc context would lift this, both out of scope here.

### What changes when it changes

- **ADR-005 (LLM matrix)** is the named future swap behind the `Generator`
  Protocol — a new file implementing `Generator` plus a one-line change in
  `generation/cli.py`. The `RAG_GEN_MODEL` env var lets a smoke run swap
  OpenAI model variants without a code change.
- **`MAX_CONTEXT_CHUNKS = 5`** is a constructor parameter on
  `ContextAssembler`, not an env var. Sprint 2 parameter sweeps configure it
  at the call site; runtime users get the default.
- **The `AnswerWithSources` schema** is the Sprint 2 eval input contract.
  Any change to it ripples into the eval harness; the closed-object schema
  (`extra="forbid"`) means OpenAI's `strict: true` mode rejects any drift
  server-side before it reaches Pydantic.

### Build-time invariants

- **Temperature is left at the model default.** `gpt-5-nano-2025-08-07`
  (a GPT-5-class model) rejects any explicit `temperature` other than 1, so the
  generator does not send one. Determinism is carried by the deterministic
  prompt builder; a model-level reproducibility strategy (a `seed`, or a
  temperature-capable model) is deferred to ADR-005 / Sprint 2's eval harness,
  where reproducibility actually matters.
- **Prompt construction is deterministic** — `build_system_prompt()` and
  `build_user_prompt()` are pure functions; identical inputs produce
  byte-identical outputs (asserted by `test_prompt.py`).
- **Schema is closed** — `AnswerWithSources` has `extra="forbid"`, which
  serializes as `additionalProperties: false` in JSON Schema; OpenAI
  `strict: true` mode enforces this server-side.
- **The abstention short-circuit must not call OpenAI** — asserted by
  `test_cli.py::test_abstain_short_circuit_does_not_call_generator` with a
  spy generator that fails the test if `.generate` is invoked.

## Carry-forward flag — same-family judge / generator

Decision 2 picks `gpt-5-nano-2025-08-07` as the generator default for cost.
The project separately designates `gpt-5-nano-2025-08-07` as the **judge** for
Sprint 2's eval harness. Using
the same OpenAI family for both reduces eval independence and may inflate
measured faithfulness scores when a judge from the same provider rates a
generator's output.

**ADR-005 (LLM matrix) is the resolution venue.** A likely resolution is
routing generation to a different family (Anthropic Claude Haiku/Sonnet, or
local Ollama for spot-checks) while keeping `gpt-5-nano-2025-08-07` as the
judge. The `Generator` Protocol seam makes that swap a localized change.

## Planned-ADR renumber

This ADR takes the ADR-003 slot, which had been earmarked for the
observability tool. The planned numbers shift by one:

- Observability tool: **ADR-004**
- LLM provider / model matrix: **ADR-005**
- (planned later) Failure-mode taxonomy: ADR-006

No shipped ADR referenced ADR-003 by number before this one (ADR-002 was the
most recent), so the renumber is a no-op for the public `docs/adr/` index.

## Alternatives Considered

| Choice               | Picked                                                                        | Rejected                                                                           | Why                                                                                                                                                                                                                       |
| -------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Context assembly     | Chunk-level `retrieve_chunks` (winning chunk per doc) + `ContextAssembler`    | Top-1 chunk per doc by lex-smallest `chunk_id`; all chunks per doc                 | The lex-smallest policy (first design) fed the doc's title chunk and starved the LLM — the live smoke caught it. Surfacing the winning chunk_id sends the relevant passage; doc-level `retrieve` stays the eval contract. |
| LLM provider default | OpenAI `gpt-5-nano-2025-08-07`                                                | Anthropic Claude Haiku; config-driven both                                         | Cheapest model; spec lists OpenAI for the judge but the cost difference dominates here. Same-family carry-forward flag (above) records the trade-off for ADR-005.                                                         |
| Attribution          | Structured JSON via OpenAI structured outputs                                 | Inline numbered `[1]` citations; inline `[doc_id]` tokens                          | No string parsing, no hallucinated mapping; OpenAI `strict: true` enforces schema server-side; ideal eval surface for Sprint 2.                                                                                           |
| Prompt structure     | System (role + schema) + user (context + question)                            | Single-turn user only; three-message multi-turn                                    | Clean role separation; system-prompt schema is idiomatic for OpenAI structured outputs; multi-turn is unnecessary for single-hop.                                                                                         |
| Smoke gate scope     | Two-tier: non-empty answer on all 10; `len(sources) >= 1` on the 3 answerable | Flat `len(sources) >= 1` on all 10; `sources ⊆ expected_doc_ids`; per-fact judging | Flat source-on-every-question would only pass via hallucinated citations — see "Faithful abstention" below. Two-tier proves wiring on all + attribution on the answerable subset; correctness is Sprint 2's eval harness. |
| CI strategy          | `StubGenerator` behind `Generator` seam                                       | Skip generator tests in CI; cassette / replay                                      | Exact precedent from ADR-002's `StubEmbedder`; exercises full pipeline wiring; no API key needed. Cassette pattern deferred to ADR-001 in Sprint 2.                                                                       |
| ADR number           | ADR-003 generation; renumber observability → ADR-004, LLM matrix → ADR-005    | Defer to DESIGN.md only; keep observability as ADR-003                             | Anti-rot principle: capture the live decision now. Renumber risk is low — no shipped ADR references ADR-003 by number yet (ADR-002 was the most recent).                                                                  |

## References

- `.claude/sdd/features/sprint-1/phase-3-generation/` — BRAINSTORM, DEFINE, DESIGN.
- ADR-0002 — retrieval architecture; defines the `Retriever` / `VectorStore`
  / `Embedder` Protocols this ADR extends.
- `.claude/kb/rag-retrieval/` — KB domain that grounds the upstream contract.
  A `rag-generation` KB is a planned post-Phase 3 `/new-kb` (same pattern as
  Phase 2's `rag-retrieval` refocus after ADR-002).
