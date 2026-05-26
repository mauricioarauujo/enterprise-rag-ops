# DESIGN: sprint-2/phase-6-multimodel-report — Multi-Model Runner & Baseline Report

**Sprint/Phase:** sprint-2/phase-6-multimodel-report | **Date:** 2026-05-25

## Architecture

Phase 6 is the **orchestration layer** that finally drives Phases 3–5 primitives
end-to-end: it runs ≥2 cross-family generators over the 500-question set, captures
cost/latency per LLM call, persists one `EvalRecord` per (question × model) to JSONL,
and renders the first published baseline report. Nothing here re-derives a metric —
every scoring primitive (`OpenAIJudge`, `aggregate`, `aggregate_retrieval_metrics`,
`compute_abstention_metrics`, `ndcg_at_k`) already exists and is reused unchanged. The
new code is composition + capture + render + a second-family adapter.

All eight BRAINSTORM questions (Q2/Q3/Q5/Q6/Q8 + Decision 2 + ADR-0007 fixed; Q1/Q4/Q7
resolved-under-delegation) are CLOSED in the DEFINE and treated here as fixed inputs,
not re-opened.

### 1. Cost/latency capture seam (Q3 = Approach C — implementations only)

```
generation/openai_generator.py:  generate(...)                    # UNCHANGED (rag-ask path)
                                  generate_with_stats(...) ──▶ (AnswerWithSources, CallStats)   # +new
generation/anthropic_generator.py: generate(...) / generate_with_stats(...) ──▶ (…, CallStats) # new file
eval/openai_judge.py:             judge(...)                       # UNCHANGED
                                  judge_with_stats(...)      ──▶ (JudgeVerdict, CallStats)       # +new
generation/stub_generator.py · eval/stub_judge.py:  *_with_stats ──▶ (…, CallStats(0,0,0.0,…))  # +zeroed
```

The `Generator` / `Judge` Protocols in `generation/interfaces.py` and
`eval/interfaces.py` stay **byte-identical** (NFR-4). `rag-ask` (`generation/cli.py`)
never unpacks a tuple. Each `*_with_stats` wraps the existing single call, times it with
`time.perf_counter()`, and reads the provider-native usage block: OpenAI
`response.usage.prompt_tokens` / `completion_tokens`; Anthropic
`resp.usage.input_tokens` / `output_tokens`. `cost_usd` is **not** computed inside the
adapters — the adapters emit token counts only; the runner applies the config price
table (FR-8) so prices live in exactly one place.

### 2. AnthropicGenerator (ADR-0005 named swap, the one new runtime dep)

```
generation/anthropic_generator.py  (the ONLY module importing `anthropic`)
   ├─ __init__: Anthropic() — raise clean RuntimeError if ANTHROPIC_API_KEY unset (mirror OpenAIGenerator)
   ├─ reuse generation/prompt.py: build_system_prompt() / build_user_prompt()   # NO duplicated prompt logic
   └─ messages.create(tools=[emit_answer w/ AnswerWithSources.model_json_schema()],
                       tool_choice={"type":"tool","name":"emit_answer"})
        └─ tool_use block → AnswerWithSources.model_validate(block.input)  # defensive re-validate, same as OpenAI
```

The adapter is the **only** `anthropic` importer — the offline-CI invariant is preserved
exactly as `OpenAIGenerator` is the only `openai` importer. Anthropic has no
`response_format`, so structured output is via forced tool-use; the tool's
`input_schema` is `AnswerWithSources.model_json_schema()` (the same schema-as-SSoT
pattern). Default model `claude-3-5-haiku-20241022`, env override `RAG_GEN_MODEL_ANTHROPIC`.

### 3. RunConfig + generator factory (micro-decision 1)

```
configs/baseline.yaml ──yaml.safe_load──▶ eval/config.py:RunConfig (pydantic)
   models: [ {model_id, system: openai|anthropic}, … ]   # system is a typed enum
   judge_model · limit · k=10 · output_dir · run_id · prices{model_id:{in,out}} · cost_ceiling_usd?
                                          │
        eval/runner.py:  _GENERATOR_FACTORY = {"system":SystemEnum → class}     # typed, offline-testable
            {"openai": OpenAIGenerator, "anthropic": AnthropicGenerator}
```

`RunConfig` selects the generator class via a `system` **enum** + a tiny in-`runner.py`
registry/factory — **not** an import-path string. This keeps selection typed and
offline-testable (the factory maps a closed enum to a known class; no `importlib`,
no string eval). Judge is always `OpenAIJudge` on `judge_model` in v1 (Q2 — `ClaudeJudge`
is the deferred ADR-0005 swap).

### 4. End-to-end runner data flow (FR-5; the single live path is cassette-gated in tests)

```
RunConfig ─▶ FR-10 fail-fast: assert LANCEDB_DIR / BM25_INDEX_DIR / CHUNK_ORDER_PATH exist
   │           (else clean message naming `make build-index-gold` — never a load_retriever stack trace)
   ▼
pipeline.load_retriever()  ── ONCE, reused across all models (Q6) ──┐
   │                                                                 │
   for model in config.models:          # generator swaps; retriever is model-agnostic
     gen = _GENERATOR_FACTORY[model.system](model=model.model_id)
     judge = OpenAIJudge(model=config.judge_model)
     for q in load_questions(limit=config.limit):     # Phase 4 reader, limit flows straight through
        chunk_hits = retriever.retrieve_chunks(q.question)        # (chunk_id, doc_id, score) tuples
        retrieval_ranked_ids = deduplicate_ranked_ids([cid for cid,_,_ in chunk_hits])  # Phase-5 helper
        if not chunk_hits:                                         # abstention short-circuit (mirror rag-ask)
           answer = AnswerWithSources(answer=ABSTAIN_ANSWER, sources=[]); gen_stats = zeroed
        else:
           ctx = ContextAssembler(store).assemble(chunk_hits)
           answer, gen_stats = gen.generate_with_stats(ctx, q.question)
        verdict, judge_stats = judge.judge_with_stats(q.question, answer, q.answer_facts, retrieved_docs)
        did_abstain_retrieval = (chunk_hits == [])
        did_abstain_e2e       = (answer.answer == ABSTAIN_ANSWER and answer.sources == [])
        rec = EvalRecord(... 3 judge floats, both CallStats+cost, retrieval_ranked_ids, abstention bools ...)
        jsonl.write(rec.model_dump_json() + "\n"); jsonl.flush()   # crash-safe checkpoint (Decision 3-C)
   ▼
eval/report.py renders results/baseline.{html,md} from the just-written JSONL  # same invocation (Decision 3-C)
```

`ABSTAIN_ANSWER` is imported from `generation/cli.py` (the NFR-5 SSoT path, re-exported
from `generation/schema.py`), never hardcoded. The runner is **sequential** in the Must
tier; `--concurrency` is FR-14 (Should).

### 5. Report render — pure function over JSONL (FR-7; micro-decision 3)

```
eval/report.py  (NO live LLM calls — reads only the JSONL)
   read_records(jsonl) ──▶ group by gen_ai.request.model
   ├─ _summary_rows(records)        → per-model mean fact_recall/precision/faithfulness + abstention P/R
   ├─ _per_category_rows(records)   → aggregate_retrieval_metrics(qs, ranked_map, k) [retrieval]
   │                                  + category-grouped judge-float means [None-skipping]; all 10 cats
   └─ _cost_rows(records)           → per-model total cost_usd, mean latency_s, total tokens
   render(_HTML_TEMPLATE | _MD_TEMPLATE)  # string.Template, one HTML (inline <style>), one MD
        None → "N/A" cell (never coerced to 0.0; NFR-2)
```

`report.py` is a deterministic render over the persisted JSONL — re-runnable as the FR-16
`rag-eval report` sub-command without any live call.

## File Manifest

Every owner is `direct` — the DEFINE (Infrastructure Readiness, final row) concluded **no
specialist agent is warranted**: Phase 6 is a single-pass orchestration build over
already-built, well-documented primitives, with no repeated specialist context-loading
across sessions. The only agents in `.claude/agents/` are workflow/KB specialists
(`code-reviewer`, `kb-architect`, brainstorm/define/design agents); none own `src/eval`
or `src/generation` code.

| File                                                       | Change  | Owner  | Phase order | Covers                                                                                                        |
| ---------------------------------------------------------- | ------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------- |
| `src/enterprise_rag_ops/eval/records.py`                   | created | direct | 1 (schema)  | FR-1, FR-2, FR-8; NFR-3; AC-1, AC-3, AC-10 (`EvalRecord` + `CallStats` + cost helper)                         |
| `tests/eval/test_records.py`                               | created | direct | 1 (tests)   | FR-15; AC-1 (round-trip + verdict-list exclusion), AC-3 (`CallStats` fields), AC-10 (cost incl. no-price)     |
| `src/enterprise_rag_ops/eval/config.py`                    | created | direct | 2 (config)  | FR-4, FR-9, FR-13; AC-6 (`RunConfig` + `system` enum + prices + `cost_ceiling_usd`)                           |
| `configs/baseline.yaml`                                    | created | direct | 2 (config)  | FR-4, FR-9; AC-6, AC-15 (Q1 model set + pinned price table; `gpt-5-nano` price-verify note)                   |
| `tests/eval/test_config.py`                                | created | direct | 2 (tests)   | FR-15; AC-6 (typed parse; malformed YAML → `ValidationError`)                                                 |
| `src/enterprise_rag_ops/generation/openai_generator.py`    | edit    | direct | 3 (core)    | FR-2; AC-3 (`+generate_with_stats` reading `response.usage`; `generate` untouched)                            |
| `src/enterprise_rag_ops/generation/stub_generator.py`      | edit    | direct | 3 (core)    | FR-2; NFR-1 (`+generate_with_stats` → zeroed `CallStats`)                                                     |
| `src/enterprise_rag_ops/generation/anthropic_generator.py` | created | direct | 3 (core)    | FR-3, FR-2; AC-4 (`Generator` via tool-use; `generate_with_stats` reads Anthropic `usage`)                    |
| `src/enterprise_rag_ops/eval/openai_judge.py`              | edit    | direct | 3 (core)    | FR-2; AC-3 (`+judge_with_stats` reading `response.usage`; `judge` untouched)                                  |
| `src/enterprise_rag_ops/eval/stub_judge.py`                | edit    | direct | 3 (core)    | FR-2; NFR-1 (`+judge_with_stats` → zeroed `CallStats`)                                                        |
| `tests/generation/test_anthropic_generator.py`             | created | direct | 3 (tests)   | FR-15; AC-4 (offline fake-client `tool_use` → `AnswerWithSources`; key-unset `RuntimeError`)                  |
| `tests/generation/test_openai_generator_stats.py`          | created | direct | 3 (tests)   | FR-15; AC-3 (`generate_with_stats` fake `usage`; Protocol-unmodified grep assertion)                          |
| `tests/eval/test_openai_judge_stats.py`                    | created | direct | 3 (tests)   | FR-15; AC-3 (`judge_with_stats` fake `usage`; Judge Protocol-unmodified assertion)                            |
| `tests/eval/cassettes/anthropic_generator.yaml`            | created | direct | 3 (tests)   | FR-15; AC-5 (one recorded Anthropic live call, `vcr`/`record_mode="none"` replay, ADR-0006)                   |
| `src/enterprise_rag_ops/eval/runner.py`                    | created | direct | 4 (eval)    | FR-5, FR-8, FR-10, FR-13, FR-14; AC-2, AC-7, AC-10, AC-11, AC-16, AC-17 (orchestration + factory + fail-fast) |
| `tests/eval/test_runner.py`                                | created | direct | 4 (tests)   | FR-15; AC-2 (flush count), AC-7 (`load_retriever` once), AC-11 (fail-fast), AC-16/17 (ceiling, concurrency)   |
| `src/enterprise_rag_ops/eval/report.py`                    | created | direct | 4 (eval)    | FR-7; NFR-2; AC-9 (HTML+MD, 10-category, None→N/A; pure render over JSONL)                                    |
| `tests/eval/test_report.py`                                | created | direct | 4 (tests)   | FR-15; AC-9 (fixture JSONL: summary, 10-category rows, cost/latency, "N/A" cell)                              |
| `src/enterprise_rag_ops/eval/cli.py`                       | created | direct | 4 (eval)    | FR-6, FR-10, FR-16; AC-8, AC-11, AC-18 (`rag-eval` `main`; `run` + `report` sub-commands)                     |
| `tests/eval/test_cli.py`                                   | created | direct | 4 (tests)   | FR-15; AC-8 (offline `run` with stubs → both files), AC-11 (guarded msg), AC-18 (`report` re-render)          |
| `pyproject.toml`                                           | edit    | direct | 4 (config)  | FR-3, FR-6; NFR-6 (`anthropic>=0.40,<1.0` runtime dep; `rag-eval` console script)                             |
| `Makefile`                                                 | edit    | direct | 4 (eval)    | FR-10, FR-11; AC-11, AC-13 (`eval-baseline` target; fail-fast wired)                                          |
| `docs/adr/0007-eval-record-schema.md`                      | created | direct | 5 (ADR)     | FR-17, FR-9; AC-14, AC-15 (schema + cost model; references ADR-0004; `gpt-5-nano` follow-up)                  |
| `docs/adr/README.md`                                       | edit    | direct | 5 (ADR)     | index row for ADR-0007                                                                                        |
| `.gitignore`                                               | edit    | direct | 5 (docs)    | FR-12; AC-12 (`!results/baseline.html`, `!results/baseline.md` negation)                                      |
| `results/baseline.html` + `results/baseline.md`            | created | direct | 6 (run)     | FR-11, FR-12; AC-12, AC-13 (committed milestone-run artifacts — the one live paid run, NFR-9)                 |

Notes on placement choices:

- **`records.py` holds `EvalRecord` + `CallStats` + the cost helper** (micro-decision 5).
  DEFINE FR-1/FR-2/FR-8 all name `eval/records.py`. Keeping the cost helper
  (`compute_cost_usd(stats, price) -> float | None`) beside `CallStats` keeps the
  arithmetic in one unit-tested place; the runner imports it. `report.py` does **not**
  recompute cost — it reads the persisted `cost_usd` from each record.
- **No `eval/interfaces.py` edit.** Q3 = Approach C: `*_with_stats` live on the
  implementations only; the Protocols stay clean (NFR-4). Confirmed against the actual
  Protocol files — `Generator.generate` and `Judge.judge` are the only methods and stay so.
- **No `generation/cli.py` / `generation/schema.py` / `generation/prompt.py` edit.**
  `rag-ask` is untouched (NFR-4); `ABSTAIN_ANSWER` and the prompt builders are imported
  as SSoT, not duplicated (NFR-5; the Anthropic adapter reuses `prompt.py`).
- **Anthropic cassette lives under `tests/eval/cassettes/`** (the ADR-0006 location
  already used by Phase 5's abstention cassette) even though the adapter is in
  `generation/`, because the `vcr` conftest fixture + `cassette_library_dir` are wired
  there. The Anthropic test file lives in `tests/generation/` (mirrors the module) and
  references the shared cassette dir via the existing fixture.
- **`tests/eval/conftest.py` is NOT edited** — Phase 5 already wired the vcrpy fixture
  (`cassette_library_dir`, `filter_headers=["authorization"]`, `record_mode="none"`); the
  Anthropic cassette test reuses it as-is. If the conftest's `cassette_library_dir` is
  scoped narrowly, `/implement` adds one line; flagged as the only possible micro-edit.

## Implementation Phases

One PR, disciplined commit sequence (DEFINE Sequencing Notes; one-branch-one-PR SDD
model). Phase-order convention: schema/config → core `src/` → eval `eval/` → tests
(interleaved per module) → docs + ADR → the milestone run. Observability hooks
(Sprint 3) are out of scope, so that convention slot is empty.

1. **`CallStats` + augmented methods + `EvalRecord` + cost helper (FR-1, FR-2, FR-8).**
   Create `eval/records.py` (`CallStats`, `EvalRecord`, `compute_cost_usd`). Add
   `generate_with_stats` to `OpenAIGenerator` + `StubGenerator` and `judge_with_stats`
   to `OpenAIJudge` + `StubJudge` (thin wrappers over the existing call, reading
   `response.usage`; stubs return zeroed `CallStats`). Mirrored tests:
   `test_records.py` (round-trip, verdict-list exclusion, cost arithmetic incl.
   no-price→None), `test_openai_generator_stats.py`, `test_openai_judge_stats.py` (fake
   `usage`; Protocol-unmodified assertion). Commit:
   `feat(eval): CallStats + EvalRecord + generate/judge_with_stats (Protocols untouched)`.

2. **`AnthropicGenerator` + offline test + recorded cassette (FR-3).** Create
   `generation/anthropic_generator.py` (tool-use structured output, reuse `prompt.py`
   builders, clean `RuntimeError` on missing key, `generate_with_stats` reads Anthropic
   `usage`). Add `tests/generation/test_anthropic_generator.py` (offline fake client
   returning `content=[tool_use]` + `usage`). Record `tests/eval/cassettes/anthropic_generator.yaml`
   once (`VCR_RECORD_MODE=once` + `ANTHROPIC_API_KEY`, the only dev-time live call) and
   add the `@pytest.mark.vcr` replay test. Add `anthropic>=0.40,<1.0` to `pyproject.toml`
   runtime deps. Commit: `feat(generation): AnthropicGenerator via tool-use + cassette`.

3. **`EvalRecord` consumers wiring — `RunConfig` + `configs/baseline.yaml` (FR-4, FR-9).**
   Create `eval/config.py` (`RunConfig` pydantic model, `system` enum, prices,
   `cost_ceiling_usd`) parsing via `yaml.safe_load`. Commit `configs/baseline.yaml` with
   the Q1 model set (`gpt-5-nano-2025-08-07` + `claude-3-5-haiku-20241022`, judge
   `gpt-5-nano-2025-08-07`) and the pinned price table. Mirrored `test_config.py`.
   Commit: `feat(eval): RunConfig + baseline.yaml (system enum, config price table)`.

4. **Runner — single-retriever reuse, factory, cost accounting, fail-fast (FR-5, FR-8,
   FR-10, FR-13).** Create `eval/runner.py` (`_GENERATOR_FACTORY` enum→class map,
   `load_retriever()` once, per-question retrieve→assemble→generate→judge→score→flush,
   `compute_cost_usd` over the price table, FR-10 index existence guard, FR-13 ceiling
   warn). Mirrored `test_runner.py` (patches `load_retriever`, asserts called once;
   flush count after early stop; fail-fast message; ceiling warn). Commit:
   `feat(eval): multi-model runner (single retriever, cost accounting, fail-fast)`.

5. **Report + CLI + console-script + make target (FR-6, FR-7, FR-11, FR-16).** Create
   `eval/report.py` (string.Template HTML+MD, 10-category breakdown via
   `aggregate_retrieval_metrics`, None→"N/A") and `eval/cli.py` (`rag-eval` `main`;
   `run` drives runner then renders, `report` re-renders from JSONL). Wire the `rag-eval`
   console script in `pyproject.toml` and the `eval-baseline` target in the `Makefile`
   (with the FR-10 fail-fast). Mirrored `test_report.py` + `test_cli.py`. Commit:
   `feat(eval): HTML+MD report + rag-eval CLI + eval-baseline target`.

6. **ADR-0007 + `.gitignore` negation (FR-12, FR-17).** Write
   `docs/adr/0007-eval-record-schema.md` (schema + cost model, references ADR-0004,
   `gpt-5-nano` price follow-up), add its `docs/adr/README.md` index row, and add the
   `.gitignore` negation lines. Commit: `docs(adr): ADR-0007 eval-record schema + cost model`.

7. **The one milestone live run → commit the baseline (FR-11, FR-12, AC-13/AC-15).**
   Maintainer verifies the `gpt-5-nano` price (AC-15) against the official OpenAI page,
   runs `make build-index-gold` then `make eval-baseline` (the single ~low-single-digit-USD
   paid run, NFR-9), and commits `results/baseline.{html,md}`. Commit:
   `feat(eval): publish first multi-model baseline report`. Distinct from `make test`,
   which is fully offline (NFR-1).

Shoulds (FR-13/14/16, AC-16/17/18) slot into steps 4–5 after the Must spine; their
absence does not fail the phase.

## ADR-0007 Content Outline (settled spec for `/implement`)

`docs/adr/0007-eval-record-schema.md` — **proposed → accepted**, written this phase
(FR-17, AC-14), referencing ADR-0004's OTEL GenAI field table. So `/implement` writes it
from a settled spec, the three sections are:

**1. The `EvalRecord` JSONL schema (FR-1 field list, OTEL-aligned).** One JSON line per
(question × model), flushed per question to `results/<run_id>.jsonl`:

- Identity: `question_id`, `category`, `run_id`.
- Generation call (OTEL `gen_ai.*`): `gen_ai.request.model` (generator id),
  `gen_ai.system` (`openai`|`anthropic`), `gen_ai.operation.name` (`chat`).
- The two `CallStats`, **namespaced nested** (micro-decision 2): `generation: CallStats`
  and `judge: CallStats`, each carrying `input_tokens`, `output_tokens`, `latency_s`,
  `model`, `system`, plus the derived `cost_usd: float | None`. Nested (not flat
  `gen_*`/`judge_*`) because `CallStats` is a reusable Pydantic sub-model — nesting keeps
  one schema definition reused twice and serializes to a clean
  `{"generation": {...}, "judge": {...}}` JSON shape, mapping 1:1 to two OTEL spans in
  Sprint 3.
- Answer payload: `answer` text + `sources: list[str]`.
- The **three aggregate judge floats**: `fact_recall`, `fact_precision`,
  `faithfulness_ratio` — each `float | None`, never coerced.
- `retrieval_ranked_ids: list[str]` — doc-level, deduplicated (the offline retrieval
  metrics input).
- Abstention booleans: `did_abstain_retrieval`, `did_abstain_e2e`.

**2. Embed-aggregates-not-verdict-lists rationale.** At 500 q × N models the
`per_fact` / `per_citation` lists dominate JSONL size, and the Phase-6 report never
drills into per-fact verdicts (that is a Sprint-3 observability concern). The 3 floats +
answer text satisfy every report section while keeping the artifact small and cloneable.
The floats are computed once during the run and persisted — never reconstructed by
re-running `aggregate`.

**3. Price-table-in-config cost model (FR-8, FR-9).**
`cost_usd = in_tok/1e6 * price_in + out_tok/1e6 * price_out`, read from
`RunConfig.prices` (never hardcoded). A model with **no price entry** → `cost_usd = None`
(rendered "N/A") + a loud warning, never a silent 0. Pinned table (per 1M tokens,
in/out): `gpt-5-nano-2025-08-07` `$0.05/$0.40` · `gpt-4o-mini` `$0.15/$0.60` ·
`claude-3-5-haiku-20241022` `$0.80/$4.00` · `claude-3-5-sonnet-20241022` `$3.00/$15.00`.
**Follow-up (AC-15):** the `gpt-5-nano-2025-08-07` price cites aggregator sources and
**must be verified against OpenAI's official pricing page** before the published run /
before ADR-0007 acceptance; record the confirmed figure in both `configs/baseline.yaml`
and ADR-0007. Cost is app-derived because `gen_ai.usage.cost_usd` is not a stable OTEL
attribute (per ADR-0004).

## Design Micro-Decisions (resolved; none reopen a DEFINE question)

1. **Generator selection — `system` enum + in-`runner.py` factory (NOT import-path
   string).** `RunConfig.models[].system` is a typed `Literal["openai","anthropic"]`
   (or `StrEnum`); `runner.py` holds `_GENERATOR_FACTORY = {"openai": OpenAIGenerator,
"anthropic": AnthropicGenerator}`. Typed, closed, offline-testable; no `importlib` /
   string eval. The judge is always `OpenAIJudge` in v1 (Q2).
2. **`EvalRecord` `CallStats` namespacing — nested `generation` / `judge`.** Two nested
   `CallStats` sub-models (`record.generation`, `record.judge`), not flat `gen_*`/`judge_*`.
   One `CallStats` definition reused twice; clean `{"generation":{…},"judge":{…}}` JSON;
   each maps 1:1 to a Sprint-3 OTEL span. `cost_usd` lives **on** each `CallStats`.
3. **Report structure — two `string.Template`s + three row-assembly helpers, pure
   render.** Named templates `_HTML_TEMPLATE` (one inline `<style>` block) and
   `_MD_TEMPLATE`. Helpers: `_summary_rows` (per-model mean judge floats + abstention
   P/R), `_per_category_rows` (feeds `aggregate_retrieval_metrics(qs, ranked_map, k)` for
   retrieval metrics + category-grouped judge-float means, all 10 categories), `_cost_rows`
   (per-model total `cost_usd`, mean `latency_s`, total tokens). Each helper assembles a
   table-string substituted into the template; `None` → `"N/A"` (never `0.0`). `report.py`
   makes **no** live call — pure function over the JSONL.
4. **YAML loader — rely on transitive `PyYAML` via `datasets`, use `yaml.safe_load`.** No
   explicit `pyyaml` pin. NFR-6 budgets exactly ONE new runtime dep (`anthropic`); adding
   `pyyaml` would be a second top-level dep for a transitively-present library. `import
yaml; yaml.safe_load(path.read_text())` is the call. **Hygiene note (surfaced, not
   blocking):** depending on a transitive dep is a mild risk if `datasets` ever drops
   `PyYAML`; if a reviewer prefers explicitness, a `pyyaml>=6.0` pin is a one-line
   hardening — but lean transitive to honor the one-dep budget. Recorded as consistency
   note C3 (LOW).
5. **`CallStats` + cost helper location — `eval/records.py`, unit-tested.** Confirms
   DEFINE FR-2/FR-8. `compute_cost_usd(stats: CallStats, price: Price | None) -> float |
None` lives beside `CallStats`; `None` price → `None` + `logger.warning`. Covered by
   parametrized `test_records.py` including the missing-price path (AC-10).

## Infrastructure Gaps

Three-layer deep scan. **No gap blocks `/implement`.** All flagged items are
known/sequenced in the DEFINE, not new blockers.

| Gap Type           | Area                                                                          | Detail                                                                                                                                                                                                                                                                                                                                                                                            | Recommendation                                                                                      |
| ------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Missing domain     | LLM cost / token accounting                                                   | None — cost accounting is a pure arithmetic helper over `CallStats` + a config price table (FR-8); the field conventions come from ADR-0004 (OTEL GenAI). Not a KB-domain-sized concern; no `/new-kb` warranted.                                                                                                                                                                                  | None.                                                                                               |
| Missing domain     | Anthropic tool-use structured output                                          | None — the tool-use call shape is a well-documented SDK pattern (canonical signature pinned in the DEFINE handoff). It mirrors `OpenAIGenerator`'s schema-as-SSoT path. No KB domain needed before `/implement`.                                                                                                                                                                                  | None (Context7 can confirm signature at `/implement` if desired).                                   |
| Missing domain     | HTML/MD report rendering                                                      | None — stdlib `string.Template` over assembled strings (Q4). No library, no KB domain.                                                                                                                                                                                                                                                                                                            | None.                                                                                               |
| Missing domain     | `observability` (OTEL/Langfuse)                                               | **DEFERRED to Sprint 3 (not a blocker).** Phase 6 emits no spans, runs no backend (NFR-3) — only the record _shape_ is OTEL-aligned, sourced from ADR-0004's field table. The deep research is archived for the Sprint-3 domain build.                                                                                                                                                            | None now; `/new-kb observability` lands in Sprint 3 / Phase 7.                                      |
| Missing concept    | `rag-eval` — eval-record schema, cost model, CallStats seam, report-rendering | `rag-eval` (draft) covers the judge layer, retrieval-metric aggregation, abstention scoring, and cassette/replay — but **not** the eval-record schema, cost-accounting model, the `CallStats`/`generate_with_stats` seam, or report rendering. **Known & sequenced** in the DEFINE as post-phase knowledge capture.                                                                               | `/update-kb rag-eval` **AFTER** this phase (not a blocker for `/implement`).                        |
| Missing specialist | eval / generation                                                             | No eval/generation specialist agent exists; existing agents are workflow/KB only. DEFINE concluded **not warranted yet** — single-pass orchestration over already-built primitives, no repeated specialist context across sessions. The Phase-5 "revisit IF Phase 6 surfaces repeated friction" condition has **not** triggered: the runner is one cohesive module set, not a recurring workflow. | None now; revisit only if Sprint-3 observability + a re-run/re-render loop create repeated context. |
| Hygiene note       | YAML loader dep                                                               | `PyYAML` arrives transitively via `datasets`/`huggingface_hub`; no explicit pin (micro-decision 4). Mild transitive-dependency risk, deliberately accepted to honor NFR-6's one-dep budget.                                                                                                                                                                                                       | Lean transitive + `yaml.safe_load`; optional `pyyaml>=6.0` pin if a reviewer prefers explicitness.  |

**Agent-alignment layer:** the relevant KB domains (`rag-eval`, `rag-retrieval`, and
`rag-generation`-equivalent via `generation/`) are all consumed `direct` in this phase; no
specialist agent's `kb_domains` needs updating because no specialist owns this work.
`code-reviewer` (`kb_domains: []`) handles `/review` and reads KB ad hoc. **Domain
existence:** every Phase-6 technology area is covered (`rag-eval` for judge/metrics/cost
shape, `rag-retrieval` for the single-retriever reuse, ADR-0004 for OTEL fields, ADR-0005
for the provider matrix, ADR-0006 for the cassette) — `observability` is the one future
domain, correctly deferred. **Verdict:** no `/new-kb` and no `/new-agent` blocks Phase 6.

## Consistency Check

Non-trivial, multi-module phase (>2 modules, 17 FR / 9 NFR / 19 AC) — full 6-pass run.
**Verdict: ✅ CONSISTENT** (no CRITICAL/HIGH; four LOW notes recorded).

| ID  | Severity | Pass                 | Location                                   | Finding                                                                                                                                                                                                                                                                                    | Suggested fix                                                                                                                                                                                                                                                                               |
| --- | -------- | -------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | LOW      | 3 Underspecification | FR-2 / `CallStats` `model`/`system` fields | FR-2 lists `CallStats(input_tokens, output_tokens, latency_s, model, system)` while FR-1 also stores `gen_ai.request.model` / `gen_ai.system` at the record level. Mild duplication between the nested `CallStats.model`/`.system` and the record-level OTEL fields.                       | Resolve in `records.py`: record-level `gen_ai.request.model`/`gen_ai.system` describe the **generation** call; each `CallStats` carries its own `model`/`system` (judge's may differ). Document the layering in the docstring. No conflict — intended redundancy for OTEL 1:1 span mapping. |
| C2  | LOW      | 6 Inconsistency      | FR-7 abstention P/R vs `abstention.py`     | FR-7(a) wants per-model "abstention precision/recall" in the summary, but `compute_abstention_metrics` operates over a `did_abstain_map` across a question **set**, not per-record. The report must rebuild the map from each model's records' `did_abstain_*` booleans before calling it. | In `report.py:_summary_rows`, group records by model, build `{question_id: did_abstain_e2e}`, then call `compute_abstention_metrics(qs, map)`. Reuse the Phase-5 scorer unchanged; the report just feeds it. Document the e2e-vs-retrieval choice (use e2e for the headline P/R).           |
| C3  | LOW      | 4 Constitution       | micro-decision 4 / YAML dep                | NFR-6 pins exactly ONE new runtime dep (`anthropic`). A `pyyaml` explicit pin would be a 2nd. Relying on transitive `PyYAML` honors the budget but is a mild hygiene risk if `datasets` drops it.                                                                                          | Lean transitive + `yaml.safe_load` (chosen). Surfaced as a hygiene note, not a budget violation — no second dep is added. Acceptable.                                                                                                                                                       |
| C4  | LOW      | 2 Ambiguity          | FR-11 / AC-13 "<30 min"                    | The `<30 min` exit criterion is a maintainer-run wall-time check on real hardware (the 8 GB Air vs a rented box), inherently environment-dependent — not a code-asserted gate.                                                                                                             | Keep as a maintainer milestone-run inspection (AC-13 already frames it as "verified by the maintainer's run wall-time"). `limit`-capped dev runs bound it. No code change.                                                                                                                  |

Pass-by-pass: **(1) Duplication** — no overlapping requirements; C1 is intended OTEL
redundancy (record-level generation model + per-`CallStats` model), not a conflict.
**(2) Ambiguity** — no unresolved TODO/???/placeholder; C4 ("<30 min") is a non-code
maintainer check, correctly framed in AC-13; "low single-digit USD" (NFR-9) is a bounded
sanity estimate, the binding control is the FR-13 ceiling. **(3) Underspecification** —
C1 (field layering); every other requirement has an object + a falsifiable AC.
**(4) Constitution alignment** — **no CRITICAL.** No speculative scope (Shoulds are
explicitly optional and named — FR-13/14/16); the one new seam (`generate_with_stats`)
is justified by a named change (Q3 + the runner's cost-capture need), not "in case";
`anthropic` is the one runtime dep justified by ADR-0005's named generator swap (NFR-6
upheld; C3 confirms no second dep); the offline-CI invariant holds (the Anthropic adapter
is the only `anthropic` importer, cassette-replayed under `record_mode="none"`, NFR-1);
`rag-ask` and the Protocols stay clean (NFR-4); no stranger-test leak (every design line
is about the system — the committed `results/baseline.{html,md}` teach a reader the
measured quality). **(5) Coverage** — every FR-1..17, NFR-1..9, AC-1..19 maps to ≥1
manifest entry (see the "Covers" column; AC-15 is a maintainer pre-publish note carried
on `configs/baseline.yaml` + ADR-0007; AC-13 is the milestone-run inspection; Should-tier
AC-16/17/18 map to `runner.py`/`cli.py`). No orphan manifest entries — `results/baseline.*`
is the FR-12/AC-12 artifact, `pyproject.toml`/`Makefile`/`.gitignore` carry the wiring FRs.
**(6) Inconsistency** — C2 (abstention P/R map rebuild); terminology otherwise consistent
(`CallStats`, `generate_with_stats`, `did_abstain_*`, "single retriever", "price table in
config", `ABSTAIN_ANSWER` sentinel SSoT used identically in DEFINE and DESIGN).

## Risks & Trade-offs

- **Anthropic tool-use schema drift (R1).** The forced-tool `input_schema` is
  `AnswerWithSources.model_json_schema()`; if Anthropic's tool-use response shape changes,
  the cassette and the fake-client test drift from live behavior. Mitigation: the adapter
  re-validates the `tool_use` block through Pydantic (a `ValidationError` surfaces drift,
  not a silent wrong answer); the cassette re-records via `VCR_RECORD_MODE=once`.
  Documented as the ADR-0005 named swap's adapter risk. Accepted.
- **Same-family judge bias (R2).** `OpenAIJudge` on `gpt-5-nano` scores OpenAI-generated
  answers in v1 (Q2) — a potential same-family inflation. Mitigation: the report's
  methodology section states the caveat explicitly; `ClaudeJudge` is the named ADR-0005
  fast-follow behind the `Judge` seam. This is a deliberate scope cut, not a defect.
- **`gpt-5-nano` price credibility (R3).** The aggregator-sourced `$0.05/$0.40` gates the
  published numbers' credibility (AC-15). Mitigation: a pre-publish verification against
  the official OpenAI page; config + ADR-0007 are reversible if it differs. Bounds a
  portfolio-trust risk, not a code risk.
- **JSONL flush cost under sequential 500-q run (R4).** Flushing per question is the
  crash-safe checkpoint (Decision 3-C) but adds 500×N `fsync`-ish writes. At this scale
  (one open file handle, append + flush) it is negligible vs LLM latency; the FR-14
  `--concurrency` Should addresses wall-time, not flush overhead. Accepted.
- **Transitive `PyYAML` (R5, = C3).** Relying on `datasets`'s transitive `PyYAML` honors
  the one-dep budget but couples config parsing to a transitive dep. Low-likelihood
  (`PyYAML` is deeply entrenched in the HF stack); a one-line explicit pin is the cheap
  hardening if ever needed. Accepted, surfaced.

**ADRs warranted:** ADR-0007 (eval-record schema + cost model — written this phase,
FR-17, content outline above). No other new ADR: ADR-0004 (OTEL fields), ADR-0005
(provider matrix), ADR-0006 (cassette) are reused; the `AnthropicGenerator` is the
ADR-0005 named swap, not a new decision.

## Next Step

→ `/implement sprint-2/phase-6-multimodel-report` — no gaps block implementation.
Sequence the commits exactly as in Implementation Phases (CallStats+stats methods FIRST,
the milestone run LAST). Verify the `gpt-5-nano` price (AC-15) before the published run.
The `/update-kb rag-eval` knowledge-loop item (eval-record schema, cost model, CallStats
seam, report rendering) runs AFTER the phase.
