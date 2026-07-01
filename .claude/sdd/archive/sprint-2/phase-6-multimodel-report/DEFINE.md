# DEFINE: sprint-2/phase-6-multimodel-report — Multi-Model Runner & Baseline Report

**Sprint/Phase:** sprint-2/phase-6-multimodel-report | **Date:** 2026-05-25

## Resolved Open Questions

The BRAINSTORM closed Q2/Q3/Q5/Q6/Q8 and Decision 2 as **fixed inputs** (Decisions 1–4
plus the consumed deep-research outcome). Q1/Q4/Q7 were left to `/define` under explicit
user delegation (lean path, ~$0 budget, config-level + reversible — not high-stakes). All
eight are recorded here so `/design` and `/implement` treat them as fixed — do **not**
re-open them.

- **Q1 — Baseline model set + price table (resolved under delegation).** `configs/baseline.yaml`
  ships the **cheapest cross-family pair**: OpenAI generator `gpt-5-nano-2025-08-07` +
  Anthropic generator `claude-3-5-haiku-20241022`, judge = **`OpenAIJudge`** on
  `gpt-5-nano-2025-08-07` (the existing `eval/openai_judge.py:28` `DEFAULT_MODEL`).
  `claude-3-5-sonnet-20241022` is a commented optional (Could). Price table (per 1M
  tokens, input / output), lifted from the BRAINSTORM Deep-research outcome →
  carried into ADR-0007: `gpt-5-nano-2025-08-07` `$0.05 / $0.40` · `gpt-4o-mini`
  `$0.15 / $0.60` · `claude-3-5-haiku-20241022` `$0.80 / $4.00` ·
  `claude-3-5-sonnet-20241022` `$3.00 / $15.00`. **Caveat (AC-15):** the
  `gpt-5-nano-2025-08-07` price cites aggregator sources and **must be verified against
  OpenAI's official pricing page** before the published baseline run / before ADR-0007 is
  accepted. Prices live in config (per FR-9), never hardcoded.
- **Q2 — Cross-family judge = FAST-FOLLOW (Won't this phase, fixed).** `OpenAIJudge`
  scores **both** generators in v1; the same-family caveat (an OpenAI judge rating
  OpenAI-generated answers) is stated in the report's methodology section. `ClaudeJudge`
  is the named ADR-0005 swap behind the `Judge` Protocol seam (`eval/interfaces.py`) and
  is explicitly deferred — ADR-0005 enables it, Phase 6 does not build it.
- **Q3 — Cost/latency seam = augmented methods on implementations (Approach C, fixed).**
  Add `generate_with_stats(...) -> (AnswerWithSources, CallStats)` /
  `judge_with_stats(...) -> (JudgeVerdict, CallStats)` on the **implementations**
  (`OpenAIGenerator`, `AnthropicGenerator`, `OpenAIJudge`, plus the stubs), **not** on the
  `Generator` / `Judge` Protocols. The Protocols stay clean; `rag-ask` (`generation/cli.py`)
  is untouched. `CallStats` reads `response.usage` (OpenAI) / the Anthropic `usage` block.
- **Q4 — Report rendering lib = Python stdlib `string.Template` (resolved under
  delegation, NO new dep).** The report is two static files with a fixed section set
  (summary, per-category table, per-model cost/latency). `string.Template` over assembled
  table strings plus an inline `<style>` block is sufficient and respects dependency
  hygiene (NFR-6). Jinja2 (`jinja2>=3.0`) is **rejected** — adding a runtime dep for
  loop/conditional template syntax is disproportionate at this report's complexity, and
  the augmentation is already carrying the one justified runtime dep (`anthropic`).
- **Q5/Q8 — Record shape = OTEL GenAI conventions per ADR-0004 (fixed + `/define`
  pins the field list).** `CallStats` / `EvalRecord` fields follow ADR-0004's table:
  `gen_ai.request.model`, `gen_ai.system`, `gen_ai.operation.name`,
  `gen_ai.usage.input_tokens` / `output_tokens`, app-derived `cost_usd`; offline scores
  as `gen_ai.evaluation.{name, score.value, score.label, explanation}`. **Decision
  (`/define`):** the persisted `EvalRecord` embeds the **3 aggregate judge floats +
  abstention booleans + the answer text**, **not** the verbose `per_fact` / `per_citation`
  lists — see FR-1 for the exact field list and the size/drill-down rationale.
- **Q6 — Single shared retriever; the Phase-5 gold-aware corpus is THE eval corpus
  (fixed).** The `HybridRetriever` is **built/loaded once** via
  `pipeline.load_retriever()` and **reused across all models** (retrieval is
  model-agnostic — only the generator swaps). The runner does **not** reload the index
  per model. `make eval-baseline` **fails fast with a helpful message** if the gold-aware
  index is missing (a reviewer must run `make build-index-gold` first — FR-10, AC-11).
- **Q7 — Commit `results/baseline.{html,md}` (resolved under delegation: YES).**
  Un-gitignore exactly those two files via `.gitignore` negation
  (`!results/baseline.html`, `!results/baseline.md`) and commit the first real run — the
  published portfolio artifact passes the stranger test (it teaches a reader about the
  system's measured quality). All run-specific JSONL (`results/<run_id>.jsonl`) stays
  gitignored. See FR-12, AC-12.
- **Decision 2 — Second family = `AnthropicGenerator`, native SDK (Must, fixed).**
  `anthropic>=0.40,<1.0` is the **one new runtime dependency** this phase (justified by
  ADR-0005's cross-family generator mandate). Structured output is via Anthropic tool-use
  (not `response_format`). Ollama via OpenAI `base_url` stays a **Could** (FR/AC mark it
  out-of-must). This is the only added runtime dep — contrast Phase 5, which added only a
  dev dep (`vcrpy`).
- **ADR-0007 (fixed, written this phase).** `docs/adr/0007-eval-record-schema.md`
  (eval-record schema + cost-accounting model) is authored in Phase 6 at decision time
  (proposed → accepted), referencing ADR-0004's OTEL field conventions. ADR-0004 is
  already drafted (proposed); Phase 6 does **not** rewrite it.

These are **confirmed inputs** for the fixed items (Q2/Q3/Q5/Q6/Q8, Decision 2, ADR-0007).
Q1/Q4/Q7 are **resolved-under-delegation** — config-level and reversible, decided like
Phase 5 resolved Q4/Q5; no `AskUserQuestion` round was needed (see Clarity Score).

## Requirements

### Functional

- **FR-1 (`EvalRecord` dataclass + JSONL persistence)** — A new `EvalRecord` (pydantic
  model or frozen dataclass) in `eval/records.py`, one record **per question per model**,
  written as JSON lines to `results/<run_id>.jsonl`, **flushed after each question**
  (crash-safe checkpoint, Decision 3 = Approach C). Field list, shaped to the ADR-0004
  OTEL GenAI conventions and **embedding aggregates + answer text, not the verbose verdict
  lists** (Q5 decision):
  `question_id`, `category`, `run_id`; `gen_ai.request.model` (the generator model id),
  `gen_ai.system` (`openai` | `anthropic`), `gen_ai.operation.name` (`chat`);
  `gen_ai.usage.input_tokens` / `output_tokens` and derived `cost_usd` for **both** the
  generation call and the judge call (two `CallStats`, namespaced e.g.
  `generation.*` / `judge.*`); `latency_s` per call; the answer text and `sources` list;
  the **three aggregate judge floats** (`fact_recall`, `fact_precision`,
  `faithfulness_ratio` — each `float | None`, never coerced); the deduplicated
  `retrieval_ranked_ids` (doc-level, for the offline retrieval metrics); and the
  `did_abstain` booleans (retrieval-level + end-to-end). **Rationale for excluding
  `per_fact` / `per_citation`:** at 500 q × N models those lists dominate the JSONL size,
  and the Phase-6 report does not drill into per-fact verdicts (that is a Sprint-3
  observability concern); the 3 floats + answer text satisfy every report section while
  keeping the artifact small and cloneable. The judge floats are reconstructed by
  re-running `eval.aggregate.aggregate` is **not** needed — they are computed once during
  the run and persisted.
- **FR-2 (`CallStats` record + `generate_with_stats` / `judge_with_stats`)** — A shared
  `CallStats` dataclass (`input_tokens: int`, `output_tokens: int`, `latency_s: float`,
  `model: str`, `system: str`) in `eval/records.py` (or a shared module), with field names
  aligned to the OTEL GenAI conventions (Q5/Q8). Each **implementation** gains an augmented
  method (Q3 = Approach C, Protocols unchanged):
  `OpenAIGenerator.generate_with_stats(...) -> (AnswerWithSources, CallStats)` reads
  `response.usage` (`prompt_tokens` / `completion_tokens`); `OpenAIJudge.judge_with_stats(...)
-> (JudgeVerdict, CallStats)` does the same; `AnthropicGenerator.generate_with_stats(...)`
  reads the Anthropic `usage.input_tokens` / `output_tokens`. `StubGenerator` /
  `StubJudge` gain trivial zeroed-`CallStats` variants for offline tests. The base
  `generate` / `judge` Protocol methods and `rag-ask` are untouched (NFR-4).
- **FR-3 (`AnthropicGenerator`)** — `generation/anthropic_generator.py` implements the
  `Generator` Protocol (the named ADR-0005 / `generation/interfaces.py` swap) via Anthropic
  **tool-use** structured output for `AnswerWithSources` (Anthropic has no
  `response_format`; the adapter declares a tool whose schema is
  `AnswerWithSources.model_json_schema()` and extracts the `tool_use` block, re-validating
  through Pydantic exactly as `OpenAIGenerator` does). Default model
  `claude-3-5-haiku-20241022`, overridable via env var (mirroring `RAG_GEN_MODEL`). A clean
  `RuntimeError` is raised when `ANTHROPIC_API_KEY` is unset (mirroring
  `OpenAIGenerator.__init__`). `anthropic>=0.40,<1.0` is added as a runtime dep (NFR-6).
- **FR-4 (`RunConfig` + `configs/baseline.yaml`)** — A `pydantic` model `RunConfig` in
  `eval/config.py` parsing a YAML file with: a `models` list (each entry: `model_id`,
  `system` = `openai`|`anthropic`, generator class selector), `judge_model`, `limit`
  (question-subset cap for dev; `null` = full 500), `k` (retrieval cutoff, default 10),
  `output_dir`, `run_id`, the per-model `prices` table (per-1M input/output), and
  `cost_ceiling_usd` (Should, FR-13). `configs/baseline.yaml` is committed with the Q1
  model set (≥1 OpenAI generator + 1 Anthropic generator) and the pinned price table.
- **FR-5 (End-to-end multi-model runner)** — A runner in `eval/runner.py` that, given a
  `RunConfig`, **loads the retriever once** (`pipeline.load_retriever()`, Q6 — never per
  model), then for each model, for each `load_questions(limit)` question:
  retrieve → assemble context (`ContextAssembler`) → `generate_with_stats` →
  `judge_with_stats` → compute the deduplicated `retrieval_ranked_ids` → determine
  `did_abstain` (retrieval-level `[] ` and end-to-end `answer == ABSTAIN_ANSWER and
sources == []`) → build and flush an `EvalRecord` to JSONL. **Sequential** in the Must
  tier (`--concurrency` is a Should, FR-14). The runner imports the abstention sentinel
  via the SSoT path (`from enterprise_rag_ops.generation.cli import ABSTAIN_ANSWER`,
  NFR-5).
- **FR-6 (`rag-eval` console script + `run` sub-command)** — `eval/cli.py:main` is wired
  as the `rag-eval` console script in `pyproject.toml [project.scripts]`. The sub-command
  `rag-eval run --config configs/baseline.yaml` parses the `RunConfig`, drives FR-5, then
  renders the report (FR-7) at the end of the same invocation (Decision 3 = Approach C:
  one user-facing command, JSONL checkpoint for free).
- **FR-7 (HTML + Markdown report renderer)** — `eval/report.py` reads a `results/<run_id>.jsonl`
  and produces `results/baseline.html` + `results/baseline.md` (stdlib `string.Template`,
  Q4). Sections: (a) overall summary per model (mean fact_recall / fact_precision /
  faithfulness, abstention precision/recall); (b) **per-category breakdown across all 10
  question categories**, fed by the existing `aggregate_retrieval_metrics`
  (`eval/retrieval_eval.py`) for retrieval metrics and category-grouped judge-float means;
  (c) a **per-model cost + latency table** (total `cost_usd`, mean `latency_s`, total
  tokens). Roll-ups **skip `None`** (never coerce to 0) and render `None` cells as **"N/A"**
  (NFR-2). The methodology section states the same-family-judge caveat (Q2).
- **FR-8 (Cost accounting)** — The runner computes `cost_usd` per call from
  `CallStats.input_tokens` / `output_tokens` and the `RunConfig` price table
  (`cost = in_tok/1e6 * price_in + out_tok/1e6 * price_out`). A model with **no price
  entry** logs a loud warning and continues with `cost_usd = None` (rendered "N/A"), never
  a silent 0. The cost formula lives in one helper and is unit-tested (FR-15).
- **FR-9 (Price table in config, not hardcoded)** — Per-model per-1M input/output prices
  are read from `RunConfig.prices` (FR-4), never literal in code. The committed
  `configs/baseline.yaml` carries the Q1 table; ADR-0007 documents the table + the
  derivation model.
- **FR-10 (Gold-aware-index fail-fast)** — `make eval-baseline` (and the `rag-eval run`
  entry, defensively) checks that the gold-aware index artifacts exist (`config.LANCEDB_DIR`,
  `config.BM25_INDEX_DIR`, `config.CHUNK_ORDER_PATH`) and **fails fast with a helpful
  message** naming `make build-index-gold` when they are missing — never a raw stack trace
  from `load_retriever` (Q6).
- **FR-11 (`make eval-baseline` target + exit criterion)** — A `make eval-baseline` target
  runs `uv run rag-eval run --config configs/baseline.yaml`. **Exit criterion:** it runs
  the full 500 questions for one model (or a `limit`-capped subset for dev) in **<30 min**,
  the report contains the per-category breakdown across all 10 categories, and cost +
  latency are visible per model.
- **FR-12 (Published baseline committed)** — `results/baseline.html` and
  `results/baseline.md` are un-gitignored via `.gitignore` negation
  (`!results/baseline.html`, `!results/baseline.md`) and the first real run's output is
  committed as the portfolio artifact (Q7). Run-specific `results/<run_id>.jsonl` stays
  gitignored.
- **FR-13 (Cost-overrun guard) — Should.** The runner accumulates `cost_usd` and, after
  each question, warns + optionally halts when it exceeds `RunConfig.cost_ceiling_usd`.
  Absence does not fail the phase.
- **FR-14 (Concurrent runner) — Should.** An opt-in `--concurrency N` flag runs N
  questions in parallel (`ThreadPoolExecutor`); sequential is the Must-tier default.
  JSONL flush stays crash-safe under concurrency. Absence does not fail the phase.
- **FR-15 (Unit + cassette tests, mirrored)** — Mirrored test files cover every new
  module: `EvalRecord` round-trip serialization/deserialization; `CallStats` cost
  arithmetic (incl. the no-price-entry → `None` path); `RunConfig` YAML parsing;
  `report.py` (given a hand-built JSONL, assert each rendered section, the 10-category
  breakdown, and `None`-as-"N/A"); `AnthropicGenerator` call shape against a **fake
  Anthropic client** (offline, no key); and a **cassette test** for the `AnthropicGenerator`
  live call (one recorded cassette in `tests/eval/cassettes/`, replayed offline under the
  `vcr` marker per ADR-0006). All run under `make test` (no key, no network).
- **FR-16 (`rag-eval report` sub-command) — Should.** `rag-eval report --results
results/<run_id>.jsonl` re-renders the report from an existing JSONL without re-running
  the eval — a thin CLI wrapper over `eval/report.py`. Absence does not fail the phase.
- **FR-17 (ADR-0007 written)** — `docs/adr/0007-eval-record-schema.md` is authored
  (proposed → accepted) documenting the `EvalRecord` JSONL schema (the FR-1 field list,
  OTEL-aligned), the embed-aggregates-not-verdict-lists decision, and the
  price-table-in-config cost-accounting model; it references ADR-0004's field conventions
  and notes the `gpt-5-nano` price-verification follow-up.

### Non-functional

- **NFR-1 (Offline `make test` — no network, no key)** — `make test` (`-m "not corpus and
not smoke"`) runs every Phase-6 unit test and the `AnthropicGenerator` **cassette** test
  with **no network I/O** and **no `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`**. The live
  multi-model path is cassette-replayed (ADR-0006, `record_mode="none"` default) or
  stub-driven. The eval LLM response is **never mocked for an assertion** (CLAUDE.md) —
  record/replay only. `vcrpy>=6.0,<7.0` and the `vcr` marker already exist (Phase 5).
- **NFR-2 (None=N/A propagates into report roll-ups)** — The `None` empty-denominator
  convention from `JudgeVerdict` / `eval/aggregate.py` and the retrieval metrics
  (`recall_at_k`/`precision_at_k`/`mrr`/`ndcg_at_k` return `float | None`) **propagates
  unchanged** into the report: category and per-model averages **skip `None`** (mirroring
  `aggregate_retrieval_metrics`), never coerce to `0.0`, and `None` cells render as **"N/A"**.
- **NFR-3 (Forward-compatible OTEL-shaped records)** — `CallStats` / `EvalRecord` field
  names map 1:1 to ADR-0004's OTEL GenAI conventions so the Sprint-3 observability
  exporter is an additive remap, not a rewrite. Phase 6 emits **no** OTEL spans and runs
  **no** tracing backend (that is Sprint 3 / Phase 7) — only the record _shape_ is
  constrained (Decision 4).
- **NFR-4 (Protocols stay clean; `rag-ask` untouched)** — `generate_with_stats` /
  `judge_with_stats` live on the **implementations only**, never on the `Generator` /
  `Judge` Protocols (Q3 = Approach C). `generation/cli.py` (`rag-ask`) and the existing
  Protocol contracts are unchanged; no tuple-unpack ripples into the generation CLI.
- **NFR-5 (Sentinel as imported SSoT)** — The runner / abstention path imports
  `ABSTAIN_ANSWER` from `generation/cli.py` (re-exported from `generation/schema.py`),
  never hardcoding the string — reusing the Phase-5 `eval/abstention.py` precedent.
- **NFR-6 (Dependency hygiene)** — Exactly **one new runtime dependency**:
  `anthropic>=0.40,<1.0` (justified by ADR-0005's cross-family generator mandate — the
  named seam swap). **No** report-lib dep (Q4 = stdlib `string.Template`). **No** new dev
  dep (`vcrpy` already present from Phase 5). No eval-framework library, no LangChain.
- **NFR-7 (Determinism)** — `gpt-5-nano-2025-08-07` rejects an explicit `temperature`
  (left at model default, as in `OpenAIGenerator` / `OpenAIJudge`); Claude is
  temperature-capable (`AnthropicGenerator` may set `temperature=0`), but cross-run
  reproducibility rests on the deterministic prompt builders + the committed cassettes,
  not on provider-side determinism guarantees.
- **NFR-8 (Conventions + mirrored tests)** — New code lives under `eval/` (records,
  config, runner, report, cli) and `generation/` (anthropic*generator) with a mirrored
  `tests/<pkg>/test*<module>.py`for every new module. ADRs use YYYY-MM-DD dates and
  English; commits follow Conventional Commits;`make lint test` passes. Stranger test
  holds — no career/personal content in any tracked Phase-6 file.
- **NFR-9 (Cost reality — published baseline is a real milestone run, bounded)** — The
  **published** `results/baseline.{html,md}` is a real paid run the maintainer executes
  **once**: ~500 q × (1 generation + 1 judge call) × the Q1 model set at the pinned prices
  ≈ **low single-digit USD** (well under the $50/cycle ceiling; the cheapest pair keeps it
  near ~$1–3). Dev runs are `limit`-capped (FR-4). The cost-overrun guard (FR-13, Should)
  bounds accidental spend. This live milestone run is **distinct** from the test suite:
  the test suite is fully offline (NFR-1) via the one recorded `AnthropicGenerator`
  cassette — no test ever issues a live call.

## Acceptance Criteria

1. `EvalRecord` (`eval/records.py`) serializes to one JSON line per question per model and
   round-trips losslessly; its fields match the FR-1 OTEL-aligned list and **exclude** the
   `per_fact` / `per_citation` lists (embedding the 3 aggregate floats + answer text +
   abstention booleans + dedup'd `retrieval_ranked_ids` instead). Verified by a
   serialize→parse unit test asserting field presence and the verdict-list exclusion.
2. The runner **flushes each `EvalRecord` to `results/<run_id>.jsonl` after the question is
   processed** (crash-safe checkpoint): a run interrupted after question _m_ leaves _m_
   complete JSON lines on disk. Verified by a unit test that processes a small question set
   with a stub generator/judge and asserts the JSONL line count after a simulated early
   stop.
3. `CallStats` (`eval/records.py`) carries `input_tokens`, `output_tokens`, `latency_s`,
   `model`, `system` with OTEL-aligned names; `OpenAIGenerator.generate_with_stats` and
   `OpenAIJudge.judge_with_stats` return `(result, CallStats)` reading `response.usage`,
   and `AnthropicGenerator.generate_with_stats` reads the Anthropic `usage` block. The base
   `generate` / `judge` Protocol methods and `generation/cli.py` are unchanged. Verified by
   unit tests on `OpenAIGenerator`/`OpenAIJudge` with a fake client returning a `usage`
   payload, plus a grep-style assertion that `Generator`/`Judge` Protocols in
   `interfaces.py` are unmodified.
4. `AnthropicGenerator` (`generation/anthropic_generator.py`) implements the `Generator`
   Protocol via Anthropic tool-use, extracts `AnswerWithSources` from the `tool_use` block,
   re-validates through Pydantic, and raises a clean `RuntimeError` when `ANTHROPIC_API_KEY`
   is unset. Verified by an **offline** unit test against a fake Anthropic client (no key,
   no network) asserting the returned `AnswerWithSources`.
5. A **committed cassette** in `tests/eval/cassettes/` lets the `AnthropicGenerator` live
   call replay offline under the `vcr` marker; the test passes under `make test` with **no
   `ANTHROPIC_API_KEY` and no network** (`record_mode="none"`, ADR-0006). Verified by
   running `make test` with the key unset and the network blocked.
6. `RunConfig` (`eval/config.py`) parses `configs/baseline.yaml` into a typed model with
   `models` (≥1 OpenAI + ≥1 Anthropic generator), `judge_model`, `limit`, `k`,
   `output_dir`, `run_id`, `prices`, and `cost_ceiling_usd`. Verified by a unit test
   parsing a hand-built YAML and asserting the typed fields; a malformed YAML raises a
   typed `ValidationError`.
7. The runner (`eval/runner.py`) **loads the retriever exactly once** and reuses it across
   all models (Q6). Verified by a unit test that patches `pipeline.load_retriever` and
   asserts it is called **once** for a 2-model run (not once per model).
8. `rag-eval run --config configs/baseline.yaml` (the `rag-eval` console script wired in
   `pyproject.toml`) drives the runner and writes both `results/baseline.html` and
   `results/baseline.md` in one invocation. Verified by an offline integration test driving
   the CLI with stub generators/judge over a tiny question set and asserting both files
   exist with the expected sections.
9. The report (`eval/report.py`) renders, for a hand-built JSONL: (a) a per-model summary;
   (b) a **per-category breakdown listing all 10 question categories**; (c) a per-model
   **cost + latency** table. `None` aggregates are **skipped in the mean** (not averaged as 0) and rendered as **"N/A"** cells. Verified by a unit test over a fixture JSONL
   containing at least one `None` metric, asserting the "N/A" cell and the 10-category rows.
10. Cost accounting (FR-8): `cost_usd` for a call equals
    `in_tok/1e6 * price_in + out_tok/1e6 * price_out` from the config price table; a model
    with no price entry yields `cost_usd = None` (rendered "N/A") + a logged warning, never
    a silent 0. Verified by parametrized unit tests on the cost helper, including the
    missing-price path.
11. `make eval-baseline` (and the `rag-eval run` entry defensively) **fails fast with a
    helpful message naming `make build-index-gold`** when the gold-aware index artifacts
    are absent — no raw `load_retriever` stack trace. Verified by a unit/integration test
    that invokes the entry with the index dir absent and asserts the guarded error message.
12. `results/baseline.html` and `results/baseline.md` are un-gitignored via `.gitignore`
    negation (`!results/baseline.html`, `!results/baseline.md`) and the first real run's
    output is committed; `results/<run_id>.jsonl` remains gitignored. Verified by inspecting
    `.gitignore` and `git status` after the milestone run (the two report files tracked, the
    JSONL untracked).
13. **Exit criterion (FR-11):** `make eval-baseline` runs the full 500 questions for one
    model (or a `limit`-capped subset for dev) in **<30 min**; the report contains the
    per-category breakdown across all 10 categories; cost and latency are visible per model.
    Verified by the maintainer's milestone run wall-time + an inspection of the rendered
    report.
14. `docs/adr/0007-eval-record-schema.md` is written (proposed → accepted): it documents the
    `EvalRecord` JSONL schema (OTEL-aligned, aggregates-not-verdict-lists), the
    price-table-in-config cost-accounting model, references ADR-0004's field conventions,
    and records the `gpt-5-nano` price-verification follow-up.
15. **Price-verification note:** before the published baseline run / ADR-0007 acceptance,
    the `gpt-5-nano-2025-08-07` per-1M price (`$0.05 / $0.40`, aggregator-sourced) is
    verified against OpenAI's official pricing page and the value in `configs/baseline.yaml`
    - ADR-0007 reflects the confirmed figure. Recorded as an acceptance note (config is
      reversible; this gates the published-numbers credibility, not the code).
16. (Should) Cost-overrun guard (FR-13): the runner warns + optionally halts when
    accumulated `cost_usd` exceeds `cost_ceiling_usd`. Verified by a unit test driving
    synthetic `CallStats` past a low ceiling. Absence does not fail the phase.
17. (Should) `--concurrency N` (FR-14) runs questions in parallel with crash-safe JSONL
    flushing; sequential is the default. Verified by a unit test asserting record count and
    JSONL integrity under concurrency. Absence does not fail the phase.
18. (Should) `rag-eval report --results results/<run_id>.jsonl` (FR-16) re-renders the
    report from an existing JSONL without re-running the eval. Verified by an offline test
    re-rendering a fixture JSONL. Absence does not fail the phase.
19. **Offline-CI invariant (NFR-1):** `make lint test` passes with **no API key and no
    network** — every Phase-6 test (incl. the Anthropic cassette) runs under
    `-m "not corpus and not smoke"`. Verified in CI on the PR.

## Clarity Score

| Dimension   | Score | Note                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem     | 3     | Root cause explicit with evidence: Phases 4–5 built every scoring primitive (`OpenAIJudge`, `aggregate`, `retrieval_metrics`, `abstention`, gold-aware corpus) but **nothing runs them end-to-end, tracks cost, or assembles a report** — `OpenAIGenerator`/`OpenAIJudge` even discard `response.usage` today. Phase 6 closes the gap and produces the Sprint-2 exit artifact (first published baseline numbers a reviewer inspects).                                                                                       |
| Users       | 2     | Consumers are the maintainer (running `make eval-baseline`, calibrating the model matrix) and the reviewer/hiring manager who reads the committed `results/baseline.{html,md}`. Internal eval-harness phase — no external end-user workflow — so workflow-impact is inherently thin, scored honestly and consistently with Phases 1–5 (Phase 5 also scored Users 2).                                                                                                                                                        |
| Success     | 3     | 19 numbered, falsifiable acceptance criteria, each with a concrete pass/fail check covering every FR/NFR: `EvalRecord` round-trip + crash-safe flush, the `CallStats` seam + Protocol-untouched assertion, the Anthropic adapter + cassette, single-retriever reuse, the gold-aware fail-fast, cost arithmetic incl. missing-price, the 10-category + "N/A" report assertions, the committed-artifact `.gitignore` check, ADR-0007, the offline-CI invariant, and the Should tier marked "absence does not fail the phase." |
| Scope       | 3     | Full MoSCoW (12 Musts, 4 Shoulds, Could/Won't) in the BRAINSTORM with an explicit Won't list (`ClaudeJudge`/cross-family judge, async streaming, Streamlit dashboard, per-fact supporting-doc mapping, full 512K-corpus encode, OTEL instrumentation). Budget relaxed for correctness (as Phase 5); Could items (Ollama, nDCG-in-report) and Shoulds bounded explicitly.                                                                                                                                                    |
| Constraints | 3     | All constraints named as NFRs: offline `make test` no-key (NFR-1), None=N/A propagation (NFR-2), forward-compatible OTEL shape with no spans (NFR-3), clean Protocols / untouched `rag-ask` (NFR-4), imported sentinel SSoT (NFR-5), dependency hygiene = exactly one runtime dep `anthropic` (NFR-6), determinism caveats per provider (NFR-7), conventions + mirrored tests (NFR-8), bounded real-run cost vs offline test suite (NFR-9).                                                                                 |

**Total: 14/15 — PASS (≥12).** Users scored 2: an internal eval-harness phase whose
"users" are the maintainer and a portfolio reviewer, so workflow-impact is inherently thin —
acceptable, not a blocker, and consistent with the Phase 1–5 DEFINEs. All eight BRAINSTORM
open questions are resolved: Q2/Q3/Q5/Q6/Q8 + Decision 2 + ADR-0007 are **fixed inputs**;
Q1/Q4/Q7 were **resolved under delegation** (config-level, reversible, ~$0 budget — decided
exactly as Phase 5 resolved Q4/Q5). No ambiguity was invented beyond what the BRAINSTORM
closed, so **no `AskUserQuestion` round was needed**. The one acceptance note that depends on
external action (AC-15, verify `gpt-5-nano` price) is correctly framed as a pre-publish check
on reversible config, not an open design question.

## Infrastructure Readiness

| Dependency | KB domain | Specialist | Status |
| -------------------------------------------------------- | ----------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `anthropic` Python SDK (`AnthropicGenerator`) | `rag-generation` | none | **New runtime dep — `anthropic>=0.40,<1.0`.** The one added runtime dependency (NFR-6), justified by ADR-0005's cross-family generator mandate (the named `generation/interfaces.py` seam swap). Tool-use structured-output shape is well-documented in the Anthropic SDK; no `/new-kb` blocks `/define`. Context7 can confirm the exact tool-use call signature at `/design`/`/implement`. |
| `OpenAIGenerator` / `OpenAIJudge` (Phases 3/4) | `rag-generation` / `rag-eval` | none | Ready — both exist and currently discard `response.usage`; FR-2 adds `generate_with_stats` / `judge_with_stats` reading it. `DEFAULT_MODEL = gpt-5-nano-2025-08-07` in both. Reused + augmented, Protocols untouched. |
| `AnswerWithSources` + `ABSTAIN_ANSWER` (Phase 3) | `rag-generation` | none | Ready — `AnswerWithSources` in `generation/schema.py`; `ABSTAIN_ANSWER` canonically in `generation/schema.py`, re-exported via `generation/cli.py:__all__`. The runner imports the sentinel from `generation/cli.py` (NFR-5). Reused unchanged. |
| `aggregate` + `aggregate_retrieval_metrics` (Phases 4/5) | `rag-eval` | none | Ready — `eval/aggregate.py:aggregate` and `eval/retrieval_eval.py:aggregate_retrieval_metrics` (None-skipping, per-category, dedup-before-metrics) are the report's roll-up entry points (FR-7). Reused unchanged. |
| `recall@k`/`precision@k`/`mrr`/`ndcg@k` (Phase 5) | `rag-eval` / `rag-retrieval` | none | Ready — `eval/retrieval_metrics.py` returns `float                                                                                                                                                                                                                                                                                                                                                                                                       | None`; `ndcg_at_k` already computed and surfaceable in the per-category breakdown (the Could from the BRAINSTORM is additive, not new code). Reused unchanged. |
| `compute_abstention_metrics` + e2e/retrieval scorers | `rag-eval` | none | Ready — `eval/abstention.py` (`evaluate_retrieval_abstention`, `evaluate_e2e_abstention`) is fed by the runner per question. Reused unchanged. |
| `pipeline.load_retriever` + gold-aware index (Phase 5) | `rag-retrieval` | none | Ready — `load_retriever()` builds the maps from the chunk-order sidecar + LanceDB (no corpus re-read, Phase-5 FR-9). Built once + reused (Q6); `make eval-baseline` fail-fast guards its absence (FR-10). A reviewer runs `make build-index-gold` first. |
| `load_questions` (Phase 4) | `rag-eval` | none | Ready — `eval/questions.py:load_questions(limit, ...)` streams the 500-question set at the pinned `DATASET_REVISION`; the runner's `limit` flows straight through. Reused unchanged. |
| `pydantic` (RunConfig + EvalRecord) | none needed | none | Ready — already a runtime dep (`pydantic>=2.6,<3.0`). No new dep. |
| YAML parsing (`RunConfig`) | none needed | none | Ready — `datasets`/`huggingface_hub` pull `PyYAML` transitively; if a direct `pyyaml` pin is preferred, `/design` decides. No new top-level runtime dep is expected for YAML. |
| Report rendering lib | none needed | none | **Resolved — stdlib `string.Template`, NO new dep (Q4).** Jinja2 rejected. Decision is final for `/design`. |
| `vcrpy` + `vcr` marker (cassette/replay) | `rag-eval` | none | Ready — `vcrpy>=6.0,<7.0` already a dev dep (Phase 5); `vcr` marker registered; `make test` (`-m "not corpus and not smoke"`) replays cassettes offline by default. The `AnthropicGenerator` cassette (FR-15/AC-5) follows ADR-0006. No new dep. |
| ADR-0004 (observability tool, field conventions) | `observability` | none | Ready (proposed) — `docs/adr/0004-observability-tool.md` supplies the OTEL GenAI field table the records mirror (NFR-3). Not rewritten this phase; acceptance deferred to Sprint 3. |
| ADR-0005 (provider matrix) / ADR-0006 (cassette) | `rag-eval` | none | Ready (accepted) — ADR-0005 mandates the Anthropic cross-family generator + the deferred `ClaudeJudge`; ADR-0006 governs the cassette pattern. Both reused; no new ADR for them. |
| ADR-0007 (eval-record schema + cost model) | `rag-eval` | none | **Written this phase (FR-17/AC-14).** Proposed → accepted, referencing ADR-0004. The persisted schema + price-table-in-config decision are its content. |
| `observability` KB domain | `observability` | none | **DEFERRED to Sprint 3 (not a blocker).** The deep-research is archived (`_research/archive/observability-2026-05-25.md`) and feeds ADR-0004; the full domain build lands when the tool is wired (Sprint 3 / Phase 7). The index lists it as a future domain. Non-blocking for Phase 6. |
| `rag-eval` KB domain update | `rag-eval` | none | **Post-phase knowledge-loop work.** `/update-kb rag-eval` after Phase 6 captures the eval-record schema, the cost-accounting model, the `CallStats`/`generate_with_stats` seam, and the report-rendering pattern. Non-blocking for `/implement`. |
| Eval-runner specialist agent | n/a | none | **Not warranted yet (assessed honestly).** Phase 6 is a single-pass orchestration build over already-built, well-documented primitives — no repeated specialist context-loading across sessions. The Phase-5 "revisit IF Phase 6 surfaces repeated friction" condition has **not** triggered: the runner is one cohesive module set, not a recurring workflow. Revisit only if Sprint-3 observability + a re-run/re-render loop create repeated context. |

No `/new-kb` or `/new-agent` blocks Phase 6. Four non-blocking items are logged for the
orchestrator: (1) the **one new runtime dep** `anthropic>=0.40,<1.0` is approved-by-ADR-0005
but flagged here for visibility; (2) the `observability` KB domain is **deferred to Sprint 3**
(research archived, ADR-0004 carries the field conventions); (3) `/update-kb rag-eval` for the
eval-record + cost-accounting + report-rendering knowledge is sequenced **after** this phase;
(4) **no specialist agent is recommended**. The only external-action item is AC-15 (verify the
`gpt-5-nano` price on reversible config before the published run).

## Sequencing Notes (not requirements)

- **One phase / one PR** (consistent with the SDD one-branch-one-PR model) with a disciplined
  commit sequence: (1) `CallStats` + `generate_with_stats`/`judge_with_stats` on
  `OpenAIGenerator`/`OpenAIJudge`/stubs; (2) `AnthropicGenerator` + its offline unit test +
  the recorded cassette; (3) `EvalRecord` + `RunConfig` + `configs/baseline.yaml`;
  (4) `eval/runner.py` (single-retriever reuse, cost accounting, fail-fast guard);
  (5) `eval/report.py` (HTML+MD, 10-category, None-as-N/A) + `eval/cli.py` + `rag-eval`
  console script + `make eval-baseline`; (6) ADR-0007 + the `.gitignore` negation; (7) the
  one milestone live run → commit `results/baseline.{html,md}`. Shoulds (FR-13/14/16) slot in
  after the Must spine; their absence does not fail the phase.
- **The `AnthropicGenerator` cassette is the only artifact requiring a live call during
  development** — recorded once with `VCR_RECORD_MODE=once` + `ANTHROPIC_API_KEY`, then
  replayed free. The published baseline run (NFR-9) is a separate, bounded (~low single-digit
  USD) maintainer action, not part of `make test`.
- **`/design` decisions to make:** the exact `string.Template` layout + the HTML `<style>`
  block; the `EvalRecord` namespacing for the two `CallStats` (generation vs judge); the
  Anthropic tool-use call signature (confirm via Context7); whether `RunConfig` selects the
  generator class by a `system` enum + a small registry vs an import path. None reopen a
  DEFINE-level question.

## Next Step

→ `/design sprint-2/phase-6-multimodel-report`
