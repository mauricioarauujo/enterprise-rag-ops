# DEFINE: sprint-6/phase-19-full-trace-hydration — Re-run + Hydrate the Full Trace (close Sprint 6)

**Sprint/Phase:** sprint-6/phase-19-full-trace-hydration | **Date:** 2026-06-03
**Approach:** **Option A — full-fidelity bronze** (ratified by the user this session over the
BRAINSTORM's lean Approach B / hybrid C). The bronze writer captures the **raw API request**
(messages + sampling params) **and the raw provider response** (serialized to a JSON-able dict),
for both the generation and judge calls — not derived objects. Rationale the user accepted:
(1) Approach B's derived-objects bronze would **drift from ADR-0010**, whose decision is the full
raw payload; (2) derived bronze loses the raw-response richness (`usage`, `finish_reason`,
`logprobs`, `refusal`, `system_fingerprint`) → a future feature would still force a re-run;
(3) the raw capture (including the request `messages`) is the **substrate for a future
resumable/cached eval sweep** — a separate backlog feature whose cache index is derivable only
if the raw request is archived now. Option A is therefore the lowest-architectural-debt choice
faithful to ADR-0010, at the cost of **per-provider response serialization** (the one real risk).

**Crisp scope call (the three pieces, with A locked).** Phase 19 ships **(1) the bronze writer**
(`eval/bronze.py`) built to the ADR-0010 contract _plus_ the Option-A seam change that surfaces the
raw request+response across the 3 generators + the judge + the 2 stubs (the off-Protocol
`*_with_stats` methods only — the `Generator`/`Judge` Protocols are **untouched**); **(2) the full
500×2 re-run** (both models, full question set — **ratified by the user this session** over a small
targeted run) to populate gold `per_fact`/`per_citation`, write bronze for **every** question×call,
and re-publish the baseline numbers in `results/`; **(3) verdict-reasoning hydration** onto the judge
span via the pure mapper. The full run is chosen deliberately: it makes bronze the **complete**
"never re-run again" archive (consistent with the Option-A rationale) rather than a ~10% sample, and
re-publishes real baseline numbers — at the cost of the sprint's one expensive/fragile operational
step (the eval-baseline recipe on the 8 GB Air). Generation-input-prompt hydration + a
`--enrich-from-bronze` flag are a **Won't** (deferred — bronze now captures the raw prompt, so a
later phase _could_ add the boundary read).
**Phase 18 already shipped the gold schema fields and the runner populating them** (`EvalRecord.per_fact`/
`per_citation` at `records.py:98-99`; `runner.py:243-244` already sets them from the in-memory
`verdict`) — so Phase 19 does **not** touch the schema and does **not** add the population line; it
consumes them.

## Problem

After Phases 17–18, the data contracts for a fully legible trace exist but the trace is **not yet
legible end-to-end**, and the ADR-0010 bronze obligation is **designed but unbuilt**:

- **The judge verdict reasoning is persisted in gold but never reaches a span.** `EvalRecord` now
  carries `per_fact` / `per_citation` (`records.py:98-99`), and the runner populates them
  (`runner.py:243-244`), but `build_span_attrs` builds `judge_attrs` (`attributes.py:64-74`) with
  **no `output.value`** — so a failed trace's judge span in Phoenix shows only token/latency/cost
  metadata, not _which fact was absent or which citation was unsupported_. Phase 17 set the precedent
  for the fix: `gen_attrs["output.value"] = record.answer` (`attributes.py:57-58`).
- **No gold record yet carries verdict lists.** The fields default `None` on every pre-Phase-18
  `results/*.jsonl`; nothing has been re-run since the schema landed, so even the mapper change above
  would render nothing until a sweep populates `per_fact`/`per_citation`.
- **The ADR-0010 bronze writer does not exist.** ADR-0010 fully specifies it (key scheme,
  overwrite-by-key idempotency, opt-in `persist_bronze` default-off, thread-safety + per-record flush,
  privacy, `run_id` sanitization, `.gitignore` entry) but explicitly defers the **build + wiring** to
  this phase ("designed here, BUILT + wired + gitignored in Phase 19", ADR-0010 §2). The raw API
  request + response it must archive are constructed inside each provider's `*_with_stats` and then
  **discarded** today (`openai_generator.py:80-91`, `anthropic_generator.py:77-98`,
  `gemini_generator.py:97-111`, `openai_judge.py:106-117`) — surfacing them is the Option-A seam change.

The decisive facts (all confirmed in source this session):

- **The Protocols do NOT declare `*_with_stats`.** `Generator.generate` (`generation/interfaces.py:21-31`)
  and `Judge.judge` (`eval/interfaces.py:23-36`) are the only Protocol methods; the `*_with_stats`
  variants are **concrete-class-only** (off-Protocol). So Option A's seam change touches only the four
  concrete implementations + the two stubs — **the Protocol contract is unchanged** (lower blast radius
  than a Protocol change). The plain `generate()`/`judge()` delegate to `*_with_stats` and discard the
  extra return (`openai_generator.py:58`, `openai_judge.py:65-67`, `gemini_generator.py:84`) — they keep
  working.
- **The provider response shapes genuinely diverge** — this is the real cost of Option A. OpenAI returns
  a `ChatCompletion` (`response.choices[0].message.content`, `response.usage`); Anthropic a `Message`
  (`response.content` blocks, `response.usage.input_tokens`); Gemini a `GenerateContentResponse`
  (`response.text`, `response.usage_metadata`). Each `*_with_stats` also builds a **different request
  shape** (`messages=[{system},{user}]` for OpenAI/judge; `system=` + `messages=[{user}]` + `tools` for
  Anthropic; `contents=` + `system_instruction` config for Gemini). Per-provider serialization to a
  JSON-able dict is required and is the `structured-output-per-provider` / `per-provider-token-accounting`
  KB territory.
- **`build_span_attrs` is the pure mapper** (`attributes.py:11`, no Phoenix/retrieval imports — must stay
  so). `judge_attrs` (`attributes.py:64-74`) currently lacks `output.value`; the always-on precedent is
  `gen_attrs` (`attributes.py:57-58`), and the cost-omit guard precedent is `attributes.py:73-74`.
- **The runner is concurrent + crash-safe.** `run_evaluation` uses a `ThreadPoolExecutor`
  (`runner.py:257-263`) plus `write_lock` (per-record `f.write(...) + f.flush()`, `runner.py:251-254`),
  `cost_lock` (`runner.py:124-125`), and `retrieve_lock` (`runner.py:129`, BGE-M3 not thread-safe). A
  bronze write must be thread-safe **and** must not deadlock or contend badly with these — the bronze
  payload is assembled and written **after** the `EvalRecord` is built (`runner.py:227-248`).
- **The verdict source for hydration.** `FactVerdict` = `{fact: str, verdict ∈ present|absent|contradicted}`,
  `CitationVerdict` = `{doc_id: str, verdict ∈ supported|unsupported}` (`eval/schema.py:24-57`), reached via
  `record.per_fact` / `record.per_citation`.
- **`.gitignore` does NOT cover `data/raw_eval/`.** It lists `data/raw/` (line 57), `data/processed/`
  (line 58), `results/*` (line 61) — `data/raw_eval/` ≠ `data/raw/`, so this phase adds the explicit line
  (ADR-0010 §2 obligation).
- **Eval-path tests use cassette/replay (ADR-0006), never a mocked LLM.** The seam change's raw-capture is
  tested via the **stubs** (bronze-writer unit tests) and, for the live providers, via **cassettes** — which
  may need re-recording to carry the new captured fields. The verdict-hydration test is **pure** (construct
  an `EvalRecord` in memory; no LLM).

## Users / Stakeholders

- **Maintainer debugging a failed trace in Phoenix** — the direct beneficiary and the sprint's whole point.
  After this phase, clicking one failed trace reads, in order, the **question** (Phase 17, chain span
  `input.value`), the **retrieved evidence content** (Phase 16, retriever span), the **answer** (Phase 17,
  generation span `output.value`), and the **judge's per-fact / per-citation verdict reasoning** (Phase 19,
  judge span `output.value`) — all in the Info tab, without leaving Phoenix or reading raw JSONL.
- **Maintainer running the re-run** — needs the bronze write to cost zero extra API calls beyond the sweep
  it already pays for (it serializes data already in memory at the call site), to be thread-safe under
  `--concurrency 8`, and to not perturb the crash-safe per-record JSONL flush.
- **A future resumable/cached-eval-sweep feature (backlog)** — the un-built downstream consumer the user
  named as Option A's justification. Its cache index (question_id + model + request-hash → cached response)
  is derivable **only** if bronze archives the raw request `messages`. This phase writes that substrate; it
  does **not** build the read-path, index, or invalidation (explicit Won't).
- **The 3 generators + 1 judge + 2 stubs (the seam-change surface)** — `OpenAIGenerator`,
  `AnthropicGenerator`, `GeminiGenerator`, `OpenAIJudge`, `StubGenerator`, `StubJudge`. Each `*_with_stats`
  must surface the raw request + response; the stubs must emit a minimal raw payload so offline tests work.
  The plain `generate()`/`judge()` Protocol methods must keep working (they discard the new value).
- **`build_span_attrs` (the pure mapper)** — gains the judge `output.value` mapping; must stay free of
  Phoenix/retrieval imports (Sprint-5 observability-coupling risk).
- **ADR-0010 (the ratified contract this phase BUILDS)** — its bronze design (key scheme, idempotency,
  opt-in, thread-safety, privacy, `.gitignore`) is implemented verbatim; the only open call ADR-0010 left to
  the build is `run_id` sanitization, resolved below (RQ-4).
- **`/update-kb observability` (`span-attribute-mapping` + `span-tree-shape`) and `/update-kb rag-eval`
  (`stats-capture-seam` for the seam change)** — deferred to **after** this phase per the Sprint-Wide
  Knowledge Plan (SPRINT.md), not a Phase-19 gap.

## Requirements

### Functional

- **FR-1 Seam change — surface the raw request + response from `*_with_stats` (Protocol untouched).**
  The four concrete implementations — `OpenAIGenerator.generate_with_stats`
  (`generation/openai_generator.py:61-114`), `AnthropicGenerator.generate_with_stats`,
  `GeminiGenerator.generate_with_stats`, and `OpenAIJudge.judge_with_stats`
  (`eval/openai_judge.py:70-154`) — must expose the **raw API request** (the messages/contents +
  sampling/model params actually sent) and the **raw provider response** (serialized to a JSON-able dict),
  in addition to their current return. The exposure mechanism (a third return value, a small typed
  `RawCall` record, or a side-channel) is a `/design` choice; the contract is that the bronze writer can
  obtain request+response for both call types. **The `Generator` / `Judge` Protocols
  (`generation/interfaces.py`, `eval/interfaces.py`) are NOT changed** — `*_with_stats` is off-Protocol.
  The plain `generate()` / `judge()` methods continue to delegate and discard the new value (FR-9).
- **FR-2 Per-provider raw-response serialization to a JSON-able dict.** Each provider's response object is
  serialized to a JSON-serializable dict capturing the raw richness (at minimum: the response body /
  message content, `usage`/token metadata, and provider-specific fields where present — `finish_reason`,
  `refusal`, `system_fingerprint` for OpenAI; stop_reason / content blocks for Anthropic;
  `usage_metadata` / candidates for Gemini). Serialization is **defensive** (missing attributes →
  omitted, never crash, mirroring the token-accounting reads at `gemini_generator.py:116-120`) and must
  not raise on a partial/odd response. This is the highest-cost item (3 divergent SDK shapes) and the one
  flagged risk.
- **FR-3 `eval/bronze.py` — new `BronzeWriter` matching the ADR-0010 contract.** A `BronzeWriter`
  whose `write(...)` persists one JSON file per call at key
  `data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json` (ADR-0010 §2). Behaviour:
  **overwrite-by-key idempotency** (same key → overwrite, matching the runner's `w`-mode JSONL semantics);
  **thread-safe** (its own lock; must coexist with the runner's `ThreadPoolExecutor` + `write_lock` +
  `retrieve_lock` + `cost_lock` without deadlock — distinct files per `question_id`/call mean low
  contention); **per-record flush** (`json.dump` + `f.flush()`); parent dir created on demand. The payload
  includes the raw request `messages`/contents (so the future cache index is derivable) + the serialized
  raw response (FR-2) for the call.
- **FR-4 `run_id` sanitization — reject path separators at `BronzeWriter` init.** Per ADR-0010 Consequences
  ("sanitize/validate `run_id` so it cannot contain path separators"), `BronzeWriter` **raises `ValueError`**
  at init if `run_id` contains `os.sep`, `/`, or `..` (RQ-4 — strict/loud over silent-replace). The runner
  generates timestamp slugs (no separators in practice), so this is a defensive guard against an unintended
  nested-directory write under `data/raw_eval/`.
- **FR-5 `RunConfig.persist_bronze` opt-in field, default off.** `eval/config.py::RunConfig` gains
  `persist_bronze: bool = False` (ADR-0010 §2 — default off; bronze is written only when explicitly
  enabled). Old configs and `configs/baseline.yaml` load unchanged (Pydantic supplies the default).
- **FR-6 Runner wiring — write bronze after the `EvalRecord` is built, under concurrency.** In
  `run_evaluation`, when `config.persist_bronze` is `True`, after the `EvalRecord` is built
  (`runner.py:227-248`) the runner calls `BronzeWriter.write(...)` once for the generation call and once
  for the judge call, passing the raw request+response surfaced by FR-1. The write is thread-safe (FR-3)
  and does **not** perturb the existing crash-safe JSONL flush (`runner.py:251-254`) or the cost/halt
  logic. When `persist_bronze` is `False` (default), **no bronze file is written and no extra work occurs**.
- **FR-7 `.gitignore` — add `data/raw_eval/`.** An explicit `data/raw_eval/` line is added (ADR-0010 §2 —
  confirmed not covered by `data/raw/` line 57 or `results/*` line 61). Bronze is author-machine-only;
  it never enters the clone.
- **FR-8 Privacy — no secrets in any bronze payload.** Per ADR-0010 §4: bronze serializes model id +
  request messages/contents + sampling params + the response body only. API keys / bearer tokens live in
  request **headers** / the client object and are **never** in the serialized request body or response, so
  they cannot land in a bronze file. The serializer must not introspect the client/auth; if any header-like
  or credential field is reachable on the response object, it is excluded/scrubbed.
- **FR-9 Backward-compatibility — old JSONL loads; existing readers/exporter/dashboard unaffected; plain
  Protocol methods still work.** A pre-Phase-18 `results/*.jsonl` line (no `per_fact`/`per_citation`) still
  parses with both fields `None`. `observability/exporter.py` (the boundary that calls `build_span_attrs`)
  and every JSONL reader behave as before for records lacking verdicts (the FR-10 guard omits `output.value`).
  The plain `generate()` (`openai_generator.py:56-59`) and `judge()` (`openai_judge.py:57-68`) Protocol
  methods continue to return their existing types unchanged. The dashboard is untouched.
- **FR-10 Verdict-reasoning hydration onto the judge span (pure mapper, always-on, guarded).** In
  `build_span_attrs`, `judge_attrs["output.value"]` is set to a **human-readable multi-line `text/plain`
  string** built from `record.per_fact` + `record.per_citation`, with
  `judge_attrs["output.mime_type"] = "text/plain"` — mirroring the Phase-17 generation precedent
  (`attributes.py:57-58`), always-on, **no new import** (pure `str.join`). The string shape (RQ-2):
  one line per fact `fact: {fact} -> {verdict}` then one line per citation `citation: {doc_id} -> {verdict}`
  (facts block then citations block; exact shape specified so AC-7 can assert it). **Guard (RQ-5):** omit
  `output.value` (and its mime_type) entirely when **both** lists are `None` **or** empty — an abstention
  with zero facts/citations correctly shows no judge output (there was nothing to verdict), consistent with
  the `cost_usd` cost-omit pattern (`attributes.py:73-74`).
- **FR-11 Full 500×2 re-run to populate gold + bronze + re-publish the baseline (RATIFIED).** The full
  sweep (both models, full question set) is run with `persist_bronze=True` via the existing eval-baseline
  recipe (`make build-index-gold` if the index is stale — ~1–2h MPS re-embed; `caffeinate -i -s`;
  `--concurrency 8`; close memory-heavy apps to avoid OOM on the 8 GB Air; **no resume** on crash → salvage
  by running the missing model into a separate `run_id` and concatenating, per the eval-baseline recipe). It
  populates `per_fact`/`per_citation` across the **whole** fresh `results/*.jsonl`, writes bronze under
  `data/raw_eval/` for **every** question×call (the complete "never re-run again" archive — the Option-A
  rationale), and the report is regenerated to **re-publish `results/baseline.{html,md}`** with the new
  schema. **No new config field beyond `persist_bronze`.** This is the sprint's one expensive/fragile
  operational step (quarantined to this phase per the SPRINT.md risk note); ~$2–3 + a few hours wall-clock.
- **FR-12 End-to-end Phoenix verification (the sprint-close check).** After `rag-export-traces` on the
  re-run's JSONL, **one failed trace** in Phoenix shows, in the Info tab, the full chain:
  question (Phase 17) → retrieved-doc content (Phase 16) → answer (Phase 17) → judge verdict reasoning
  (Phase 19) — without leaving Phoenix. This is a manual/operational acceptance (it requires the live
  re-run + a running Phoenix), verified by inspection and recorded in the phase's `/review`.

### Non-functional

- **NFR-1 Mapper purity preserved.** `build_span_attrs` stays free of Phoenix / OpenTelemetry / retrieval /
  ingest imports (`attributes.py:1-8`); FR-10 uses only `record.per_fact`/`per_citation` already on the
  in-memory `EvalRecord` and a pure `str.join`. The boundary-enrichment rule (Sprint-5
  `dashboard-phoenix-boundary`) is honoured — no loader is pulled into the mapper.
- **NFR-2 Concurrency + crash-safety preserved.** The bronze write is thread-safe (own lock, FR-3) and runs
  **after** the `EvalRecord` is built, without altering the runner's `ThreadPoolExecutor` / `write_lock` /
  `retrieve_lock` / `cost_lock` model (`runner.py:124-129, 251-263`). Distinct file-per-call keys keep
  contention low; a bronze write failure must not corrupt the JSONL flush.
- **NFR-3 Zero extra API cost from bronze + hydration.** The bronze write and the verdict hydration add **no
  LLM call** — they serialize data already produced by the calls the sweep makes. The only cost is the full
  re-run itself (FR-11), which is the sprint's one budgeted expensive action (~$2–3 + a few hours wall-clock).
- **NFR-4 Privacy / no-secrets (ADR-0010 §4).** No API key, bearer token, or auth header is ever serialized
  into a bronze file (FR-8). The bronze path is gitignored (FR-7) — secrets cannot reach the clone even if a
  serialization bug occurred.
- **NFR-5 Opt-in / default-off.** Bronze is written only when `persist_bronze=True` (FR-5); the default sweep
  path is byte-for-byte unchanged. This mirrors the Sprint-5/6 enrichment-flags-default-off discipline
  (SPRINT.md success criteria, "enrichment paths remain opt-in and default-off").
- **NFR-6 Backward-compat.** New `EvalRecord` consumption is read-only and tolerant of `None` verdicts
  (FR-9/FR-10 guard); no schema change, no reader edit, no dashboard change. Old JSONL and old configs load
  unchanged.
- **NFR-7 Determinism of serialization where feasible.** The verdict `output.value` string is deterministic
  for a given verdict (stable list order from the record). Bronze response serialization captures whatever
  the provider returned (inherently non-deterministic across live calls) but is **structurally** stable (same
  keys for the same provider) so the future cache can rely on the shape.
- **NFR-8 Test mirror + cassette/replay.** Tests mirror `src/`: `tests/eval/test_bronze.py` (new,
  with `tests/eval/__init__.py` present), bronze-writer assertions and seam-change-stub assertions; the
  judge-hydration assertion extends `tests/observability/test_attributes.py`. No flat `tests/test_*.py`.
  Bronze-writer + hydration tests run **offline** (stubs / in-memory `EvalRecord`); any live-provider seam
  assertion uses the cassette/replay pattern (ADR-0006), never a mocked LLM API — re-recording cassettes may
  be needed for the new captured fields. `make lint test` is the gate.

## Acceptance Criteria

Each code AC is checkable **offline** (no live LLM, no HF, no Phoenix, no network) via stubs, in-memory
`EvalRecord`s, or cassettes. The re-run + Phoenix ACs (AC-9, AC-10) are operational/manual and state how
they are verified.

- **AC-1 Protocols unchanged; `*_with_stats` surfaces raw request + response.** `Generator`
  (`generation/interfaces.py`) and `Judge` (`eval/interfaces.py`) declare only `generate()` / `judge()`
  (asserted unchanged). Each of the four concrete `*_with_stats` (OpenAI/Anthropic/Gemini generators +
  OpenAI judge) returns/exposes the raw request (messages/contents + params) and a serialized raw-response
  dict; asserted via cassette replay for at least one live provider, and via the stubs for the offline path.
- **AC-2 Per-provider serialization yields a JSON-able dict and never crashes on partial input.** Given a
  recorded (cassette) or stubbed provider response, the serializer returns a dict that round-trips through
  `json.dumps`; given a response missing `usage`/optional fields, it omits them without raising (asserted on
  a deliberately sparse stub/fake response object per provider shape).
- **AC-3 Stubs emit a minimal raw payload.** `StubGenerator.generate_with_stats` and
  `StubJudge.judge_with_stats` surface a minimal but valid raw request + serialized response (so bronze
  writing works fully offline); the plain `StubGenerator.generate` / `StubJudge.judge` still return exactly
  their current types (assert types + that the stub bronze payload is JSON-able).
- **AC-4 `BronzeWriter` key scheme + idempotency.** `BronzeWriter.write(run_id, question_id, model,
call_type, payload)` writes to `data/raw_eval/{run_id}/{question_id}__{model}__{call_type}.json`
  (`call_type ∈ {gen, judge}`); a second write to the same key **overwrites** (file content equals the
  second payload; no duplicate/append). Asserted against a `tmp_path` root with stub payloads.
- **AC-5 `BronzeWriter` thread-safety + flush.** Two threads writing the **same `run_id`** with **different
  `question_id`s** produce two complete, non-interleaved, individually-valid JSON files (asserted by spawning
  two threads against a `tmp_path`); each write is flushed (file readable immediately after `write` returns).
- **AC-6 `run_id` sanitization rejects path separators.** `BronzeWriter` init with a `run_id` containing
  `/`, `os.sep`, or `..` raises `ValueError`; a clean timestamp-slug `run_id` initializes successfully
  (parametrized assertion).
- **AC-7 Verdict hydration present, correct shape, and guarded.** (a) For an `EvalRecord` with
  `per_fact=[FactVerdict(fact="X", verdict="absent")]` and
  `per_citation=[CitationVerdict(doc_id="d1", verdict="unsupported")]`, `build_span_attrs(record)["judge"]`
  has `output.value` containing the lines `fact: X -> absent` and `citation: d1 -> unsupported` and
  `output.mime_type == "text/plain"`. (b) For an `EvalRecord` with `per_fact=None` and `per_citation=None`,
  the judge attrs have **no** `output.value` and **no** `output.mime_type` key. (c) For an `EvalRecord` with
  `per_fact=[]` and `per_citation=[]` (empty), behaviour is identical to (b) — omitted (RQ-5 single rule).
  All three are pure, in-memory, no LLM.
- **AC-8 `persist_bronze` opt-in + runner wiring (offline).** `RunConfig` has `persist_bronze: bool` default
  `False` (assert via `model_fields`). With a stubbed generator + judge and `persist_bronze=True`, a short
  `run_evaluation` (limit 1–2, stub factories) writes the expected bronze files under a `tmp_path`
  `data/raw_eval/{run_id}/...` (one `__gen` + one `__judge` per question); with `persist_bronze=False`, **no**
  bronze file is created. The JSONL output is byte-for-byte the same in both runs (bronze is side-channel).
  No additional generator/judge call beyond the existing two per question.
- **AC-9 Full 500×2 re-run populates gold + bronze + re-publishes baseline (operational).** The full sweep
  (both models, full question set) run with `persist_bronze=True` produces a fresh `results/*.jsonl` whose
  records carry `per_fact`/`per_citation` (non-empty on scored questions), writes bronze files under
  `data/raw_eval/{run_id}/` for **every** processed question×call, and regenerates
  `results/baseline.{html,md}` from the new run. Verified by inspecting the JSONL (verdict lists present
  across the run), the bronze dir (files present, each JSON-valid, no secrets), and the regenerated report —
  recorded in `/review`. (On a mid-run crash, salvage via separate `run_id` + concat per the eval-baseline
  recipe.)
- **AC-10 End-to-end legible failed trace in Phoenix (operational, the sprint-close gate).** After
  `rag-export-traces` on the re-run JSONL, one failed trace's Info tab shows — in order — the question
  (chain), retrieved-doc content (retriever), the answer (generation), and the judge verdict reasoning
  (judge). Verified by inspection (screenshot/notes) in `/review`. This is the Sprint 6 success criterion
  "a failed trace explains itself end-to-end."
- **AC-11 `.gitignore` + backward-compat + no out-of-scope change.** `.gitignore` contains a `data/raw_eval/`
  line. A pre-Phase-18 fixture JSONL line (no verdict keys) loads with both fields `None` and the exporter
  path produces a judge span **without** `output.value` (AC-7b). The diff contains **no** Protocol change
  (`generation/interfaces.py` / `eval/interfaces.py` unchanged), **no** `EvalRecord` schema change
  (`records.py` fields unchanged), **no** `--enrich-from-bronze` flag, **no** generation-span `input.value`
  hydration, and **no** dashboard change (asserted by diff/file review at `/review`).
- **AC-12 `make lint test` passes; offline tests need no network.** The full gate is green; bronze-writer +
  hydration + stub-seam tests run with no live LLM / no network; any live-provider seam assertion uses a
  committed cassette (ADR-0006).

## Resolved Open Questions

`AskUserQuestion` is unavailable to this subagent, so the BRAINSTORM's 5 open questions are resolved to their
ADR-0010 / SPRINT / user-ratified defaults below and flagged as **unconfirmed assumptions** for the
orchestrator to confirm before `/design`. RQ-1–RQ-5 map 1:1 to BRAINSTORM Open Questions 1–5. The
**bronze-payload fork (RQ-1) is already user-ratified as Option A** this session; the one operational
assumption worth confirming is **RQ-3** (re-run size/selection), since it sets what gets demonstrated.

- **RQ-1 Bronze payload — raw, not derived (BRAINSTORM Q1). RATIFIED → Option A (raw).** Bronze captures the
  **raw API request** (messages/contents + sampling params) **and the serialized raw provider response**, for
  both gen and judge — not derived objects. **✅ Ratified by the user (this session)** over Approach B/C:
  derived bronze would drift from ADR-0010 ("full raw payload"), lose raw-response richness, and fail to be
  the substrate for the future resumable/cached sweep. Encoded as FR-1/FR-2/FR-3. _Settled scope contract for
  `/design` — this is the phase's defining decision; not a soft assumption._
- **RQ-2 Judge `output.value` format — `text/plain` human-readable multi-line (BRAINSTORM Q2).**
  **Resolved: `text/plain`**, one line per fact (`fact: {fact} -> {verdict}`) then one line per citation
  (`citation: {doc_id} -> {verdict}`), consistent with Phase-17's `text/plain` answer rendering and more
  legible on Phoenix's narrow Info panel than a raw JSON array. The exact shape is specified so AC-7 asserts
  it. Encoded as FR-10 + AC-7. _Unconfirmed assumption — low risk; matches BRAINSTORM recommendation._
- **RQ-3 Re-run size/selection — full 500×2 re-published baseline (BRAINSTORM Q3). ✅ RATIFIED by the user
  (this session).** **Resolved: the full sweep** (both models, full question set) with `persist_bronze=True`,
  re-publishing `results/baseline.{html,md}`. Chosen over the drafted small (~20–50 q) run because the
  Option-A rationale is bronze-as-**complete** archive (a small run would archive only ~10% → a future
  feature would still re-run for the rest), and the full run re-publishes real baseline numbers. Trade-off
  accepted: this is the sprint's one expensive/fragile step (~1–2h index + ~40min eval on the 8 GB Air, OOM
  risk, no resume, ~$2–3) — quarantined here per the SPRINT.md risk note. Encoded as FR-11 + AC-9. _Settled
  scope contract for `/design`, not a soft assumption._
- **RQ-4 `run_id` sanitization — reject (raise `ValueError`) at init (BRAINSTORM Q4).**
  **Resolved: reject** — `BronzeWriter` raises `ValueError` if `run_id` contains `os.sep` / `/` / `..`,
  strict and loud over silent-replace. The runner generates timestamp slugs (no separators), so this is a
  defensive guard against an unintended nested write under `data/raw_eval/` (ADR-0010 Consequences). Encoded
  as FR-4 + AC-6. _Unconfirmed assumption — low risk._
- **RQ-5 Verdict guard — omit `output.value` when both lists are `None` OR empty (BRAINSTORM Q5).**
  **Resolved: single rule — omit when both are `None` or `[]`.** An abstention with zero facts/citations
  shows no judge `output.value` (correct — nothing was verdicted), consistent with the `cost_usd` cost-omit
  pattern. Encoded as FR-10 + AC-7c. _Unconfirmed assumption — low risk._

## Infrastructure Readiness

| Dependency                                                                                                                 | Type    | KB domain                                                                                            | Specialist   | Status                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Seam change — surface raw request+response from `*_with_stats` (OpenAI/Anthropic/Gemini generators + OpenAI judge)         | modules | rag-eval (`stats-capture-seam`); rag-generation (`generator-seam`)                                   | —            | Ready — `*_with_stats` confirmed off-Protocol (`interfaces.py`); request+response live in each impl today and discarded (`openai_generator.py:80-91`, `openai_judge.py:106-117`)                                                                                                                                                                |
| Per-provider raw-response serialization to a JSON-able dict                                                                | modules | rag-generation (`structured-output-per-provider`, `per-provider-token-accounting`)                   | —            | **Thin for raw-response serialization** — KB documents per-provider _output/token_ divergence, not full raw-payload serialization; the 3 divergent SDK shapes are the real risk (FR-2). Resolvable in `/design` from the verified source shapes; a brief Context7 check on each SDK's response object is optional, not a `--deep-research` need |
| `eval/bronze.py::BronzeWriter` (key/idempotency/thread-safety/sanitization/flush)                                          | module  | rag-eval (`stats-capture-seam`, `concurrent-eval-sweep`)                                             | —            | Ready — ADR-0010 §2 specifies the contract; runner concurrency model verified (`runner.py:124-129, 251-263`); writer is new but small + isolated                                                                                                                                                                                                |
| `eval/config.py::RunConfig.persist_bronze` (opt-in, default off)                                                           | module  | rag-eval (`stats-capture-seam`)                                                                      | —            | Ready — additive Pydantic field, backward-compat by default (`config.py:25-57`)                                                                                                                                                                                                                                                                 |
| `eval/runner.py::run_evaluation` (bronze write after EvalRecord, under concurrency)                                        | module  | rag-eval (`concurrent-eval-sweep`)                                                                   | —            | Ready — build site + locks verified (`runner.py:227-263`); verdict population already shipped Phase 18 (`runner.py:243-244`)                                                                                                                                                                                                                    |
| `StubGenerator` / `StubJudge` minimal raw payload                                                                          | modules | rag-eval (`cassette-replay-eval`)                                                                    | —            | Ready — stubs verified (`stub_generator.py`, `stub_judge.py`); add a minimal JSON-able payload so offline bronze tests work                                                                                                                                                                                                                     |
| `observability/attributes.py::build_span_attrs` (judge `output.value` + guard)                                             | module  | observability (`span-attribute-mapping`)                                                             | —            | Ready — pure mapper verified (`attributes.py:11`); Phase-17 precedent at `:57-58`, cost-omit guard at `:73-74`; no new import                                                                                                                                                                                                                   |
| `.gitignore` `data/raw_eval/` entry                                                                                        | config  | —                                                                                                    | —            | Ready — confirmed not covered by `data/raw/` (line 57) / `results/*` (line 61); this phase adds the line (ADR-0010 §2 / FR-7)                                                                                                                                                                                                                   |
| Small re-run (eval-baseline recipe) + Phoenix end-to-end verification                                                      | op      | rag-eval (`concurrent-eval-sweep`, `cassette-replay-eval`); observability (`span-attribute-mapping`) | —            | Ready — eval-baseline recipe documented (`make build-index-gold` / `caffeinate` / `--concurrency`); the one host-constrained step (quarantined here per SPRINT.md risk)                                                                                                                                                                         |
| `tests/eval/test_bronze.py` (new) + `tests/observability/test_attributes.py` (extend); cassette re-record for new fields   | tests   | rag-eval (`cassette-replay-eval`)                                                                    | —            | Ready — mirror layout + cassette pattern (ADR-0006); bronze + hydration tests offline; re-recording cassettes may be needed for the new captured fields (NFR-8)                                                                                                                                                                                 |
| `/update-kb observability` (`span-attribute-mapping` + `span-tree-shape`) and `/update-kb rag-eval` (`stats-capture-seam`) | KB      | observability / rag-eval                                                                             | kb-architect | **Correctly deferred (not a gap)** — Sprint-Wide Knowledge Plan lands these **after** the phase ships (SPRINT.md); their absence today is expected                                                                                                                                                                                              |

**No new KB, agent, command, or `--deep-research` needed for this phase.** Every dependency maps to an
existing module + existing KB domain. The one thin spot — **per-provider raw-response serialization** — sits
under `rag-generation` (`structured-output-per-provider` / `per-provider-token-accounting`), which documents
output/token divergence but not full raw-payload serialization; it is resolvable in `/design` from the
already-verified provider source shapes (an optional brief Context7 check on each SDK's response object, not
deep research). The post-phase `/update-kb` runs are deferred by design per SPRINT.md, not readiness gaps.

## Out of Scope (Won't — Phase 19)

- **Any `Generator` / `Judge` Protocol change** (`generation/interfaces.py`, `eval/interfaces.py`) — the seam
  change touches only the off-Protocol `*_with_stats` concrete methods + stubs (FR-1).
- **Any `EvalRecord` schema change** — Phase 18 shipped `per_fact`/`per_citation`; this phase only consumes
  them (no edit to `records.py` fields).
- **Generation-input-prompt hydration onto the generation span's `input.value`** — deferred; the sprint goal
  (question → evidence → answer → verdict) does not name it, the evidence is already on the retriever span
  (Phase 16), and bronze now archives the raw prompt for a future phase to read.
- **A `--enrich-from-bronze` CLI flag + the supporting `bronze_lookup` boundary read in
  `exporter.py` / `replay_jsonl`** — deferred (the read-path for bronze-driven span hydration is a later
  feature).
- **The future resumable / cached eval sweep** — its read-path, cache index, and invalidation are a separate
  **backlog** feature; this phase only writes the raw substrate (request messages) that makes it cheap to
  build later.
- **Any dashboard change** — this phase is Phoenix per-trace only; the aggregate dashboard is unchanged.
  (The dashboard reads the regenerated `results/baseline.*` like any other run — no code change.)
- **Parquet / DB storage for bronze** — JSON-per-call is sufficient at ~1500-record scale (ADR-0010 /
  BRAINSTORM Won't).
- **The `/update-kb` refreshes** — deferred to after the phase per the Sprint-Wide Knowledge Plan (SPRINT.md).

## Clarity Score

| Dimension        | Score          | Note                                                                                                                                                                                                                                                                                                    |
| ---------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem          | 3              | Root cause + evidence: verdicts in gold but no judge `output.value` (`attributes.py:64-74`); nothing re-run since Phase 18; ADR-0010 bronze designed-but-unbuilt; raw request+response discarded in each provider (`openai_generator.py:80-91`, `openai_judge.py:106-117`); `.gitignore` gap confirmed. |
| Users            | 3              | Named roles with workflow impact: Phoenix debugger (direct), re-runner, the future cached-sweep consumer (Option-A justification), the 3 gen + judge + 2 stubs (seam surface), the pure mapper, ADR-0010, deferred `/update-kb`.                                                                        |
| Success          | 3              | 12 ACs, falsifiable; offline where possible (stubs / in-memory / cassettes) and the two operational ACs (re-run, Phoenix) state their manual verification; AC-7 specifies the exact `output.value` string for assertion.                                                                                |
| Scope            | 3              | Option A locked + the three pieces crisply bounded; explicit Won't list (Protocol change, schema change, prompt hydration, `--enrich-from-bronze`, full baseline, the cache read-path, dashboard); all 5 open questions resolved (RQ-1 user-ratified, RQ-3 flagged to confirm).                         |
| Constraints      | 3              | All named: Protocol untouched / off-Protocol seam, mapper purity, concurrency + crash-safety, zero extra API cost, privacy/no-secrets, opt-in default-off, backward-compat, per-provider serialization risk, test mirror + cassette (ADR-0006).                                                         |
| **Total: 15/15** | **PASS (≥12)** | Gate passed. RQ-1 (bronze=raw / Option A) is user-ratified this session; RQ-2/RQ-4/RQ-5 are low-risk defaults; **RQ-3 (re-run size/selection) is the one operational assumption to confirm** before `/design`. No `AskUserQuestion` available as subagent.                                              |

## Next Step

→ `/design sprint-6/phase-19-full-trace-hydration`
