# DEFINE: sprint-1/phase-3-generation — Generation Layer with Source Attribution

**Sprint/Phase:** sprint-1/phase-3-generation | **Date:** 2026-05-20

## Resolved Open Questions

The BRAINSTORM contains a **Decisions (2026-05-20)** block pinning all 8 design
decisions and resolving all 6 open questions. They are recorded here so `/design` and
`/implement` treat them as fixed — do **not** re-open them.

- **RQ-1 — Context assembly (Decision 1, C+B).** Standalone `ContextAssembler` plus a
  minimal extension to the `VectorStore` Protocol:
  `fetch_chunks_by_doc_ids(doc_ids: list[str]) -> list[Chunk]`. The assembler stays
  pure of LanceDB; `VectorStore` widens by exactly one read method, justified by use.
  `Retriever` Protocol is unchanged.
- **RQ-2 — LLM provider (Decision 2).** Single `OpenAIGenerator` behind a new
  `Generator` Protocol. Default model `gpt-5-nano-2025-08-07`; override via env var
  `RAG_GEN_MODEL` (separate from any future judge-model var). This diverges from the
  spec's OpenAI=judge / Anthropic=generator split — chosen for cost. **Carry-forward
  flag for Sprint 2 / ADR-005:** same-family judge/generator reduces eval
  independence; ADR-003 must record this concern.
- **RQ-3 — Attribution format (Decision 3, C).** Structured JSON output via OpenAI's
  native structured outputs (`response_format={"type": "json_schema", "json_schema": ..., "strict": true}`).
  `AnswerWithSources` Pydantic model with `answer: str` and `sources: list[str]`. No
  regex parsing; schema-validated at the API layer.
- **RQ-4 — Prompt structure (Decision 4, B).** System prompt = role + JSON output
  instruction + schema. User turn = numbered context block (`[1] doc_id: text...`)
  followed by the question. Abstention is a Python short-circuit: when
  `Retriever.retrieve() == []`, return a fixed "no information" `AnswerWithSources`
  with `sources=[]` and **no LLM call**.
- **RQ-5 — Smoke gate scope (Decision 5, A).** Per question: non-empty `answer`
  string + `len(sources) >= 1`. No `expected_doc_ids` check (Sprint 2 territory). Run
  on 10 questions.
  - **Revised during `/implement` (2026-05-21).** Running the live gate revealed
    that the default 100-docs/source subset contains the gold documents for only
    3 of the 500 benchmark questions — and of those, only some have an answer
    self-contained in the single top-ranked chunk we feed. For the rest the
    generator faithfully abstains with `sources=[]` (correct behavior, the
    project's whole thesis). A flat `len(sources) >= 1` on every question would
    only pass if the model hallucinated citations. The assertion is now two-tier:
    **all 10** assert a valid, non-empty `answer` (wiring); the **attribution
    subset** (gold doc in subset AND answer in the top chunk — `qst_0104`,
    `qst_0258`) additionally asserts `len(sources) >= 1`. See AC-13.
- **RQ-6 — CI strategy (Decision 6, A).** `StubGenerator` implementing the
  `Generator` Protocol; returns deterministic `AnswerWithSources(answer="stub", sources=retrieved_doc_ids)`.
  Pipeline-contract test in `tests/generation/test_generation_contract.py` runs
  offline under `make verify`.
- **RQ-7 — Smoke execution model (Decision 7, A).** `make smoke` is local-only
  (requires `OPENAI_API_KEY` and a built index). Marked `smoke` in pytest, excluded
  from `make verify`. Mirrors `make retrieval-smoke`.
- **RQ-8 — ADR-003 scope and numbering (Decision 8, C).** Write ADR-003 covering
  Generator seam + attribution format + abstention behavior + the same-family
  judge/generator carry-forward flag. Renumber planned: observability → ADR-004,
  LLM matrix → ADR-005. A one-time `rg -i "ADR-003|ADR-004"` across `docs/`,
  `.claude/`, and the Carreira `portfolio/enterprise_rag_ops/` runs during
  `/implement` setup.
- **RQ-9 — `fetch_chunks_by_doc_ids` return semantics (OQ-1).** Store-level method
  returns **all chunks** for the requested `doc_ids` (predictable, single SQL-style
  read). The `ContextAssembler` is the policy owner: dedup to **top-1 chunk per
  `doc_id`** (first chunk by deterministic `chunk_id` ordering), preserving the
  doc-level fused-rank order from the retriever.
- **RQ-10 — Smoke-question selection timing (OQ-2).** Selected during `/implement`
  (first step: stream the dataset `questions` config at the pinned SHA, pick 10 with
  verified `expected_doc_ids` plausibly inside the stratified subset). Mirrors
  Phase 2's RQ-2 resolution.
- **RQ-11 — JSON extraction mechanism (OQ-3).** OpenAI structured outputs
  (`response_format` + JSON schema, `strict: true`). Schema-validated by the API; no
  prompt-side JSON instruction fragility.
- **RQ-12 — ADR renumber grep (OQ-4).** Run once during `/implement` setup:
  `rg -i "ADR-003|ADR-004"` across `docs/`, `.claude/`, and the Carreira
  `portfolio/enterprise_rag_ops/`. Not a blocker; update any stale references in the
  same commit that adds ADR-003.
- **RQ-13 — Smoke-questions storage location (OQ-5).** Inline `SMOKE_QUESTIONS`
  constant in `tests/generation/test_generation_smoke.py`. Matches Phase 2's pattern;
  revisit (extract to JSON) only if the list grows beyond ~20.
- **RQ-14 — Context chunk cap (OQ-6).** Default `MAX_CONTEXT_CHUNKS = 5`, configurable
  at `ContextAssembler` construction time (`ContextAssembler(max_chunks=5)`). No env
  var — avoids env-var sprawl for a substrate phase. CLI uses the default; Sprint 2
  sweeps can override at the call site.

These were resolved by the user on 2026-05-20 directly in the BRAINSTORM. RQ-1
through RQ-14 are **confirmed inputs, not unconfirmed assumptions** — no orchestrator
re-confirmation is needed before `/design`.

## Requirements

### Functional

- **FR-1 (`AnswerWithSources` model)** — A Pydantic model `AnswerWithSources` exists
  with exactly two fields: `answer: str` and `sources: list[str]`. The model is the
  single canonical schema used by the `Generator` Protocol return type, the OpenAI
  structured-output JSON schema, and the `rag-ask` CLI output.
- **FR-2 (`Generator` Protocol)** — A `Generator` Protocol exists in
  `generation/interfaces.py` with a single method
  `generate(context_chunks: list[Chunk], question: str) -> AnswerWithSources`. The
  Protocol is the named seam Phase 4/ADR-005 will swap behind.
- **FR-3 (`OpenAIGenerator`)** — An `OpenAIGenerator` class implements `Generator`.
  Default model is `gpt-5-nano-2025-08-07`; override via env var `RAG_GEN_MODEL`.
  Uses OpenAI's structured outputs API with the `AnswerWithSources` JSON schema and
  `strict: true`. Temperature is 0.
- **FR-4 (`VectorStore` Protocol extension)** — The `VectorStore` Protocol in
  `retrieval/interfaces.py` gains exactly one method:
  `fetch_chunks_by_doc_ids(doc_ids: list[str]) -> list[Chunk]`. Existing methods
  (`add`, `dense_search`) are unchanged.
- **FR-5 (`LanceDBStore.fetch_chunks_by_doc_ids`)** — `LanceDBStore` implements
  `fetch_chunks_by_doc_ids` as a LanceDB table read filtered by `doc_id IN (...)`,
  returning **all** chunks for the requested `doc_ids` (no policy applied at the
  store layer).
- **FR-6 (`ContextAssembler`)** — A `ContextAssembler` class in
  `generation/context.py` accepts `(store: VectorStore, max_chunks: int = 5)` at
  construction. Its method
  `assemble(retrieved: list[tuple[str, float]]) -> list[Chunk]` calls
  `store.fetch_chunks_by_doc_ids(...)`, deduplicates to **top-1 chunk per `doc_id`**
  (first by deterministic `chunk_id` ordering), preserves the doc-level fused-rank
  order from the retriever, and truncates the output to `max_chunks`.
- **FR-7 (Prompt builder)** — A prompt builder produces two strings: a **system
  prompt** carrying role + JSON output instruction + the `AnswerWithSources` schema,
  and a **user prompt** carrying a numbered context block in the format
  `[1] doc_id: text\n[2] doc_id: text\n...` followed by the question. The builder is
  deterministic — same inputs yield byte-identical strings.
- **FR-8 (Abstention short-circuit)** — When `Retriever.retrieve(question)` returns
  `[]`, the pipeline returns
  `AnswerWithSources(answer="I don't have enough information to answer this question.", sources=[])`
  **without** calling the `Generator`. No LLM request is issued.
- **FR-9 (`rag-ask` CLI)** — A `rag-ask` console-script entry-point in
  `pyproject.toml` wires `HybridRetriever` → `ContextAssembler` → `OpenAIGenerator`
  end-to-end. It accepts a question via argv (or stdin), prints the
  `AnswerWithSources` payload as JSON to stdout, and exits 0 on success.
- **FR-10 (`StubGenerator`)** — A `StubGenerator` implementing the `Generator`
  Protocol returns a deterministic
  `AnswerWithSources(answer="stub", sources=[chunk.doc_id for chunk in context_chunks])`.
  It is the CI-safe drop-in for `OpenAIGenerator` through the `Generator` seam — no
  API key, no network.
- **FR-11 (Pipeline-contract test)** — A pipeline-contract test in
  `tests/generation/test_generation_contract.py` runs under `make verify`. Using a
  fixture retriever (returning two `(doc_id, score)` pairs), a fixture store, the
  `ContextAssembler`, and the `StubGenerator`, it asserts the produced
  `AnswerWithSources` has `sources` equal to the retrieved `doc_id`s in fused-rank
  order. No network I/O; no API key.
- **FR-12 (`make smoke` target)** — A `make smoke` Makefile target invokes pytest
  with the `smoke` marker against `tests/generation/test_generation_smoke.py`. The
  target is **not** invoked by `make verify`; the `smoke` marker is excluded from
  the default test run.
- **FR-13 (Smoke gate assertions)** — `tests/generation/test_generation_smoke.py`
  defines an inline `SMOKE_QUESTIONS` constant (10 questions, selected during
  `/implement` per RQ-10), runs the full `rag-ask` pipeline against each, and
  asserts two tiers (revised per RQ-5): **every** question yields a valid,
  non-empty `answer`; the **attribution subset** (`expect_sources=True` — gold
  doc in subset AND answer self-contained in the top-ranked chunk fed to the LLM)
  additionally asserts `len(sources) >= 1`. The other questions may faithfully
  abstain (`sources=[]`).
- **FR-14 (ADR-003 + renumber)** — `docs/adr/` gains `ADR-003-generation.md`
  recording: Generator seam, attribution format (structured JSON via
  `AnswerWithSources`), abstention behavior, and the same-family judge/generator
  carry-forward flag for ADR-005. The Carreira `adrs_planned.md` is updated:
  observability → ADR-004, LLM matrix → ADR-005. The `rg -i "ADR-003|ADR-004"` grep
  (RQ-12) is completed and any stale references are updated in the same commit.

### Non-functional

- **NFR-1 (CI offline / no API key)** — `make verify` runs the pipeline-contract
  test with `StubGenerator` and performs no network I/O. No `OPENAI_API_KEY` is
  required for `make verify` to pass.
- **NFR-2 (Interface seam)** — The `Generator` Protocol is the named seam isolating
  LLM-provider specifics. The CI test uses `StubGenerator` through this seam, so the
  anticipated ADR-005 LLM-matrix swap is a localized change (one new file plus a
  one-line wiring change), not a rewrite.
- **NFR-3 (Dependency hygiene)** — `pyproject.toml` `dependencies` gains **exactly
  one** new entry, `openai`, version-bounded. No eval, observability, prompt-template,
  or agent libraries are added.
- **NFR-4 (Reproducibility)** — Temperature is fixed at `0` in `OpenAIGenerator`.
  Prompt construction is deterministic — given the same `(retrieved, question)`,
  the prompt builder produces byte-identical system and user strings. (LLM output
  is not asserted to be byte-stable; only the inputs are.)
- **NFR-5 (Observability)** — `OpenAIGenerator` and the `rag-ask` CLI log via the
  stdlib `logging` module at INFO level: the retrieved `doc_id`s (post-assembler)
  per question, and the final cited `sources` per question. No third-party
  telemetry library is introduced.
- **NFR-6 (Conventions)** — New code lives under
  `src/enterprise_rag_ops/generation/` with mirrored tests under `tests/generation/`.
  `make verify` (ruff format + lint + pytest excluding `smoke`) passes.
- **NFR-7 (Graceful API-key error)** — If `OPENAI_API_KEY` is unset when `make smoke`
  is invoked, the failure is a clear human-readable message naming the missing env
  var, not a Python stack trace from the OpenAI SDK.
- **NFR-8 (Cost cap, sanity bound)** — A full `make smoke` run at default settings
  (10 questions, `MAX_CONTEXT_CHUNKS = 5`, `gpt-5-nano-2025-08-07`, temperature 0)
  is expected to cost well under $0.05. This is a sanity bound, not an enforced
  check — Phase 3 does not implement cost tracking (Sprint 3 owns observability).

## Acceptance Criteria

1. `AnswerWithSources` is a Pydantic model with exactly two fields
   (`answer: str`, `sources: list[str]`); constructing it with valid data succeeds;
   missing or wrong-typed fields raise `ValidationError`.
2. A `Generator` Protocol exists in `src/enterprise_rag_ops/generation/interfaces.py`
   declaring
   `generate(context_chunks: list[Chunk], question: str) -> AnswerWithSources`.
3. `OpenAIGenerator` implements `Generator`, defaults to model
   `gpt-5-nano-2025-08-07`, honors `RAG_GEN_MODEL` env-var override, uses
   `response_format={"type": "json_schema", ..., "strict": true}` with the
   `AnswerWithSources` schema, and sets temperature to 0.
4. The `VectorStore` Protocol gains `fetch_chunks_by_doc_ids(doc_ids) -> list[Chunk]`;
   `add` and `dense_search` remain unchanged.
5. `LanceDBStore.fetch_chunks_by_doc_ids([d1, d2])` returns every chunk whose
   `doc_id` is in the requested set, with no filtering or deduplication at the store
   layer.
6. `ContextAssembler(store, max_chunks=5).assemble([(d1, s1), (d2, s2), ...])`
   returns a `list[Chunk]` of length at most 5, contains exactly one chunk per
   distinct `doc_id`, preserves the order of `doc_id`s as they appear in the input,
   and selects the chunk with the lexicographically smallest `chunk_id` per
   `doc_id`.
7. The prompt builder produces a system prompt that includes the role string and the
   `AnswerWithSources` JSON schema, and a user prompt of the form
   `[1] {doc_id}: {text}\n[2] {doc_id}: {text}\n...\n\n{question}`; identical inputs
   produce byte-identical outputs across two invocations.
8. When `Retriever.retrieve(question)` returns `[]`, the pipeline returns
   `AnswerWithSources(answer="I don't have enough information to answer this question.", sources=[])`
   and no call is made to `OpenAIGenerator.generate` (verified via spy or stub).
9. `pyproject.toml` declares a `rag-ask` console-script entry-point that, given a
   question argument and a built index, prints a single JSON object matching the
   `AnswerWithSources` schema to stdout and exits 0.
10. `StubGenerator` implements `Generator` and returns
    `AnswerWithSources(answer="stub", sources=[c.doc_id for c in context_chunks])`
    deterministically.
11. `tests/generation/test_generation_contract.py` runs under `make verify` with no
    network access and no `OPENAI_API_KEY`, asserts the full pipeline (fixture
    retriever → fixture store → `ContextAssembler` → `StubGenerator`) yields an
    `AnswerWithSources` whose `sources` equal the retrieved `doc_id`s in fused-rank
    order.
12. `make smoke` runs `pytest -m smoke tests/generation/`; it is **not** triggered
    by `make verify`; pytest is configured so the `smoke` marker is excluded from
    the default test run.
13. With `OPENAI_API_KEY` set and a built index present, `make smoke` runs the 10
    inline `SMOKE_QUESTIONS` end-to-end. For **every** question it asserts a valid,
    non-empty `answer` (`result.answer != ""`). For the **attribution subset**
    (`expect_sources=True` — gold doc in subset AND answer self-contained in the
    top-ranked chunk) it additionally asserts `len(result.sources) >= 1`. The
    remaining questions may return `sources=[]` (faithful abstention — gold doc
    absent, or the answer spans chunks beyond the top-1 we feed), which is correct,
    not a failure.
14. With `OPENAI_API_KEY` unset, `make smoke` exits non-zero with a single clear
    error line naming the missing env var, **not** a Python stack trace from the
    OpenAI SDK.
15. `docs/adr/ADR-003-generation.md` exists and records the Generator seam,
    attribution format, abstention behavior, and the same-family judge/generator
    carry-forward flag for ADR-005; the Carreira `adrs_planned.md` is updated so
    observability is ADR-004 and the LLM matrix is ADR-005; the `rg -i "ADR-003|ADR-004"`
    grep is recorded as completed with any stale references updated in the same
    commit.
16. `pyproject.toml` `dependencies` gains exactly one new entry — `openai`,
    version-bounded — and no eval, observability, prompt-template, or agent
    libraries are added.
17. New code is under `src/enterprise_rag_ops/generation/` with mirrored tests under
    `tests/generation/`, and `make verify` (ruff format + lint + pytest excluding
    `smoke`) passes.
18. `OpenAIGenerator` and the `rag-ask` CLI emit stdlib `logging` INFO records
    containing the post-assembler `doc_id`s and the final `sources` per question;
    a unit test captures the log records and asserts both fields are present.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                                                                         |
| ----------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit: Phase 2 returns `(doc_id, score)` only; Phase 3 must close the loop with chunk fetch + LLM call + cited answer. Sprint 2 (eval harness) is the consumer; abstention/attribution choices set its eval surface.           |
| Users       | 2     | Consumers are Sprint 2's eval harness (named) and the maintainer running `make smoke`. Substrate phase — no external end user; workflow-impact dimension is inherently thin (same logic as Phase 2's DEFINE).                                |
| Success     | 3     | 18 numbered, falsifiable acceptance criteria, each with a concrete pass/fail check covering every FR, the smoke gate, the make-target behavior, ADR-003, and dependency addition.                                                            |
| Scope       | 3     | Full MoSCoW in BRAINSTORM with an explicit 10-item Won't list (multi-hop, reranker activation, cost/latency, eval, prompt template lib, multi-model smoke, streaming, tool use, guardrails, cassette/replay).                                |
| Constraints | 3     | CI-offline invariant, named seams (`Generator`, `VectorStore` extension), dependency hygiene (one new dep), reproducibility (temperature 0, deterministic prompt), observability (stdlib logging), graceful API-key error all named as NFRs. |

**Total: 14/15 — PASS (≥12).** Users scored 2: substrate phase whose "user" is the
downstream Sprint 2 eval harness plus the maintainer, so the workflow-impact
dimension is inherently thin — acceptable, not a blocker (consistent with Phase 1
and Phase 2 DEFINEs).

## Infrastructure Readiness

| Dependency                                | KB domain       | Specialist | Status                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------- | --------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `HybridRetriever` + `(doc_id, score)` API | `rag-retrieval` | none       | Ready — Phase 2 merged (commit `0946263`); `Retriever` Protocol is the SSoT for the upstream contract. ADR-002 documents the seam.                                                                                                                                                                                                    |
| `VectorStore` Protocol (Phase 2)          | `rag-retrieval` | none       | Ready — exists in `retrieval/interfaces.py`. Phase 3 extends it by one method (`fetch_chunks_by_doc_ids`) per RQ-1; narrow, justified extension.                                                                                                                                                                                      |
| `LanceDBStore` (Phase 2)                  | `rag-retrieval` | none       | Ready — Phase 3 adds the `fetch_chunks_by_doc_ids` implementation; LanceDB table scan filtered by `doc_id IN (...)` is straightforward.                                                                                                                                                                                               |
| `openai` Python SDK                       | none needed     | none       | Ready — well-documented public SDK; structured outputs (`response_format` + JSON schema, `strict: true`) is the supported path. New dep (NFR-3).                                                                                                                                                                                      |
| `gpt-5-nano-2025-08-07` model access      | none needed     | none       | Ready (local) — requires `OPENAI_API_KEY` for `make smoke`; CI uses `StubGenerator` (NFR-1).                                                                                                                                                                                                                                          |
| `Chunk` dataclass (Phase 2)               | `rag-retrieval` | none       | Ready — defined in Phase 2 with `chunk_id`, `doc_id`, `text`. Reused unchanged.                                                                                                                                                                                                                                                       |
| HF dataset `questions` config             | none needed     | none       | Ready — same pinned SHA as Phase 1/2; the 10 smoke questions are picked during `/implement` via streamed inspection (RQ-10, mirrors Phase 2 RQ-2).                                                                                                                                                                                    |
| `pytest` markers (`smoke`)                | none needed     | none       | Ready — the `smoke` marker pattern is already established by Phase 2's `make retrieval-smoke`. Phase 3 reuses the marker config in `pyproject.toml`.                                                                                                                                                                                  |
| `rag-generation` KB domain                | (none yet)      | none       | **Gap, non-blocking.** No `rag-generation` KB exists. Recommend `/new-kb rag-generation` as a **post-Phase 3** action — mirrors Phase 2's plan to refocus `rag-retrieval` after ADR-002. Phase 3 does not need it to ship; OpenAI SDK + the BRAINSTORM/DEFINE artifacts are sufficient grounding for `/implement`.                    |
| Specialist agent for generation           | n/a             | none       | Not required. Conventional single-turn prompt + structured output is a small, well-bounded implementation; no repeated specialist context-loading is anticipated. Revisit only if `/implement` surfaces repeated generation-specific friction (would be a post-phase `**Harness suggestion:**` for `/new-agent generation-engineer`). |

No `/new-kb` or `/new-agent` is blocking Phase 3. The two non-blocking
recommendations (`/new-kb rag-generation` post-phase, no specialist agent) are
logged so the orchestrator can decide whether to surface them after `/review`.

No new gaps were identified beyond those covered by the BRAINSTORM's Decisions and
Open Questions — all ambiguity has a confirmed input.

## Next Step

→ `/design sprint-1/phase-3-generation`
