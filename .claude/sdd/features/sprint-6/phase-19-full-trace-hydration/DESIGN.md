# DESIGN: sprint-6/phase-19-full-trace-hydration — Re-run + Hydrate the Full Trace (close Sprint 6)

**Sprint/Phase:** sprint-6/phase-19-full-trace-hydration | **Date:** 2026-06-03

## Architecture

Phase 19 closes Sprint 6 by shipping three code pieces + one operational step, all to the
**ratified Option-A / ADR-0010 contract**. The three code pieces are independent in their
data paths but share one new typed model:

- **Piece 1 — the Option-A seam change (the real work + the one flagged risk).** Each of the
  four concrete `*_with_stats` methods (3 generators + the judge) + the 2 stubs surfaces the
  **raw API request** (the messages/contents + sampling/model params actually sent) and the
  **raw provider response** (serialized to a JSON-able dict) as a **third return value** —
  a new typed `RawCall` model. The `Generator`/`Judge` **Protocols are untouched** (they
  declare only `generate()`/`judge()`; `*_with_stats` is off-Protocol). The plain
  `generate()`/`judge()` methods unpack and **discard** the new value.
- **Piece 2 — the bronze writer + wiring.** A new `eval/bronze.py::BronzeWriter` persists one
  JSON file per call at the ADR-0010 key, thread-safe, opt-in via a new
  `RunConfig.persist_bronze` flag (default off), wired into the runner after the `EvalRecord`
  is built.
- **Piece 3 — verdict hydration (pure mapper).** `build_span_attrs` sets the judge span's
  `output.value` to a human-readable `text/plain` string from `record.per_fact` +
  `record.per_citation`, guarded to omit when both are `None`/empty.
- **Piece 4 (operational) — the FULL 500×2 re-run + Phoenix verify.** Runbook only (no code);
  host-bound, runs on the maintainer's machine.

### Seam mechanism decision — a typed `RawCall` returned as the 3rd tuple element

**Decision: option (b)+(a) combined — a small typed Pydantic `RawCall` model returned as the
third element of the `*_with_stats` tuple:** `(result, CallStats, RawCall)`.

Justification (against the DEFINE FR-1 menu of a 3rd return value / a typed model / a
side-channel):

- **Explicit + testable.** A return value is visible at every call site and asserted directly
  (AC-1/AC-2/AC-3) — a side-channel (instance attribute / thread-local) is invisible in the
  signature, races under `--concurrency 8`, and is the harder thing to test. Rejected.
- **Keeps `CallStats` lean (ADR-0007 footprint discipline).** Stuffing the raw payload into
  `CallStats` would bloat the gold `EvalRecord` (which embeds `generation`/`judge` CallStats)
  with the exact prompt+payload bulk ADR-0007/ADR-0010 deliberately route to **bronze**.
  `RawCall` is a **separate, never-persisted-to-gold** model — it rides the return tuple to
  the runner and dies there (only the runner's bronze write consumes it).
- **A typed model, not a bare dict.** `RawCall` carries `request: dict` + `response: dict`
  with a tiny, stable shape — typed so the runner and tests assert structure, and so the
  bronze payload schema (below) is constructed from it deterministically.

`RawCall` lives in a **new small module `eval/raw_call.py`** (not in `records.py`, to keep it
off the gold-schema module and signal it is a transient transport type). It imports only
`pydantic` — acyclic. `generation/*` and `eval/openai_judge.py` import it from there.

```python
# eval/raw_call.py  (new)
class RawCall(BaseModel):
    """Transient transport of one provider call's raw request + serialized response.

    NOT persisted to gold (EvalRecord). Surfaced as the 3rd element of *_with_stats and
    consumed only by the runner's bronze write. Kept off records.py on purpose.
    """
    model_config = ConfigDict(extra="forbid")
    request: dict[str, Any]    # model + messages/contents + sampling params actually sent
    response: dict[str, Any]   # provider response serialized to a JSON-able dict (FR-2)
```

### Data flow

```
# Piece 1 + 2 — raw capture → bronze (only when persist_bronze=True)
generator.generate_with_stats(ctx, q)            judge.judge_with_stats(q, ans, facts, docs)
        │ returns (answer, gen_stats, gen_raw)            │ returns (verdict, judge_stats, judge_raw)
        ▼                                                  ▼
   runner.process_one  ──── builds EvalRecord (runner.py:227-248, per_fact/per_citation already set) ────┐
        │                                                                                                 │
        │ if config.persist_bronze:                                                                       │
        │   bronze.write(run_id, q.question_id, model.model_id, "gen",   payload_from(gen_raw, meta))     │
        │   bronze.write(run_id, q.question_id, model.model_id, "judge", payload_from(judge_raw, meta))   │
        ▼                                                                                                 │
   with write_lock: f.write(record.model_dump_json()+"\n"); f.flush()   # UNCHANGED — bronze is side-channel
                                                                                                          │
   data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json   ◄──────────────────────────────────┘

# Piece 3 — verdict gold → pure mapper → judge span (no re-run needed for the code path)
EvalRecord.per_fact / .per_citation ──► build_span_attrs ──► judge_attrs["output.value"] (text/plain) ──► Phoenix Info tab
```

### Per-provider raw-response serialization strategy (FR-2 — the flagged risk)

A single **defensive serializer** `_serialize_response(response) -> dict` per call site (or a
shared helper) follows one uniform algorithm, defensive at every step:

1. **Try the pydantic-v2 fast path:** `response.model_dump(mode="json")`. The three live SDK
   response objects (OpenAI `ChatCompletion`, Anthropic `Message`, google-genai
   `GenerateContentResponse`) are all pydantic v2, so this is the expected uniform path and
   captures body/content + usage + provider-specific fields in one call.
2. **Fall back to a manual dict of known fields** when `model_dump` is absent or raises (this
   path is **exercised by the offline tests** — the fake clients return `SimpleNamespace`,
   not pydantic; see Risks). Read each field with `getattr(..., default)` and **omit** any
   missing attr — never raise — mirroring the defensive token reads at
   `gemini_generator.py:116-120`. Per-provider known fields:
   - **OpenAI** (`openai_generator.py`, `openai_judge.py`): `choices[0].message.content`,
     `choices[0].finish_reason`, `choices[0].message.refusal`, `system_fingerprint`, `model`,
     `usage` (`prompt_tokens`/`completion_tokens`/`total_tokens`).
   - **Anthropic** (`anthropic_generator.py`): `content` blocks (each `type` + `input`/`text`),
     `stop_reason`, `model`, `usage` (`input_tokens`/`output_tokens`).
   - **Gemini** (`gemini_generator.py`): `text`, `candidates` (content + `finish_reason`),
     `usage_metadata` (`prompt_token_count`/`candidates_token_count`/`thoughts_token_count`),
     `model_version`.
3. **Never raise** on a partial/odd response (FR-2 / AC-2): the whole serializer is wrapped so
   a missing/None attribute yields an omitted key, and a hard failure yields at most
   `{"_serialization_error": "<type>"}` rather than crashing the sweep.

The **request** capture is built explicitly from the local vars already in scope (not
introspected from the client): `{model, messages|contents|system, params}` — e.g. OpenAI/judge
`{"model", "messages", "response_format"}`; Anthropic `{"model", "system", "messages", "tools",
"tool_choice", "max_tokens"}`; Gemini `{"model", "contents", "system_instruction",
"response_mime_type"}`. The request `messages`/`contents` are the **substrate for the future
cache index** (backlog) — captured now, never read by this phase.

### Why the Protocols stay untouched

`Generator.generate` / `Judge.judge` are the only Protocol methods (verified
`generation/interfaces.py:21-31`, `eval/interfaces.py:23-36`). `*_with_stats` is
concrete-class-only. Surfacing `RawCall` from `*_with_stats` therefore changes **no Protocol**
(AC-1, AC-11) — the lowest-blast-radius path. The plain `generate()`/`judge()` keep their exact
return types by unpacking and discarding the third value (`result, _, _ = self.generate_with_stats(...)`).

### Mapper purity

`build_span_attrs` gains the judge `output.value` from `record.per_fact`/`per_citation`
(already on the in-memory `EvalRecord`) with a pure `str.join` — **no new import**, no Phoenix /
OTEL / retrieval / ingest coupling (NFR-1, the Sprint-5 boundary rule).

### Concurrency safety of bronze writes

`BronzeWriter` carries its **own `threading.Lock`**, independent of the runner's `write_lock` /
`cost_lock` / `retrieve_lock`. Because each call writes a **distinct file** keyed by
`question_id`+`call_type`, contention is low; the lock guards only the open→`json.dump`→`flush`
of one file. The bronze write happens **after** the `EvalRecord` is built and **before/around**
the JSONL flush without touching the `write_lock`-guarded `f.write/f.flush` (NFR-2). A bronze
write failure must not corrupt the JSONL flush — the bronze call is the runner's, and an
exception in it would propagate like any worker exception (acceptable: it surfaces loudly, the
JSONL up to that point is already flushed crash-safely).

### Bronze payload schema

`BronzeWriter.write` receives a caller-assembled `payload: dict` (the runner builds it from
`RawCall` + meta). Shape:

```json
{
  "schema_version": 1,
  "meta":     {"run_id": "...", "question_id": "...", "model": "...",
               "system": "openai|anthropic|google", "call_type": "gen|judge"},
  "request":  { ... RawCall.request ... },
  "response": { ... RawCall.response (serialized, FR-2) ... }
}
```

`schema_version` is included so a future cache/read-path can evolve the shape without
ambiguity (NFR-7 structural stability). No secrets: only model id + messages/contents +
sampling params + response body are serialized (FR-8); auth lives in headers/the client and is
never introspected.

## File Manifest

Prescriptive — an executor (Antigravity / Gemini) needs no extra context. All `direct` (no
specialist owns `eval/`, `generation/`, or `observability/`; the Infrastructure Readiness table
lists `—` throughout). Ordered by the phase convention (schema/transport → config → core →
runner wiring → observability → gitignore/cli → tests → docs).

| File                                                       | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Owner  | Phase order |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------- |
| `src/enterprise_rag_ops/eval/raw_call.py`                  | **New.** Define `RawCall(BaseModel)` with `model_config = ConfigDict(extra="forbid")`, fields `request: dict[str, Any]` and `response: dict[str, Any]`. Module docstring states it is a transient transport of one call's raw request + serialized response, NOT persisted to gold (kept off `records.py`). Imports only `pydantic` + `typing.Any` — acyclic.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | direct | 1           |
| `src/enterprise_rag_ops/generation/openai_generator.py`    | (1) Import `from enterprise_rag_ops.eval.raw_call import RawCall`. (2) Change `generate_with_stats` return type to `tuple[AnswerWithSources, CallStats, RawCall]`. (3) After the existing logic, build `request = {"model": self._model, "messages": [...the same list passed to create...], "response_format": {...}}` and `response = _serialize_response(response)` via the defensive serializer (try `response.model_dump(mode="json")`; except → manual dict of `choices[0].message.content`, `choices[0].finish_reason`, `choices[0].message.refusal`, `system_fingerprint`, `model`, `usage.{prompt_tokens,completion_tokens,total_tokens}`, each `getattr`-guarded, omit-missing). Return `result, stats, RawCall(request=request, response=response)`. (4) `generate` becomes `result, _, _ = self.generate_with_stats(...)`. Add a private module-level `_serialize_response(response) -> dict` helper (defensive, never raises).                                                                                                                                                                                                                                                                                                                                                                                         | direct | 3           |
| `src/enterprise_rag_ops/generation/anthropic_generator.py` | Same shape. Import `RawCall`; return `tuple[AnswerWithSources, CallStats, RawCall]`; `request = {"model", "system", "messages", "tools", "tool_choice", "max_tokens"}` (the exact values passed to `messages.create`); `response` via defensive serializer (try `model_dump(mode="json")`; except → manual: `content` blocks each `{type, name?, input?, text?}`, `stop_reason`, `model`, `usage.{input_tokens,output_tokens}`). `generate` → `result, _, _ = ...`. Add `_serialize_response`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct | 3           |
| `src/enterprise_rag_ops/generation/gemini_generator.py`    | Same shape. Import `RawCall`; return `tuple[AnswerWithSources, CallStats, RawCall]`; `request = {"model", "contents", "system_instruction", "response_mime_type"}`; `response` via defensive serializer (try `model_dump(mode="json")`; except → manual: `text`, `candidates` (content + `finish_reason`), `usage_metadata.{prompt_token_count,candidates_token_count,thoughts_token_count}`, `model_version`). `generate` → `result, _, _ = ...`. Add `_serialize_response`. Mirror the existing defensive `or 0` token reads (`:116-120`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | direct | 3           |
| `src/enterprise_rag_ops/eval/openai_judge.py`              | Same shape. Import `RawCall`; `judge_with_stats` return type → `tuple[JudgeVerdict, CallStats, RawCall]`; `request = {"model", "messages", "response_format"}`; `response` via defensive serializer (OpenAI shape, same as the OpenAI generator). `judge` becomes `result, _, _ = self.judge_with_stats(...)`. Add/reuse `_serialize_response`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | direct | 3           |
| `src/enterprise_rag_ops/generation/stub_generator.py`      | Import `RawCall`; `generate_with_stats` return type → `tuple[AnswerWithSources, CallStats, RawCall]`; append a minimal JSON-able `RawCall(request={"model": self._model, "messages": [{"role": "user", "content": question}]}, response={"answer": "stub", "sources": [c.doc_id for c in context_chunks]})` as the 3rd element. `generate` unchanged (returns `AnswerWithSources` only). Ensures AC-3/AC-8 work fully offline.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct | 3           |
| `src/enterprise_rag_ops/eval/stub_judge.py`                | Import `RawCall`; `judge_with_stats` return type → `tuple[JudgeVerdict, CallStats, RawCall]`; append a minimal JSON-able `RawCall(request={"model": self._model, "messages": [{"role": "user", "content": question}]}, response={"per_fact": [...], "per_citation": [...]})` built from the same lists it already produces. `judge` unchanged.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct | 3           |
| `src/enterprise_rag_ops/eval/config.py`                    | In `RunConfig`, add `persist_bronze: bool = Field(default=False, description="Opt-in: write raw request+response bronze under data/raw_eval/ (ADR-0010). Default off.")`. Additive, backward-compat (Pydantic supplies the default; `configs/baseline.yaml` loads unchanged).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | direct | 2           |
| `src/enterprise_rag_ops/eval/bronze.py`                    | **New.** `BronzeWriter`. `__init__(self, root: Path \| str = Path("data/raw_eval"), run_id: str)`: validate `run_id` — raise `ValueError` if it contains `os.sep`, `"/"`, or `".."` (FR-4/AC-6); store `self._run_dir = Path(root) / run_id`; create `self._lock = threading.Lock()`. `write(self, question_id: str, model: str, call_type: Literal["gen","judge"], payload: dict) -> Path`: key `self._run_dir / f"{question_id}__{model}__{call_type}.json"`; under `self._lock` — `mkdir(parents=True, exist_ok=True)`, open in `"w"` mode (overwrite-by-key idempotency, matching the runner's JSONL `w` semantics), `json.dump(payload, f)`, `f.flush()`. Module docstring cites ADR-0010 §2 + §4 (no secrets). Imports: `json`, `os`, `threading`, `pathlib`, `typing.Literal`. Independent lock — coexists with the runner's locks (distinct file-per-call = low contention).                                                                                                                                                                                                                                                                                                                                                                                                                                                | direct | 3           |
| `src/enterprise_rag_ops/eval/runner.py`                    | (1) Import `BronzeWriter`. (2) Update the two `*_with_stats` call sites to unpack the 3-tuple: `answer, gen_stats, gen_raw = generator.generate_with_stats(...)` (`runner.py:184`) and `verdict, judge_stats, judge_raw = judge.judge_with_stats(...)` (`runner.py:187`). **Abstain branch (`runner.py:171-181`):** that branch sets `answer`/`gen_stats` without a real call, so set `gen_raw = None` there (no generation API call was made → no bronze gen file for abstained-retrieval questions; document this). (3) When `config.persist_bronze`, construct one `BronzeWriter(run_id=config.run_id)` once (outside the per-question loop, e.g. near the lock setup `runner.py:124-129`) — `None` when off. (4) After the `EvalRecord` is built (`runner.py:227-248`), when `config.persist_bronze`: if `gen_raw is not None`, `bronze.write(q.question_id, model.model_id, "gen", {schema_version, meta{run_id,question_id,model.model_id,model.system,"gen"}, request: gen_raw.request, response: gen_raw.response})`; always `bronze.write(... "judge", from judge_raw ...)`. Place the bronze writes **outside** the `write_lock` block (BronzeWriter owns its own lock) and **do not** alter the JSONL `f.write/f.flush` (`runner.py:251-254`) or cost/halt logic. When `persist_bronze` is False → no writer, no writes. | direct | 4           |
| `src/enterprise_rag_ops/observability/attributes.py`       | In `build_span_attrs`, after the `judge_attrs` dict is built (`attributes.py:64-71`) and before the cost-omit block (`:72-74`): build the verdict string with a pure `str.join` — facts block then citations block: `lines = [f"fact: {fv.fact} -> {fv.verdict}" for fv in (record.per_fact or [])] + [f"citation: {cv.doc_id} -> {cv.verdict}" for cv in (record.per_citation or [])]`. **Guard (RQ-5, single rule):** only when `lines` is non-empty (i.e. NOT both `None`/empty) set `judge_attrs["output.value"] = "\n".join(lines)` and `judge_attrs["output.mime_type"] = "text/plain"`; otherwise omit both keys. No new import (uses `record.per_fact`/`per_citation` already on `EvalRecord`). Mirrors the Phase-17 generation precedent (`:57-58`) + the cost-omit guard (`:73-74`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | direct | 5           |
| `.gitignore`                                               | Add a `data/raw_eval/` line in the "Data / artifacts" block (after `data/processed/`, `.gitignore:58`). Confirmed not covered by `data/raw/` (`:57`) or `results/*` (`:61`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | direct | 6           |
| `src/enterprise_rag_ops/eval/cli.py`                       | Wire `persist_bronze` so the operational run (FR-11) can enable it. **Recommended (lower surface): config-only** — `configs/baseline.yaml` carries `persist_bronze: true` for the re-run, no CLI change; `RunConfig.load_from_yaml` already passes it through. **If a CLI override is preferred:** add `run_parser.add_argument("--persist-bronze", action="store_true")` and, after `config = RunConfig.load_from_yaml(...)` (`cli.py:71`), `if args.persist_bronze: config.persist_bronze = True`. Pick the config-only path unless the operator wants an ad-hoc toggle; the manifest treats the CLI flag as optional.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | direct | 6           |
| `tests/eval/test_raw_call.py`                              | **New.** AC-1 transport: `RawCall(request={...}, response={...})` round-trips through `model_dump_json`/`model_validate_json`; `extra="forbid"` rejects an unknown field. Pure, in-memory.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | direct | 7           |
| `tests/eval/test_bronze.py`                                | **New.** AC-4 key scheme + idempotency: `BronzeWriter(root=tmp_path, run_id="r1").write("q1","m","gen",payload)` writes `tmp_path/r1/q1__m__gen.json`; a second `write` to the same key overwrites (content == second payload, no append). AC-5 thread-safety + flush: two threads, same `run_id`, different `question_id`s → two complete, non-interleaved, individually-`json.load`-able files; each readable immediately after `write` returns. AC-6 sanitization: `BronzeWriter(root=tmp_path, run_id="a/b")` / `"../x"` / `f"x{os.sep}y"` raise `ValueError`; a clean timestamp slug succeeds (parametrized). AC-2 (offline serializer path, if `_serialize_response` is unit-testable) — assert a `SimpleNamespace`-style sparse response serializes to a `json.dumps`-able dict with missing fields omitted, never raising.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | direct | 7           |
| `tests/eval/test_runner.py`                                | **Extend.** (1) **Fix the 3-tuple break** in the existing `InstrumentedGenerator`/`InstrumentedJudge`/`CrashingGenerator` subclasses: they already `return super().generate_with_stats(...)`/`super().judge_with_stats(...)` so they propagate the 3-tuple transparently — verify no test unpacks the runner's internal call as a 2-tuple (none do; the runner is the unpacker). (2) Add AC-8: with `StubGenerator`+`StubJudge` and `run_config.persist_bronze = True` + `output_dir = tmp_path`, a short `run_evaluation` (limit 1–2) writes `data/raw_eval/{run_id}/{qid}__{model}__gen.json` + `__judge.json` per question (point bronze root at `tmp_path` — pass via the BronzeWriter root being `data/raw_eval` relative to cwd, or monkeypatch the writer's default root; recommend the writer's `root` defaulting to a module-level `BRONZE_ROOT` that the test monkeypatches, OR run the test in a `tmp_path` cwd). With `persist_bronze = False`, **no** bronze dir/file is created. Assert the JSONL is byte-for-byte identical between the two runs, and no extra gen/judge call beyond the existing two per question.                                                                                                                                                                                                  | direct | 7           |
| `tests/observability/test_attributes.py`                   | **Extend.** AC-7(a): `EvalRecord` with `per_fact=[FactVerdict(fact="X", verdict="absent")]`, `per_citation=[CitationVerdict(doc_id="d1", verdict="unsupported")]` → `build_span_attrs(record)["judge"]["output.value"]` contains exactly the lines `fact: X -> absent` and `citation: d1 -> unsupported` (assert exact string / line membership), and `["output.mime_type"] == "text/plain"`. AC-7(b): `per_fact=None`, `per_citation=None` → judge attrs have **no** `output.value` and **no** `output.mime_type` key. AC-7(c): `per_fact=[]`, `per_citation=[]` → identical to (b) — both keys omitted. Pure, in-memory, no LLM.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | direct | 7           |
| `tests/generation/test_openai_generator_stats.py`          | **Extend / fix.** The existing `result, stats = generator.generate_with_stats(...)` (`:41`) now unpacks a 3-tuple → **will fail**. Change to `result, stats, raw = generator.generate_with_stats(...)`; add AC-2 assertions: `raw` is a `RawCall`; `raw.request["model"] == "gpt-5-nano-test"`; `raw.request["messages"]` present; `json.dumps(raw.response)` succeeds; with the `SimpleNamespace` fake (no `model_dump`), the serializer used the manual fallback and omitted missing fields without raising. Keep the Protocol-unchanged assertions (`:52-57`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | direct | 7           |
| `tests/generation/test_anthropic_generator.py`             | **Extend / fix.** Change `result, stats = ...` (`:57`, and the second site `:107`) to `result, stats, raw = ...`; add AC-1/AC-2 assertions (`raw.request` has `system`/`messages`/`tools`; `raw.response` json-able; defensive fallback on the `SimpleNamespace` fake).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | direct | 7           |
| `tests/generation/test_gemini_generator.py`                | **Extend / fix.** Change every `result, stats = ...` / `_, stats = ...` site (`:70, :100, :116, :128, :135, :147, :229`) to unpack a 3-tuple (`result, stats, raw` or `_, stats, _`); add AC-1/AC-2 assertions on at least one happy-path site (`raw.request` has `contents`/`system_instruction`; `raw.response` json-able; defensive fallback on the fake).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | direct | 7           |
| `tests/eval/test_openai_judge_stats.py`                    | **Extend / fix.** Change `result, stats = judge.judge_with_stats(...)` (`:55`) to `result, stats, raw = ...`; add AC-1/AC-2 assertions (`raw.request` has `messages`/`response_format`; `raw.response` json-able; defensive fallback). Keep the Protocol-unchanged assertions (`:71-75`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | direct | 7           |

No `docs/adr/` change is in scope — ADR-0010 was ratified in Phase 18; this phase **builds**
against it (no new ADR, no amendment needed; the seam is the named-and-likely change ADR-0010
already anticipates). No Protocol change, no `records.py` change, no `exporter.py` change, no
`--enrich-from-bronze` flag, no dashboard change (AC-11 / Out-of-Scope).

## Implementation Phases

1. **`RawCall` transport model** — `eval/raw_call.py`. _No dependency._ Satisfies the seam's
   typed-transport contract; checkable by AC-1 (`test_raw_call.py`).
2. **Config flag** — `eval/config.py` `persist_bronze`. _No dependency._ Satisfies FR-5;
   checkable by AC-8 (`model_fields`).
3. **Seam change across impls + stubs + per-provider serialization** — the 3 generators, the
   judge, and the 2 stubs return `(result, CallStats, RawCall)`; plain `generate()`/`judge()`
   discard the 3rd value; add the defensive `_serialize_response`. **Protocols untouched.**
   **Depends on step 1.** Satisfies FR-1, FR-2, FR-8 (request side), FR-9 (plain methods);
   checkable by AC-1/AC-2/AC-3 + the fixed `*_stats` tests.
4. **Bronze writer + runner wiring** — `eval/bronze.py` (`BronzeWriter`, key/lock/flush/sanit)
   then `eval/runner.py` (3-tuple unpack at `:184`/`:187`, `gen_raw=None` on abstain, construct
   the writer when `persist_bronze`, write gen+judge after the `EvalRecord`). **Depends on
   steps 1–3** (`RawCall` + the seam surface) and step 2 (the flag). Satisfies FR-3, FR-4,
   FR-6, FR-8 (response side), NFR-2/3/4/5; checkable by AC-4/AC-5/AC-6/AC-8.
5. **Verdict hydration** — `observability/attributes.py` judge `output.value` + guard.
   _Independent of steps 3–4_ (pure mapper, reads existing `EvalRecord` fields). Satisfies
   FR-10, NFR-1; checkable by AC-7.
6. **`.gitignore` + cli wiring** — add `data/raw_eval/`; wire `persist_bronze` (config-only
   recommended). Satisfies FR-7; the gitignore line is checked by AC-11.
7. **Tests** — new `test_raw_call.py`, `test_bronze.py`; extend `test_runner.py`,
   `test_attributes.py`; **fix the four `*_stats` tests for the 3-tuple** (the biggest break —
   see Consistency Check C-1). Satisfies NFR-8.
8. **Quality pass** — `make lint test`. Targeted first:
   `uv run pytest tests/eval/test_bronze.py tests/eval/test_raw_call.py tests/observability/test_attributes.py tests/generation/ tests/eval/test_openai_judge_stats.py tests/eval/test_runner.py`.
9. **[Operational — host-bound, NOT in agy] the full 500×2 re-run + report + Phoenix verify**
   (Piece 4 runbook below). **Depends on steps 1–8 merged.** Satisfies FR-11, FR-12;
   verified by AC-9/AC-10 in `/review`.

### Operational runbook (FR-11 / FR-12 — Piece 4, runs on the maintainer's host)

1. If the gold index is stale: `make build-index-gold` (~1–2h MPS re-embed).
2. Set `persist_bronze: true` in `configs/baseline.yaml` (or use `--persist-bronze` if the CLI
   flag was added). Close memory-heavy apps (OOM risk on the 8 GB host).
3. `caffeinate -i -s uv run rag-eval run --config configs/baseline.yaml --concurrency 8`.
   On a mid-run crash there is **no resume** (the runner opens JSONL in `"w"`): salvage by
   running the missing model into a separate `run_id` and concatenating, per the eval-baseline
   recipe.
4. Verify: the fresh `results/*.jsonl` carries `per_fact`/`per_citation` (non-empty on scored
   questions); `data/raw_eval/{run_id}/` has a `__gen`/`__judge` JSON per processed
   question×call, each `json.load`-able, no secrets.
5. Regenerate the published baseline: `uv run rag-eval report --results results/<run>.jsonl`
   → re-publish `results/baseline.{html,md}`.
6. `rag-export-traces` on the re-run JSONL, then open **one failed trace** in Phoenix and
   confirm the Info tab reads question (chain) → retrieved-doc content (retriever) → answer
   (generation) → judge verdict reasoning (judge). Record the screenshot/notes in `/review`
   (AC-10, the sprint-close gate).

## Test Plan (AC → check)

| AC                                                                         | Check                                                                                                                                                                                                                      | Where                                                                                             |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **AC-1** Protocols unchanged; `*_with_stats` surfaces raw request+response | Protocol-method assertions (`Generator`/`Judge` declare only `generate`/`judge`) kept in the `*_stats` tests; each `*_with_stats` returns a `RawCall` 3rd element (cassette/fake for a live provider, stubs offline).      | `tests/generation/test_*`, `tests/eval/test_openai_judge_stats.py`, `tests/eval/test_raw_call.py` |
| **AC-2** Serializer JSON-able + never crashes on partial                   | `json.dumps(raw.response)` succeeds; the `SimpleNamespace` fake (no `model_dump`) drives the manual fallback, missing fields omitted, no raise.                                                                            | `tests/generation/test_*`, `tests/eval/test_openai_judge_stats.py`, `tests/eval/test_bronze.py`   |
| **AC-3** Stubs emit a minimal raw payload                                  | `StubGenerator.generate_with_stats` / `StubJudge.judge_with_stats` return a JSON-able `RawCall`; plain `generate`/`judge` return their existing types.                                                                     | `tests/eval/test_runner.py` (stub path), `tests/eval/test_bronze.py`                              |
| **AC-4** Bronze key scheme + idempotency                                   | Write → correct path; second same-key write overwrites (no append).                                                                                                                                                        | `tests/eval/test_bronze.py`                                                                       |
| **AC-5** Bronze thread-safety + flush                                      | Two threads, same run_id, different qids → two complete non-interleaved valid files; readable immediately.                                                                                                                 | `tests/eval/test_bronze.py`                                                                       |
| **AC-6** `run_id` sanitization                                             | `/`, `os.sep`, `..` raise `ValueError`; clean slug succeeds.                                                                                                                                                               | `tests/eval/test_bronze.py`                                                                       |
| **AC-7** Verdict hydration present/correct/guarded                         | (a) exact lines + `text/plain`; (b) both `None` → omitted; (c) both `[]` → omitted.                                                                                                                                        | `tests/observability/test_attributes.py`                                                          |
| **AC-8** `persist_bronze` opt-in + runner wiring                           | `model_fields["persist_bronze"]` default `False`; True → bronze files written under tmp; False → none; JSONL byte-for-byte identical; no extra calls.                                                                      | `tests/eval/test_runner.py`                                                                       |
| **AC-9** Full re-run populates gold+bronze+re-publishes                    | Inspect fresh JSONL (verdicts present), bronze dir (files present, JSON-valid, no secrets), regenerated report. Operational.                                                                                               | `/review`                                                                                         |
| **AC-10** End-to-end legible failed trace in Phoenix                       | Inspect one failed trace's Info tab (question→evidence→answer→verdict). Operational.                                                                                                                                       | `/review`                                                                                         |
| **AC-11** `.gitignore` + backward-compat + no out-of-scope change          | `.gitignore` has `data/raw_eval/`; pre-Phase-18 fixture loads `None`/`None` and yields a judge span without `output.value` (AC-7b); diff shows no Protocol/`records.py`/`--enrich-from-bronze`/gen-input/dashboard change. | `tests/observability/test_attributes.py` + diff review (`/review`)                                |
| **AC-12** `make lint test` green; offline tests need no network            | Full gate green; bronze/hydration/stub-seam tests offline; any live-provider seam assertion uses a committed cassette (ADR-0006).                                                                                          | `make lint test`                                                                                  |

**Cassette note (ADR-0006):** the four `*_stats` unit tests use in-process **fake clients**
(`SimpleNamespace`), not vcrpy cassettes — so no cassette re-record is needed for them; the
defensive serializer's manual fallback is what they exercise. If any **live-provider cassette**
test asserts the new captured `RawCall` fields, that cassette may need re-recording (NFR-8) —
but none is required for the offline gate.

## Infrastructure Gaps

Deep three-layer check. One thin spot (per-provider raw-response serialization), already
flagged in DEFINE; everything else covered by existing modules + KB.

| Gap Type           | Area             | Detail                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Recommendation                                                                                                                   |
| ------------------ | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Missing domain     | —                | All tech areas (the off-Protocol seam, Pydantic transport model, bronze JSON-per-call writer, thread-safe flush, the pure span mapper, `.gitignore`/data-layering) map to existing domains: `rag-eval` (`stats-capture-seam`, `concurrent-eval-sweep`, `cassette-replay-eval`), `rag-generation` (`generator-seam`, `structured-output-per-provider`, `per-provider-token-accounting`), `observability` (`span-attribute-mapping`, `dashboard-phoenix-boundary`).                                                                                                                                                                                                             | none                                                                                                                             |
| Missing concept    | `rag-generation` | **Thin (the flagged risk):** `structured-output-per-provider` / `per-provider-token-accounting` document per-provider _output/token_ divergence, **not full raw-payload serialization** to a JSON-able dict (FR-2 — the 3 divergent SDK response shapes). Resolvable in `/implement` from the **already-verified source shapes** (this DESIGN's serialization strategy section enumerates each provider's fields); an optional brief **Context7** check on each SDK's response object (OpenAI `ChatCompletion`, Anthropic `Message`, google-genai `GenerateContentResponse`) confirms `model_dump(mode="json")` availability + field names. **NOT** a `--deep-research` need. | `/update-kb rag-generation` (raw-payload serialization) — **deferred to the sprint-wide knowledge plan, not a Phase-19 blocker** |
| Missing specialist | —                | No specialist owns `eval/`, `generation/`, or `observability/` (`—` across the Infrastructure Readiness table); prior sprint-6 phases shipped `direct`. No new agent warranted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | none                                                                                                                             |

- **Domain existence:** ✅ every area maps to `rag-eval` / `rag-generation` / `observability`.
- **Concept coverage:** ✅ except the one thin spot above — raw-response serialization sits
  under `rag-generation` but is documented for output/token divergence, not full-payload
  capture. Resolvable from the verified source shapes (no research).
- **Agent alignment:** ✅ N/A — no specialist owns these modules; `kb-architect` owns the
  deferred post-phase `/update-kb` refreshes per the Sprint-Wide Knowledge Plan.

## Consistency Check

**Verdict: 🟡 MINOR DRIFT (no blocking CRITICAL/HIGH; one MEDIUM code-reality break the
DEFINE under-states — C-1).** Multi-module phase (3 src modules touched in the seam + 2 stubs +
bronze + config + runner + attributes + gitignore + cli + 7 test files; DEFINE went through a
ratified scope fork on RQ-1/RQ-3) → full six-pass cross-check of DEFINE↔DESIGN against the
constitution (AGENTS.md § Engineering Behavior + § Conventions + § Testing, ADR-0010, ADR-0007,
ADR-0006, the `rag-eval` / `rag-generation` / `observability` KB).

| ID  | Severity | Pass                         | Location                                                                                                                                                                                                                        | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Suggested fix                                                                                                                                                                                                                                                                                                                   |
| --- | -------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | MEDIUM   | Inconsistency (code-reality) | `tests/generation/test_openai_generator_stats.py:41`; `tests/generation/test_anthropic_generator.py:57,107`; `tests/generation/test_gemini_generator.py:70,100,116,128,135,147,229`; `tests/eval/test_openai_judge_stats.py:55` | **The biggest break — DEFINE under-states it.** Eleven existing test sites unpack the `*_with_stats` 2-tuple (`result, stats = ...` / `_, stats = ...`). FR-1's 3-tuple change makes **every one of them fail** (too many values to unpack). DEFINE NFR-8 names extending `test_bronze`/`test_attributes` but does **not** flag these existing 2-tuple unpackings. (The runner-subclass overrides in `test_runner.py:185-191,354-356,411-423` `return super()...` so they propagate the 3-tuple transparently — those are safe; only the direct 2-tuple unpackings break.) | Manifest step 7 makes fixing the four `*_stats` test files (the 11 sites) a required edit, converting each to `result, stats, raw = ...` / `_, stats, _ = ...` and adding the AC-1/AC-2 `raw` assertions. Flagged here so the executor does not read the existing tests as the spec.                                            |
| C-2 | LOW      | Underspecification           | DEFINE FR-6 / AC-8 (bronze root in tests)                                                                                                                                                                                       | DEFINE asserts bronze files land under a `tmp_path` `data/raw_eval/{run_id}/...` but does not say how the writer's **root** is redirected to `tmp_path` in the offline runner test (the writer defaults to `data/raw_eval`).                                                                                                                                                                                                                                                                                                                                               | DESIGN: `BronzeWriter.__init__` takes a `root` arg (default `Path("data/raw_eval")` or a module-level `BRONZE_ROOT`); the AC-8 test monkeypatches the root or runs under a `tmp_path` cwd. Implementer's choice; either keeps the test offline.                                                                                 |
| C-3 | LOW      | Underspecification           | Abstain branch + bronze gen file (`runner.py:171-181`)                                                                                                                                                                          | On retrieval-abstain no generation API call is made, so there is no `gen_raw`. DEFINE AC-9 says bronze for "every question×call" but a retrieval-abstained question has **no gen call**.                                                                                                                                                                                                                                                                                                                                                                                   | DESIGN: set `gen_raw = None` on the abstain branch and skip the gen bronze write for those questions (the judge bronze still writes — the judge always runs, `runner.py:187`). "Every question×call" = every call that actually happened. Note this in `/review` so AC-9's bronze-file count reconciles with the abstain count. |
| C-4 | LOW      | Ambiguity                    | DEFINE FR-1 seam mechanism ("third value / typed model / side-channel — a `/design` choice")                                                                                                                                    | DEFINE leaves the mechanism open.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | DESIGN resolves it: typed `RawCall` returned as the 3rd tuple element (rationale in Architecture). Settled.                                                                                                                                                                                                                     |

- **Duplication:** none. FR-1 (seam) and FR-2 (serialization) are layered, not overlapping;
  FR-3/FR-4/FR-6 (writer/sanitize/wiring) are sequential build steps; FR-10 (hydration) is an
  independent pure-mapper path. No requirement is double-built.
- **Ambiguity:** only C-4 (mechanism, now resolved). No vague descriptors; all 5 RQs resolved
  in DEFINE (RQ-1/RQ-3 user-ratified). The verdict-string shape is exact (AC-7).
- **Underspecification:** C-2 (test bronze root) and C-3 (abstain gen bronze) — both resolved
  in DESIGN. Every FR maps to a named site (`runner.py:184/187/227-248`, `attributes.py:64-74`,
  the four `*_with_stats`, `.gitignore:58`); every code-bearing AC names its mechanism
  (`model_fields`, `tmp_path` writer, `str.join` lines, `json.dumps` round-trip).
- **Constitution alignment:** ✅ **Minimal scope** — the seam is the _named, likely_ change
  ADR-0010 explicitly anticipates ("built + wired + gitignored in Phase 19"), not "in case";
  `RawCall` is a transport type that dies at the runner (no speculative persistence — it is
  deliberately kept **off** the gold `records.py` to honour ADR-0007 footprint discipline).
  **No Protocol change** (AGENTS.md seam rule + AC-1). The defensive serializer mirrors the
  existing defensive token reads (`gemini_generator.py:116-120`) — house pattern, not new.
  **No stranger-test leak** (all artifacts are public system design; no budget/career framing).
  **Conventions honoured:** English; tests mirror `src/` into `tests/eval/`, `tests/generation/`,
  `tests/observability/` with existing `__init__.py` (no flat `tests/test_*.py`); ADR-0006
  cassette/replay applies only to live-LLM paths (the offline gate uses stubs/fakes, never a
  mocked LLM API). **Privacy (FR-8/NFR-4):** the serializer never introspects client/auth; only
  body/params serialized; bronze is gitignored (FR-7).
- **Coverage:** ✅ all 12 FR + 8 NFR map to ≥1 manifest entry; all 12 AC map to a test or an
  operational `/review` check. Reverse check: every manifest entry references a verified
  component (`RawCall` new; `*_with_stats` at the four read sites; `runner.py:184/187/227-248`;
  `attributes.py:64-74` + the `:57-58`/`:73-74` precedents; `config.py:25-57`; `.gitignore:58`;
  `cli.py:71`; the 11 broken test sites). FR-11/FR-12 (operational) map to the runbook +
  AC-9/AC-10 `/review`, not code, per the locked scope.
- **Inconsistency:** only C-1 (the 11 stale 2-tuple unpackings — a real code-reality conflict,
  now a required step-7 edit). Terminology identical across DEFINE/DESIGN (`RawCall`, `bronze`,
  `persist_bronze`, `overwrite-by-key`, `text/plain`, "off-Protocol seam"); no directive
  conflicts with ADR-0010 (built verbatim), ADR-0007 (RawCall kept off gold — honours it),
  ADR-0006 (offline path uses fakes/stubs, not mocks).

## Risks & Trade-offs

- **The 11 stale 2-tuple test unpackings (C-1) — the single biggest trap.** The four `*_stats`
  test files will fail the moment FR-1 lands. Manifest step 7 makes fixing them required; if an
  executor adds new tests but leaves the old unpackings, `make test` fails at step 8. Flagged
  here and in C-1 with file:line.
- **Offline tests exercise the serializer's manual fallback, not the pydantic fast path.** The
  fake clients return `SimpleNamespace` (no `.model_dump`), so the `model_dump(mode="json")`
  fast path is **never** hit offline — only the manual per-provider branch is. The pydantic
  path is only exercised live (the re-run). Mitigation: the manual fallback is the defensive,
  always-correct path; the fast path is an optimization. AC-2 should assert the fallback
  produces a JSON-able dict; the live re-run (AC-9) implicitly validates the fast path.
- **Per-provider serialization drift (FR-2, the named risk).** Three divergent SDK shapes; a
  field rename in a future SDK bump would silently omit (defensive-by-design — omit, never
  raise). Acceptable: bronze is a best-effort archive, not a contract; the request side (the
  cache substrate) is built from local vars, not SDK introspection, so it is stable.
- **Abstain questions write no gen bronze (C-3).** Correct — no gen call happened — but AC-9's
  "every question×call" count must reconcile with the abstain count. Documented for `/review`.
- **Bronze write outside the JSONL `write_lock`.** A bronze write exception would propagate like
  any worker exception; the crash-safe JSONL flush has already happened for prior records, so no
  JSONL corruption. The bronze writer's own lock prevents intra-bronze races. Low contention
  (distinct file per call).
- **ADR warranted? No new ADR.** ADR-0010 (ratified Phase 18) is the contract this phase builds;
  the seam is the change it already anticipates. No amendment, no new decision — correctly below
  the "ADR only if a new/changed decision" bar.
- **Operational fragility (FR-11).** The full 500×2 re-run is the sprint's one expensive/fragile
  step (OOM risk, no resume, ~$2–3). Quarantined to this phase; host-bound (not agy). Salvage
  path documented in the runbook.

## Next Step

→ `/implement sprint-6/phase-19-full-trace-hydration` — gaps are clean (the one thin spot,
per-provider raw-response serialization, is resolved inline in this DESIGN from the verified
source shapes; optional Context7 confirmation, no `--deep-research`).

Per the cross-tool **Implement Contract** (AGENTS.md), the token-heavy code implement stage
should run in **Antigravity / Gemini** (`/implement-agy`) against this `DESIGN.md` as the
contract — confirm the branch `sprint-6/phase-19-full-trace-hydration`, read this manifest +
`DEFINE.md` (acceptance criteria) + the `rag-eval` / `rag-generation` / `observability` KB,
implement in phase order (RawCall → config → seam+serialization → bronze+runner → hydration →
gitignore/cli → tests), **fix the 11 stale 2-tuple test unpackings (C-1) as part of step 7**,
then `make lint test`. **Steps 1–8 run in agy; step 9 (the full 500×2 re-run + report + Phoenix
verify, FR-11/FR-12) is operational and host-bound — it runs on the maintainer's machine, then
Claude reviews via `/review` against AC-9/AC-10.**
