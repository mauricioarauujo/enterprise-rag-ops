# BRAINSTORM: phase-3-generation — Generation Layer with Source Attribution

**Sprint/Phase:** sprint-1/phase-3-generation | **Date:** 2026-05-20

## Problem Statement

Phase 2 shipped a hybrid retriever (`HybridRetriever`) that returns `list[(doc_id,
fused_score)]` — doc identifiers only, no chunk text. Phase 3 must close the loop: take
those doc identifiers, retrieve chunk text, compose a prompt, call an LLM, and return an
answer with cited sources. The deliverable is a `rag-ask` CLI entry-point and a
`make smoke` gate that runs it on 10 questions from EnterpriseRAG-Bench, returning a
non-empty answer plus ≥1 cited source per question. This is the final substrate phase of
Sprint 1. The differentiator of this project is the eval and observability layer
(Sprints 2–3); generation is deliberately conventional.

---

## Research & KB Scan

| Topic                                                    | KB file / domain                                   | Coverage                                                                          |
| -------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------- |
| Retriever Protocol and output contract (`doc_id, score`) | `rag-retrieval/patterns/hybrid-retrieve-fuse.md`   | Sufficient — ADR-002 is the SSoT                                                  |
| VectorStore contract (`add`, `dense_search` only)        | `retrieval/interfaces.py` (codebase)               | Sufficient — gap is the missing fetch-by-id method                                |
| LLM provider APIs (Anthropic / OpenAI)                   | None in KB                                         | Thin — not needed for a stub-based substrate; real-call details are provider docs |
| RAG prompt patterns (system/user, context block)         | None in KB                                         | Thin — sufficient for a conventional single-turn prompt                           |
| Source attribution patterns                              | None in KB                                         | Missing — pattern file would help Sprint 2; defer to post-Phase 3 KB update       |
| Abstention handling                                      | `rag-retrieval/concepts/retrieval-eval-metrics.md` | Sufficient — ADR-002 defines the abstention gate                                  |
| CI strategy for LLM-dependent modules                    | `rag-retrieval/patterns/expected-doc-ids-smoke.md` | Sufficient — StubEmbedder pattern is the direct analogue                          |
| Multi-hop agent design                                   | None in KB                                         | Not needed — explicitly deferred (Won't)                                          |
| Cost/latency tracking                                    | None in KB                                         | Not needed — Sprint 3 concern (Won't)                                             |

**Conclusion:** No `/new-kb` or `--deep-research` is needed before `/define`. The
`rag-retrieval` KB is sufficient for the retrieval contract. LLM provider details are
covered by their own documentation and are not complex enough to warrant a KB entry
before a conventional single-turn prompt is implemented. A `rag-generation` KB domain
is a Sprint 2 candidate (post-Phase 3), once the attribution format and Generator seam
choices are proven by implementation.

---

## Approaches Considered

### Decision 1 — Context Assembly: getting chunk text from `(doc_id, score)`

`Retriever.retrieve()` returns `list[(doc_id, fused_score)]`. The LanceDB schema stores
`text` per chunk, but `VectorStore` exposes only `add` and `dense_search`. The generation
layer needs the full chunk text to build the prompt context block.

| Approach                                                              | Pros                                                                                                                                                                                                                                                             | Cons                                                                                                                                                                                                                                                                                     | Effort                          |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| A. Extend `Retriever.retrieve()` to return `(doc_id, score, text)`    | One call gives everything; no new abstraction                                                                                                                                                                                                                    | Breaks the retrieval / generation seam — evaluation and retrieval layers have no business caring about raw text; makes the Protocol harder to stub cleanly; contradicts ADR-002's framing of `Retriever` as the "contract Phase 3 generation depends on" (not one that Phase 3 reshapes) | S (code) / M (downstream churn) |
| B. Add `VectorStore.fetch_chunks_by_doc_ids(doc_ids)` to the Protocol | Minimal extension to the existing seam; `VectorStore` already owns the text; fetch is a natural read operation on the store                                                                                                                                      | Widens the `VectorStore` Protocol — any future `VectorStore` implementation must implement fetch; the Protocol seam was deliberately kept narrow (add + dense_search)                                                                                                                    | S                               |
| C. Standalone `ContextAssembler` that owns the LanceDB lookup         | Keeps `Retriever` and `VectorStore` Protocols pure and stable; single-responsibility: assembler translates `(doc_id, score)` → `list[Chunk]`; easy to swap the backing store in; mirrors the Phase 2 philosophy of naming seams, not widening existing contracts | One additional class and file; LanceDB still accessed directly inside assembler (not behind VectorStore Protocol) unless B is also adopted                                                                                                                                               | S                               |

**Recommendation: Approach C (`ContextAssembler`) with a minimal `VectorStore.fetch_chunks_by_doc_ids` added to the Protocol (hybrid C+B).** The assembler keeps `Retriever` pure — critical because Sprint 2 will evaluate the retriever in isolation. The `fetch_chunks_by_doc_ids` addition to `VectorStore` is unavoidable (something must translate doc_ids to text), and the Protocol is a better home for it than direct LanceDB access inside the assembler (keeps the anticipated LanceDB→Qdrant swap localized). The assembler calls `store.fetch_chunks_by_doc_ids(doc_ids)`, deduplicates to top-1 chunk per doc_id (preserving fused rank order), and returns an ordered `list[Chunk]` for the prompt builder.

---

### Decision 2 — LLM Provider for the Substrate Default

`adrs_planned.md` schedules ADR-004 (LLM provider and model matrix) for Phase 5/6. The
spec names Claude Haiku/Sonnet for generation and `gpt-5-nano-2025-08-07` for the judge.
Phase 3 must pick a default without pre-empting ADR-004.

| Approach                                                                       | Pros                                                                                                                                              | Cons                                                                                                                                                                                           | Effort |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Anthropic Claude (`claude-haiku-4-5` default) behind a `Generator` Protocol | Spec explicitly lists Haiku/Sonnet for generation; same family as the coding environment; ADR-004 anticipates this; seam makes the swap localized | One provider default only — OpenAI users need an env var or config change                                                                                                                      | S      |
| B. OpenAI (`gpt-4.1-nano` or similar) behind a `Generator` Protocol            | Low cost per call (~$0.10/1M tokens); familiar                                                                                                    | Spec designates OpenAI for the judge model, not the generator; mixing judge and generator into the same family reduces eval independence (Sprint 2 concern); slightly at odds with spec intent | S      |
| C. Config-driven with both providers wired at Phase 3                          | Flexible; demonstrates multi-provider design early                                                                                                | Pre-empts ADR-004; adds provider-selection logic that belongs to Sprint 4+; scope creep for a substrate phase                                                                                  | M      |

**Recommendation: Approach A (Anthropic Claude Haiku default, `Generator` Protocol seam).** This directly follows the spec and mirrors the ADR-002 seam rationale: name the contract, wire one default, keep the door open for ADR-004's swap. The `Generator` Protocol is the Phase 3 seam — future implementations (`OpenAIGenerator`, `OllamaGenerator`) are one file each plus a one-line wiring change. Haiku is cheap enough for the smoke gate (10 questions × ~$0.001/question ≈ $0.01 total). The `ANTHROPIC_API_KEY` env var requirement is stated explicitly in the `make smoke` docs.

---

### Decision 3 — Attribution Mechanism

How should the LLM cite sources in its answer? Sprint 2 will evaluate attribution
quality; the choice here sets the eval surface.

| Approach                                                                                                    | Pros                                                                                                                        | Cons                                                                                                                                                                      | Effort |
| ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Inline numbered citations `[1]` with trailing source list                                                | Natural reading; common convention; easy for a human reviewer to check                                                      | Requires parsing the trailing list to extract doc_ids; LLMs occasionally hallucinate citation numbers or mix up the mapping                                               | S      |
| B. Inline `[doc_id]` tokens directly in the answer text                                                     | Doc_id is ground truth — no mapping table needed; trivial to parse; eval-friendly (exact string match on extracted doc_ids) | Ugly in the answer text; doc_ids are opaque strings (e.g., `confluence::abc123`); unnatural for a reader                                                                  | S      |
| C. Structured output — JSON with `answer` and `sources` fields (Pydantic + Anthropic tool use or JSON mode) | Clean separation; zero parsing ambiguity; ideal eval surface for Sprint 2; `sources` is a `list[str]` of doc_ids            | Adds prompt complexity (tool definition or JSON schema in system prompt); Anthropic's tool use API is slightly more code than a plain completion; increases prompt tokens | S–M    |

**Recommendation: Approach C (structured output via Pydantic schema + Anthropic JSON mode).** The attribution format is the most consequential seam for Sprint 2 eval. Inline citations require fragile regex parsing and introduce hallucination risk in the citation mapping. Structured output eliminates both problems: `sources: list[str]` is a first-class field, extractable without parsing. Anthropic's `claude-haiku-4-5` supports JSON mode via a system prompt instruction plus a `max_tokens` + response format hint — no tool-call overhead needed for a simple schema. The `AnswerWithSources` Pydantic model serves as the canonical output schema across the `Generator` Protocol, the CLI output, and Sprint 2's eval harness input.

---

### Decision 4 — Prompt Structure

Where does context, question, and instruction live? Where does abstention live?

| Approach                                                                                   | Pros                                                                                                                                                                | Cons                                                                                                                 | Effort |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Single system prompt + user turn; context block in the user turn after question         | Simple; LLMs handle this well; context length is bounded by top-k chunk count                                                                                       | Mixing context and question in the user turn is slightly unconventional                                              | S      |
| B. System prompt = role + instructions + JSON schema; user turn = context block + question | Clean role separation; JSON output instruction in system prompt is idiomatic for Anthropic; explicit schema in system prompt improves structured output reliability | Two-part prompt to maintain; slightly more tokens in system prompt                                                   | S      |
| C. Context + question + instructions as three distinct user messages (multi-turn)          | Mirrors some chain-of-thought patterns                                                                                                                              | Unnecessary for single-hop; complicates the `Generator` Protocol's call signature; multi-turn is a Sprint 2+ concern | M      |

**Recommendation: Approach B.** System prompt carries: role ("You are an enterprise knowledge assistant"), output instruction (answer in JSON with `answer` and `sources` fields), and the JSON schema. User turn carries: the numbered context block (`[1] doc_id: text...`) followed by the question. Abstention lives in two places: (1) Python short-circuit — if `Retriever.retrieve()` returns `[]`, return `AnswerWithSources(answer="I don't have enough information to answer this question.", sources=[])` immediately without an LLM call; (2) a fallback instruction in the system prompt for the case where retrieved context is present but insufficient.

---

### Decision 5 — Smoke Gate Scope

`make smoke` runs 10 questions and must return answers + sources. What does it assert?

| Approach                                                                                                   | Pros                                                                                                                                                       | Cons                                                                                                                                                        | Effort |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Non-empty answer + `len(sources) >= 1` per question (smoke == "doesn't crash and attributes something") | Smallest meaningful assertion; consistent with the Phase 2 smoke philosophy (`Recall@k > 0`); fast to implement; doesn't require `expected_doc_ids` lookup | Does not verify correctness; a stub generator would pass — but the smoke is a real LLM call, so "doesn't crash" is meaningful                               | S      |
| B. Non-empty answer + sources ⊆ `expected_doc_ids` for each question                                       | Validates attribution ground truth against the benchmark                                                                                                   | Requires loading 10 questions' `expected_doc_ids` from the dataset; `expected_doc_ids` in the stratified subset may overlap imperfectly with retrieved docs | S–M    |
| C. Full per-fact judging (answer quality scored against `answer_facts`)                                    | Most rigorous                                                                                                                                              | Out of scope — this is the Sprint 2 eval harness; pre-building it here is scope creep                                                                       | L      |

**Recommendation: Approach A (non-empty answer + ≥1 source per question).** The smoke gate's job is to verify the pipeline is wired end-to-end. Correctness verification is Sprint 2's job. Approach B's `expected_doc_ids` check is a step toward Sprint 2 but requires extra dataset loading logic that bloats Phase 3. The distinction is: smoke confirms "the system works," eval confirms "the system works correctly." Keep them separate.

---

### Decision 6 — CI Strategy for the Generator

How do we test the generation layer in `make verify` (offline, no API keys)?

| Approach                                                                                                                                   | Pros                                                                                                                                                                                    | Cons                                                                                                                                                          | Effort                      |
| ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| A. `StubGenerator` implementing `Generator` Protocol — returns deterministic `AnswerWithSources` with sources = retrieved doc_ids verbatim | Exact precedent from `StubEmbedder` (ADR-002); exercises the full pipeline wiring (`ContextAssembler` → prompt builder → generator → output model) in CI; no API key needed; no network | Does not test the real LLM prompt; catches wiring bugs only                                                                                                   | S                           |
| B. Skip generator tests in CI entirely; only real smoke (`make smoke`) tests generation                                                    | Simpler                                                                                                                                                                                 | Leaves the generation wiring untested in CI; a refactor that breaks `ContextAssembler` → `Generator` wiring would not surface until a manual `make smoke` run | S (code savings) / M (risk) |
| C. Record/replay (cassette) for real LLM calls in CI                                                                                       | Tests real prompt format without API costs in CI                                                                                                                                        | ADR-001 explicitly defers cassette/replay to Sprint 2; implementing it in Phase 3 pre-empts that decision                                                     | M                           |

**Recommendation: Approach A (`StubGenerator`).** This is the established pattern and there is no strong reason to deviate. The `StubGenerator` is a 10-line class: it accepts the assembled context + question and returns a pre-baked `AnswerWithSources(answer="stub", sources=retrieved_doc_ids)`. The pipeline-contract test (`tests/generation/test_generation_contract.py`) asserts that, given a mock retriever returning two doc_ids and a stub LanceDB store, the CLI produces an `AnswerWithSources` with those doc_ids in `sources`. This catches all wiring bugs without an API key.

---

### Decision 7 — Smoke Gate Execution Model

Should `make smoke` require network/API keys? How does it relate to `make verify`?

| Approach                                                                                                                 | Pros                                                                                                                                   | Cons                                                                                                               | Effort |
| ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------ |
| A. Local-only, like `make retrieval-smoke` — excluded from `make verify`; requires `ANTHROPIC_API_KEY` and a built index | Consistent with the tiered model established in Phase 2; `make verify` stays offline and free; smoke is a real test of the live system | Developer must set an API key and run `make smoke` manually                                                        | S      |
| B. Include in CI with a secret-gated job (skips if `ANTHROPIC_API_KEY` not set)                                          | Validates generation in CI on PRs with secrets available                                                                               | CI complexity; cost per PR run (~10 questions × Haiku rate); non-free runs block the "CI is always free" invariant | M      |
| C. Mock the LLM in CI (cassette) and include in `make verify`                                                            | No cost in CI                                                                                                                          | Cassette pattern deferred to Sprint 2 (ADR-001 scope)                                                              | M      |

**Recommendation: Approach A.** `make smoke` is local-only, analogous to `make retrieval-smoke`. It is excluded from `make verify` via a `smoke` pytest marker (same pattern as `corpus` and `smoke` markers already in `pyproject.toml` / `Makefile`). The Makefile target documents the API key requirement. `make verify` remains offline and free. This is the most important invariant to preserve — do not let Phase 3 break it.

---

### Decision 8 — ADR-003 Scope and Numbering

`adrs_planned.md` reserves ADR-003 for observability tooling (Phase 7). Generation decisions are not covered by any planned ADR. Should Phase 3 write an ADR?

| Approach                                                                                                                                    | Pros                                                                                                                                           | Cons                                                                                                                                                                                    | Effort                               |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| A. Write ADR-003-generation now (Generator seam + attribution format), renumber observability to ADR-004, shift LLM matrix to ADR-005       | ADR captures the live generation+attribution decision at decision time (anti-rot principle); clean number sequence                             | Renumbering cascades — ADR-003 and ADR-004 in `adrs_planned.md` shift; any doc referencing them by number is stale                                                                      | S                                    |
| B. Record decisions in DESIGN.md only; defer all generation ADRs                                                                            | Zero ADR overhead; decisions are still captured                                                                                                | Generation seam and attribution format are architectural choices of the same weight as ADR-002; only the DESIGN doc (a private SDD artifact) captures them — not the public `docs/adr/` | S (code) / M (portfolio signal loss) |
| C. Insert ADR-003 as "generation architecture" and keep observability as ADR-004, LLM matrix as ADR-005 (shift by one, accept the renumber) | Clean; preserves the anti-rot principle; public docs capture all three foundational substrate decisions (retrieval, generation, observability) | One-time renumber of planned ADRs (low cost)                                                                                                                                            | S                                    |

**Recommendation: Approach C.** Write ADR-003 for generation architecture (Generator seam, attribution format, abstention behavior) in Phase 3. Renumber the planned observability ADR to ADR-004, LLM matrix to ADR-005. The renumber risk is low — `adrs_planned.md` is private and no public doc references "ADR-003" by name yet (ADR-002 was the first shipped ADR). The generation seam is exactly the kind of decision an ADR exists to capture: it has a named future swap (ADR-005 LLM matrix), a deliberate format choice (structured output), and a rationale that future maintainers need. Recording it only in a private SDD DESIGN file is a portfolio anti-pattern.

---

## Recommended Approach

The recommended design is a minimal, four-component generation layer:

1. **`VectorStore` Protocol extension** — add `fetch_chunks_by_doc_ids(doc_ids: list[str]) -> list[Chunk]` to the existing Protocol in `retrieval/interfaces.py`. `LanceDBStore` implements it as a LanceDB table scan filtered by `doc_id IN (...)`. This is a narrow, justified extension.

2. **`ContextAssembler`** — standalone class in `generation/context.py`. Takes `list[(doc_id, fused_score)]` from the retriever + a `VectorStore`, calls `fetch_chunks_by_doc_ids`, deduplicates to top-1 chunk per doc_id (preserving rank), and returns `list[Chunk]` ordered by fused_score descending. This keeps `Retriever` pure.

3. **`Generator` Protocol + `AnthropicGenerator`** — Protocol in `generation/interfaces.py` with a single `generate(context_chunks, question) -> AnswerWithSources` method. `AnthropicGenerator` uses `claude-haiku-4-5` (configurable via env var `RAG_MODEL`), system prompt with role + JSON schema instruction, user turn with numbered context block + question, Python short-circuit for empty retriever output. `AnswerWithSources` is a Pydantic model with `answer: str` and `sources: list[str]`.

4. **`rag-ask` CLI** — entry-point in `pyproject.toml`; wires `HybridRetriever` → `ContextAssembler` → `AnthropicGenerator` → print JSON output. `make smoke` runs it on 10 hardcoded questions from the benchmark and asserts non-empty answer + `len(sources) >= 1` per question.

**CI pattern:** `StubGenerator` (returns deterministic `AnswerWithSources` with `sources = retrieved_doc_ids`) in a `tests/generation/test_generation_contract.py` pipeline-contract test. `make smoke` marker excludes it from `make verify`.

**ADR:** Write ADR-003 capturing Generator seam, attribution format (structured JSON), and abstention behavior.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                       |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Must     | `VectorStore` Protocol extended with `fetch_chunks_by_doc_ids(doc_ids: list[str]) -> list[Chunk]`                                          |
| Must     | `LanceDBStore.fetch_chunks_by_doc_ids` implementation                                                                                      |
| Must     | `ContextAssembler` in `generation/context.py` — translates `(doc_id, score)` pairs → ordered `list[Chunk]`                                 |
| Must     | `Generator` Protocol in `generation/interfaces.py` with `generate(context_chunks, question) -> AnswerWithSources`                          |
| Must     | `AnswerWithSources` Pydantic model with `answer: str` and `sources: list[str]`                                                             |
| Must     | `AnthropicGenerator` implementing `Generator` — `claude-haiku-4-5` default, structured JSON output                                         |
| Must     | Python short-circuit abstention: `Retriever.retrieve() == []` → return fixed "no information" answer with `sources=[]` without an LLM call |
| Must     | System prompt carrying role + JSON output instruction + schema; user turn carrying numbered context block + question                       |
| Must     | `rag-ask` CLI entry-point wiring the full pipeline end-to-end                                                                              |
| Must     | `make smoke` Makefile target running 10 questions, marked `smoke`, excluded from `make verify`                                             |
| Must     | Smoke gate assertions: non-empty `answer` + `len(sources) >= 1` per question                                                               |
| Must     | `StubGenerator` for CI pipeline-contract test in `tests/generation/test_generation_contract.py`                                            |
| Must     | ADR-003 written: Generator seam, attribution format, abstention behavior                                                                   |
| Should   | `make verify` continues to pass offline (ruff + lint + unit tests excluding `smoke`)                                                       |
| Should   | `RAG_MODEL` env var to override the default Anthropic model (forward hook for ADR-005)                                                     |
| Should   | Logging the number of context chunks assembled and the doc_ids cited per question                                                          |
| Should   | Graceful error if `ANTHROPIC_API_KEY` is unset at `make smoke` time (clear error message, not a stack trace)                               |
| Could    | `MAX_CONTEXT_CHUNKS` config to cap context length (default 5)                                                                              |
| Could    | Top-level `docs/adr/README.md` update noting ADR-003 added and observability/LLM matrix renumbered                                         |
| Won't    | Multi-hop agent variants — explicitly deferred to Sprint 1 stretch at earliest; more likely Sprint 2+                                      |
| Won't    | Reranker integration in the generation pipeline — Phase 2 left a `reranker=None` hook; Phase 3 does not activate it                        |
| Won't    | Cost and latency tracking per question — Sprint 3 (observability layer)                                                                    |
| Won't    | Structured eval of answer quality (per-fact judge, faithfulness) — Sprint 2 (eval harness)                                                 |
| Won't    | Prompt template library or template engine — conventional single prompt is sufficient; no Jinja2 or LangChain prompts                      |
| Won't    | Multi-model comparison at smoke time — one default model; ADR-005 owns this                                                                |
| Won't    | Streaming generation — not needed for a CLI smoke gate; Sprint 4+ polish                                                                   |
| Won't    | Tool use / function calling for retrieval — the retriever is a Python call, not an LLM tool                                                |
| Won't    | Guardrails, content filtering, PII detection — out of scope for a benchmark substrate                                                      |
| Won't    | Cassette/replay for CI — ADR-001 deferred to Sprint 2; do not pre-build it in Phase 3                                                      |
| Won't    | OpenAI or Ollama generator implementations — ADR-005 owns provider diversity; Phase 3 wires one provider                                   |

---

## Open Questions

1. **`fetch_chunks_by_doc_ids` return semantics.** When a `doc_id` maps to multiple chunks (the corpus has 3–5 chunks per document), should the assembler return all chunks for that doc_id (potentially large context) or only the top-1 chunk by fused_score? The choice affects prompt length and attribution quality — `/define` should pick one and specify the default cap.

2. **Smoke question selection.** Which 10 questions from the EnterpriseRAG-Bench `questions` split will be hardcoded in `make smoke`? They must be selected so that their `expected_doc_ids` are plausibly within the stratified corpus subset (same constraint as the Phase 2 retrieval smoke). Should this selection happen during `/implement` (same as Phase 2's pattern) or be specified in `/define`?

3. **`AnswerWithSources` JSON extraction reliability.** Anthropic's JSON mode reliability on `claude-haiku-4-5` requires the JSON schema to be explicit in the system prompt. Should the implementation use raw JSON instruction in the system prompt, or use Anthropic's `tool_use` API (which enforces schema via the API layer)? The tool_use path is more reliable but more code; the raw JSON instruction path is simpler but fragile. `/define` must pick one.

4. **ADR-003 renumbering downstream impact.** Renumbering the planned observability ADR from ADR-003 to ADR-004 (and LLM matrix from ADR-004 to ADR-005) is recommended. Before `/define` commits to this, confirm there are no other files in `docs/` or `.claude/` that reference "ADR-003" by number — this is a one-time grep during implementation setup, not a blocker.

5. **`make smoke` question hardcoding location.** Should the 10 smoke questions be defined inline in the pytest file (like Phase 2's `SMOKE_QUESTIONS` list) or in a separate `tests/generation/smoke_questions.json` fixture file? The inline list is simpler; the JSON fixture is more maintainable if the question set grows. `/define` should settle this before `/design`.

6. **Context chunk count cap.** The `ContextAssembler` needs a `max_chunks` parameter to avoid blowing the model's context window or incurring excessive token costs. What is the default? Top-5 chunks (≈5 × 256 tokens ≈ 1280 tokens of context, well within Haiku's 200K context window) is a reasonable default, but `/define` should make it explicit and specify whether it is configurable at runtime.

---

## Next Step

→ `/define sprint-1/phase-3-generation`

---

## Decisions (2026-05-20)

User-confirmed answers to the 8 decisions and 6 open questions. These are
**confirmed inputs** for `/define` — do not re-open.

### Decisions 1–8

| #   | Pick                                             | Resolution                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **C+B**                                          | Hybrid: standalone `ContextAssembler` + add `fetch_chunks_by_doc_ids(doc_ids: list[str]) -> list[Chunk]` to the `VectorStore` Protocol. Assembler stays pure of LanceDB; `VectorStore` widens by exactly one read method (justified by use, not "in case"). `Retriever` Protocol unchanged.                                                                                                                                                                                        |
| 2   | **OpenAI `gpt-5-nano-2025-08-07`, parametrized** | One `OpenAIGenerator` using `gpt-5-nano-2025-08-07` as the default; model name parametrized via env var `RAG_GEN_MODEL` (separate from any future judge model var). Diverges from the spec's "OpenAI=judge / Anthropic=generator" split — chosen for cost. **Flag for Sprint 2:** ADR-005 must revisit judge/generator family independence; using the same OpenAI family for both reduces eval independence and may inflate measured faithfulness. Record this concern in ADR-003. |
| 3   | **C**                                            | Structured JSON output. `AnswerWithSources` Pydantic model with `answer: str` and `sources: list[str]`. Use OpenAI's native structured outputs (`response_format={"type": "json_schema", "json_schema": ...}`) for schema-validated extraction — no string parsing.                                                                                                                                                                                                                |
| 4   | **B**                                            | System prompt = role + JSON output instruction + schema. User turn = numbered context block (`[1] doc_id: text...`) + question. Abstention: Python short-circuit when `Retriever.retrieve() == []` returns fixed "no information" answer with `sources=[]` and no LLM call.                                                                                                                                                                                                        |
| 5   | **A**                                            | Smoke assertions per question: non-empty `answer` (string) + `len(sources) >= 1`. No `expected_doc_ids` check (Sprint 2 territory).                                                                                                                                                                                                                                                                                                                                                |
| 6   | **A**                                            | `StubGenerator` implementing `Generator` Protocol; returns deterministic `AnswerWithSources(answer="stub", sources=retrieved_doc_ids)`. Pipeline-contract test in `tests/generation/test_generation_contract.py`, runs offline in `make verify`.                                                                                                                                                                                                                                   |
| 7   | **A**                                            | `make smoke` is local-only (requires `OPENAI_API_KEY` + a built index). Marked `smoke` in pytest, excluded from `make verify`. Mirrors `make retrieval-smoke`.                                                                                                                                                                                                                                                                                                                     |
| 8   | **C**                                            | Write ADR-003 (generation architecture: Generator seam, attribution format, abstention). Renumber planned: observability → ADR-004, LLM matrix → ADR-005. One-time grep during `/implement` confirms no stale "ADR-003" references (see OQ-4).                                                                                                                                                                                                                                     |

### Open Questions — resolved (tech-debt-cautious)

1. **`fetch_chunks_by_doc_ids` return semantics.** The store-level method returns
   **all chunks** for the requested `doc_ids` (predictable, single SQL-style
   read). The `ContextAssembler` is responsible for the policy: dedup to **top-1
   chunk per `doc_id`** (first chunk by deterministic `chunk_id` ordering),
   preserving the doc-level fused-rank order from the retriever. This keeps the
   Protocol mechanical and the policy in one place — easy to evolve in Sprint 2.

2. **Smoke question selection timing.** Selected during **`/implement`** (first
   step: stream the dataset `questions` config at the pinned SHA, pick 10 with
   verified `expected_doc_ids` plausibly inside the stratified subset). Mirrors
   Phase 2's RQ-2 resolution — no new pattern.

3. **JSON extraction.** Use **OpenAI structured outputs**
   (`response_format={"type": "json_schema", "json_schema": <AnswerWithSources schema>, "strict": true}`).
   Schema-validated by the API; no regex parsing, no JSON-mode prompt
   instruction needed. `gpt-5-nano-2025-08-07` supports it. This is the
   tech-debt-cautious path — fragile prompt-side JSON instructions are rejected.

4. **ADR-003 renumber grep.** Run once during `/implement` setup:
   `rg -i "ADR-003|ADR-004"` across `docs/`, `.claude/`, and the Carreira
   `portfolio/enterprise_rag_ops/`. Not a blocker; update any stale references
   in the same commit that adds ADR-003.

5. **Smoke questions location.** Inline `SMOKE_QUESTIONS` constant in the
   pytest file (`tests/generation/test_generation_smoke.py`). Matches Phase 2's
   pattern. If the list grows beyond ~20, revisit by extracting to JSON — not
   now.

6. **Context chunk count cap.** Default `MAX_CONTEXT_CHUNKS = 5`. Configurable
   **at `ContextAssembler` construction time** (`ContextAssembler(max_chunks=5)`).
   No env var — avoids env-var sprawl for a substrate phase. The CLI uses the
   default; future Sprint 2 sweeps can override at the call site.

### Carry-forward flags

- **Same-family judge/generator (Decision 2 trade-off).** Record in ADR-003 as a
  known limitation; ADR-005 must address it.
- **Stranger-test boundary (Phase 2 lesson).** Watch ADR-003 and DESIGN.md for
  personal-context leaks (budget, portfolio framing). Review during `/review`.
- **`load_retriever` re-chunking drift (Phase 2 gotcha).** Phase 3 inherits the
  same risk via `pipeline.load_retriever()`. If `/implement` touches that path,
  consider the harden-the-drift fix opportunistically; otherwise leave for
  Sprint 2.
