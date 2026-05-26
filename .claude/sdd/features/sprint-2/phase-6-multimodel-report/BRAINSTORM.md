# BRAINSTORM: phase-6-multimodel-report — Multi-Model Runner & Baseline Report

**Sprint/Phase:** sprint-2/phase-6-multimodel-report | **Date:** 2026-05-24

## Problem Statement

Phases 4 and 5 produced all the scoring primitives — per-fact judge, retrieval metrics,
abstention scorers, and the gold-aware corpus — but nothing runs them end-to-end over a
question set, tracks what each LLM call costs, or assembles the numbers into a human-readable
report. Phase 6 closes that gap: it adds an orchestration layer that drives the full pipeline
(`load_questions → retrieve → assemble → generate → judge → score retrieval/abstention →
accumulate cost/latency`) for ≥2 models from different families, persists per-question eval
records to JSONL, and renders the first published baseline report in HTML and Markdown —
completing the Sprint 2 success criterion of `make eval-baseline` producing real numbers for
a reviewer to inspect.

---

## Research & KB Scan

| Topic                                                                                      | KB file / domain                                                        | Coverage                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JudgeVerdict` / None-empty-denominator convention                                         | `rag-eval/concepts/none-empty-denominator.md` (conf 0.95)               | Sufficient — averaging must skip `None`, never coerce; this propagates into the report's roll-ups unchanged.                                                                                                                                        |
| Retrieval metric aggregation (per-category, None-skipping, dedup-before-metrics)           | `rag-eval/concepts/retrieval-metric-aggregation.md` (conf 0.95)         | Sufficient — `aggregate_retrieval_metrics` is the ready-made entry point; the runner feeds it.                                                                                                                                                      |
| Abstention scoring (`compute_abstention_metrics`, `evaluate_e2e_abstention`)               | `rag-eval/concepts/abstention-scoring.md` (conf 0.95)                   | Sufficient — `abstention.py` is already built; the runner just feeds it answers.                                                                                                                                                                    |
| Cassette/replay pattern (`vcrpy`, `record_mode="none"`, `vcr` marker)                      | `rag-eval/patterns/cassette-replay-eval.md` (conf 0.95)                 | Sufficient — ADR-0006 and the conftest wiring are in place; the runner's tests follow the same pattern.                                                                                                                                             |
| LLM provider/model matrix (OpenAI vs Anthropic vs Ollama; cross-family judge independence) | `docs/adr/0005-llm-provider-matrix.md` (accepted)                       | Sufficient — ADR-0005 assigns roles: OpenAI for judge, Anthropic (`claude-3-5-haiku`/`sonnet`) as cross-family generator, Ollama for $0 local runs.                                                                                                 |
| Generator Protocol seam (`Generator`, `OpenAIGenerator`, `StubGenerator`)                  | `generation/interfaces.py`, `generation/openai_generator.py` (codebase) | Sufficient — the seam is clean; a second-family generator is a new file + one wiring line (per ADR-0003/0005).                                                                                                                                      |
| Anthropic structured-output API difference (tool-use vs `json_schema`)                     | Not in KB                                                               | Thin — the Anthropic SDK uses tool calls for structured outputs, not `response_format`; the `Generator` Protocol hides this but the adapter must handle it. No `/new-kb` needed before `/define`; pattern is well-documented in Anthropic SDK docs. |
| Cost/latency capture patterns (token usage fields, per-call timing)                        | Not in KB                                                               | Thin — OpenAI `response.usage` is known but there is no established harness pattern for a `CallStats` record; deciding the capture seam is this phase's sharpest design tension.                                                                    |
| HTML/Markdown report rendering options (Jinja2 vs stdlib vs pandas.to_html)                | Not in KB                                                               | Thin — the choice is a judgment call at the 6h budget; no `/new-kb` or deep research needed; recommendation can be made directly.                                                                                                                   |
| YAML config schema patterns for eval runners                                               | Not in KB                                                               | Thin — no prior config pattern in the harness; simple `pydantic` model over a YAML file is the natural approach given `pydantic` is already a runtime dep.                                                                                          |

**Conclusion (revised after brainstorm review).** No `/new-kb` or `/update-kb` blocks
`/define` for the **runner mechanics** — those are decided engineering, not research. But a
**focused `--deep-research` pass IS commissioned now**, scoped to the 2026 LLM eval +
observability tooling landscape (Langfuse vs Arize Phoenix vs LangSmith vs OTEL-native), to:
(1) sharpen **ADR-0004 (observability tool), pulled forward from Sprint 3**, and (2) pin the
concrete trace/span data model so Phase 6's `CallStats`/`EvalRecord` are shaped
forward-compatible with the chosen tool (see Decision 4). The research feeds the future
`observability` KB domain. A `/update-kb rag-eval` after Phase 6 still captures the
eval-record schema, cost-accounting model, and report rendering pattern (post-ship knowledge
capture, not a pre-design blocker).

**Deep-research outcome (2026-05-25, consumed).** The pulled-forward research ran and is
archived at `.claude/kb/_research/archive/observability-2026-05-25.md`. It independently
confirmed Decision 4: **Langfuse (self-hosted, MIT) primary, Arize Phoenix (Apache-2.0)
runner-up**, with the phased JSONL-now → exporter-later → OTEL-collector path. Recorded as
**ADR-0004 (proposed)** — `docs/adr/0004-observability-tool.md`. The full `observability` KB
domain build is deferred to Sprint 3 (when the tool is wired); the research file is preserved
in `archive/` for that build. Two concrete inputs are now pinned for `/define` and ADR-0007:

- **`CallStats`/`EvalRecord` OTEL field names:** `gen_ai.request.model`, `gen_ai.system`,
  `gen_ai.operation.name`, `gen_ai.usage.input_tokens`/`output_tokens`, derived `cost_usd`
  (app-computed, not canonical OTEL); offline scores as
  `gen_ai.evaluation.{name,score.value,score.label,explanation}`; retrieval span as `db.*` +
  `retrieval.documents.{i}.document.{id,content,score}`.
- **Price table for ADR-0007** (per 1M tokens, input / output): `gpt-5-nano-2025-08-07`
  `$0.05 / $0.40` · `gpt-4o-mini` `$0.15 / $0.60` · `claude-3-5-haiku-20241022` `$0.80 / $4.00`
  · `claude-3-5-sonnet-20241022` `$3.00 / $15.00`. **Caveat:** these cite aggregator sources;
  verify `gpt-5-nano` against the official OpenAI pricing page before locking ADR-0007.

---

## Approaches Considered

### Decision 1 — Cost/latency capture seam

The runner needs input-token count, output-token count, and wall-clock latency per LLM call.
Both `OpenAIGenerator.generate` and `OpenAIJudge.judge` currently ignore `response.usage`.
Three places to capture this:

| Approach                                                                                                                                                                                                                                                                                                                                               | Pros                                                                                                                                                                                                                                                             | Cons                                                                                                                                                                                                                                                                                                                           | Effort |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. Widen Protocol return types — `Generator.generate` returns `(AnswerWithSources, CallStats)` and `Judge.judge` returns `(JudgeVerdict, CallStats)` where `CallStats(input_tokens, output_tokens, latency_s, model)` is a new dataclass in a shared module.                                                                                           | Stats are first-class; no post-hoc reconstruction; the Protocol contract makes cost visible at every call site; `StubGenerator`/`StubJudge` can emit zeroed `CallStats` trivially; clean seam for Sprint 3 observability.                                        | Breaking change to the existing Protocol — all call sites must be updated; the generation CLI (`rag-ask`) must unpack the tuple even though it discards stats; adds surface area to a clean, minimal seam; Phase 3 did not design for this return.                                                                             | M      |
| B. Runner-level wrapper with timing — the runner owns a thin `timed_call(fn, *args)` helper that records `time.perf_counter()` before/after and extracts `response.usage` by patching the OpenAI client via a lightweight response-interceptor (a thin `__init__` subclass or a `httpx.Client` hook). The Protocols and implementations are unchanged. | Zero Protocol changes; existing CLI, tests, and stubs are untouched; timing + usage are captured orthogonally at the runner boundary, where cost accounting is actually needed; easy to scope to Phase 6 without touching Phase 4/5 code.                        | The runner must be aware of provider-specific `usage` shapes (OpenAI vs Anthropic differ); `response.usage` is only available inside the implementation, so the runner either reads a side-channel (module-level dict, thread-local) or the implementation must write stats somewhere the runner can read — a hidden coupling. | S      |
| C. Separate `CallStats` record returned by augmented implementations — each implementation (not the Protocol) exposes an alternative method `generate_with_stats(...)` / `judge_with_stats(...)` that returns `(result, CallStats)`. The runner calls this method; the CLI and the Protocol contract call the original method unchanged.               | No Protocol break; no side-channel; Stats are explicit in the runner call path; `StubGenerator` gains `generate_with_stats` trivially; each implementation controls its own stats extraction cleanly (OpenAI reads `.usage`; Claude reads its own token fields). | Two methods per implementation to maintain; the augmented method is not on the Protocol, so runtime type-checking (`isinstance`) does not enforce it; a `duck-typing` dependency on a non-Protocol method is a mild design smell; slightly more code than B.                                                                   | S      |

**Leaning: C.** Approach A's Protocol break is disproportionate for a 6h phase — the
`rag-ask` CLI would need a tuple unpack purely to discard the stats, and every future
implementation must emit them whether or not the caller cares. Approach B's hidden
side-channel (thread-local or module-level dict) is fragile and hard to test. Approach C
keeps the Protocol clean, makes stats explicit in the runner's call path, and lets each
implementation extract stats in the provider-appropriate way without magic. The cost is
two methods per implementation, which is acceptable — `generate_with_stats` in
`OpenAIGenerator` is a thin wrapper over `generate` that reads `response.usage` before
returning. The runner uses the augmented method; everything else uses the Protocol method.
`CallStats` field names follow the **OTEL GenAI semantic conventions**
(`gen_ai.usage.input_tokens` / `output_tokens`, request model, latency, derived cost) so the
Sprint-3 observability exporter (Decision 4) maps 1:1 from the same record — see ADR-0004.

---

### Decision 2 — Second-family generator integration

ADR-0005 mandates Anthropic (`claude-3-5-haiku-20241022` or `claude-3-5-sonnet-20241022`)
as the cross-family generator. Three integration paths:

| Approach                                                                                                                                                                                                                                                                                                                                                                                              | Pros                                                                                                                                                                                                                                                            | Cons                                                                                                                                                                                                                                                                                                                       | Effort |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. Native Anthropic SDK adapter — add `anthropic>=0.40,<1.0` as a runtime dep; implement `AnthropicGenerator` in `generation/anthropic_generator.py`. Structured output is via tool-use (`client.messages.create(tools=[...])` + `tool_use` block in the response), not `response_format`. The adapter extracts the `AnswerWithSources` from the tool-use result and returns it through the Protocol. | Native SDK; full control over the tool-use schema; first-class Anthropic structured output (no third-party wrapper); direct access to `usage.input_tokens`/`output_tokens` for the stats record; the Protocol contract is the only abstraction, no extra layer. | One new runtime dependency (`anthropic`); tool-use extraction differs enough from the OpenAI path that the adapter is non-trivial (~50 lines); the tool schema must be kept in sync with `AnswerWithSources.model_json_schema()` or custom-defined per provider.                                                           | M      |
| B. OpenAI-compatible `base_url` via Ollama — configure `OpenAIGenerator` with Ollama's `base_url` (e.g. `http://localhost:11434/v1`) pointing at a local `llama3`/`mistral` model. The OpenAI SDK speaks the compatible REST surface; no new SDK dep.                                                                                                                                                 | Zero new runtime dep; Ollama models are $0 and stay offline; the `OpenAI(base_url=...)` trick is already an ADR-0005-anticipated path; dev runs never hit a paid API.                                                                                           | Ollama is not "a different family" in the credit-worthy sense — it's a wrapper; the baseline numbers at Phase 6 should pit OpenAI-family against Anthropic-family to demonstrate cross-family judge independence (the mid-checkpoint criterion). Structured output support is model-dependent and less reliable on Ollama. | S      |
| C. Both A and B — ship `AnthropicGenerator` for the cross-family baseline, and also support Ollama via the `base_url` path as the $0 dev option.                                                                                                                                                                                                                                                      | Complete: real cross-family numbers from Anthropic + free local iteration from Ollama; the config YAML selects the generator per model entry; the harness is fully ADR-0005-compliant.                                                                          | Approach A + B in one phase; the Anthropic tool-use adapter is the dominant effort; adding Ollama on top of it is a "Could" not a "Must."                                                                                                                                                                                  | L      |

**Leaning: A (AnthropicGenerator, native SDK) as Must; B (Ollama base_url) as Could.**
The cross-family comparison is the entire point of Phase 6's multi-model deliverable. Using
Ollama as the "second family" satisfies the letter of "≥2 models from different families"
but not the spirit — Anthropic Claude provides a genuinely different family with
portfolio-credible results. The Anthropic SDK adapter is ~50 lines following the exact same
shape as `OpenAIGenerator`. Ollama is useful for $0 dev runs and can be wired with a single
`base_url` override if time permits; it is a Could.

Regarding the **cross-family judge** question from ADR-0005 ("run cross-evaluations"): Phase 6
does not need to wire `ClaudeJudge` to judge OpenAI-generated answers. The baseline report
uses `OpenAIJudge` for both generators — that is the v1 baseline. The same-family concern
(OpenAI judge rating OpenAI answers) is noted in the report's methodology section; the
`ClaudeJudge` swap is a fast-follow and is explicitly in the Won't list. ADR-0005 enables
it; Phase 6 does not build it.

---

### Decision 3 — Runner persistence and report split

The runner processes 500 questions × N models. Two orchestration architectures:

| Approach                                                                                                                                                                                                                                                                                                                                                                                                                       | Pros                                                                                                                                                                                                                                                                                      | Cons                                                                                                                                                                                                                                            | Effort |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A. JSONL eval-record as durable artifact, report as pure render — the runner writes one JSON line per question per model (`EvalRecord(question_id, model, answer, verdict, retrieval_ranked_ids, cost_stats, latency_s, category, …)`) to `results/<run_id>.jsonl` as it processes each question. The report command reads that JSONL and renders HTML+MD. Runs are resumable (skip already-recorded question_id+model pairs). | Decouples eval from reporting; a crashed run at question 400 can be resumed without reprocessing; the JSONL is the authoritative record and can be re-rendered with a new template; the report is a deterministic function of the JSONL — reproducible offline; easy to diff across runs. | One extra schema (`EvalRecord`) to define and test; JSONL path management (run IDs, output dirs) adds a small config surface; the "pure render" split is a mild over-engineering risk if the report is only ever rendered once from the runner. | M      |
| B. In-memory single-pass — the runner accumulates everything in memory and writes the report at the end. No intermediate JSONL; the report IS the output.                                                                                                                                                                                                                                                                      | Simpler; fewer moving parts; the 6h budget is tight.                                                                                                                                                                                                                                      | A crash at question 499 loses everything; no re-render without re-running; the report becomes a formatting concern tightly coupled to the runner logic; hard to inspect intermediate results.                                                   | S      |
| C. Checkpoint-to-JSONL during run, report inline — the runner writes JSONL and immediately renders the report at the end of the same invocation. The `rag-eval run` command does both; a `rag-eval report` sub-command re-renders from JSONL if the user wants. Hybrid of A and B.                                                                                                                                             | Best of both: crash-safe (JSONL checkpoint), single-command UX, and re-renderability as a bonus. The report command is just a thin CLI wrapper over the existing render function.                                                                                                         | Slightly more surface area than B; the CLI must parse sub-commands (`run` vs `report`).                                                                                                                                                         | M      |

**Leaning: C.** Approach B is the simplest but unacceptable at 500 questions — a crash or a
cost overrun mid-run loses all data. Approach A is the cleanest architecture but the
two-command UX ("run, then render") is awkward for a one-command `make eval-baseline` target.
Approach C gives the JSONL durability for free while keeping `rag-eval run` as the single user-
facing command; the `rag-eval report --results path/to.jsonl` sub-command is a thin wrapper
added as a Should. The JSONL schema is the one new ADR candidate (see Suggested ADRs below).

---

### Decision 4 — Observability & framework tooling positioning (resolved in brainstorm review)

Phase 6 deliberately builds a **thin, tool-agnostic** runner + static report rather than
adopting an orchestration or eval framework. The tools raised in review and their placement:

| Tool              | Verdict                              | Reasoning                                                                                                                                                                                                                                                                           |
| ----------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LangChain**     | ❌ Not adopted                       | Would replace the deliberate custom substrate (ADR-0002/0003). Swapping LangChain into a 9-source hybrid RAG already built on clean Protocol seams reads to a senior reviewer as not understanding the primitives — an anti-signal. The custom seams **are** the signal.            |
| **LangSmith**     | ❌ Not adopted · ✅ compared in 0004 | Proprietary SaaS, not self-hostable → fails ADR-0004's stated criteria (portability, self-host, no lock-in). But the documented comparison ("evaluated LangSmith, rejected because X") is itself a senior signal — it belongs in ADR-0004's alternatives-considered.                |
| **OpenTelemetry** | ✅ Sprint 3 (Phase 7) — shape now    | The portability layer (ADR-0004). Phase 6 does **not** emit spans, but `CallStats`/`EvalRecord` are shaped to the OTEL GenAI semantic conventions (model, input/output tokens, latency, cost) so Sprint 3 adds an exporter over the same data, not a rewrite ("shape right day 0"). |
| **Langfuse**      | ✅ Sprint 3 lead candidate (0004)    | Self-hostable, open-source; does traces + cost + eval scores. The Phase 6 eval-record JSONL is the durable, tool-agnostic substrate that will **feed** Langfuse via a Sprint-3 exporter, not be replaced by it.                                                                     |

**Decision (confirmed with the user):** keep Phase 6's durable artifact a cloneable JSONL +
static HTML/MD report (zero infra — a reviewer sees real numbers from a `git clone`, no
`docker-compose up`), but shape the records OTEL/Langfuse-compatible. A **focused
`--deep-research`** (see Research & KB Scan) is pulled forward to back **ADR-0004** and pin
the exact trace/span field model the records mirror. Integrating Langfuse live in Phase 6 was
considered and **rejected**: it collapses two sprints, blows the 6h budget, and couples the
"published baseline numbers" deliverable to running infrastructure.

---

## Recommended Approach

**Decision 1: Approach C** (augmented `generate_with_stats`/`judge_with_stats` methods on
implementations, not on the Protocol). Keeps the seam clean, gives the runner explicit stats
without hidden side-channels, and lets each provider extract stats in its own way.

**Decision 2: Approach A as Must, Approach B (Ollama) as Could.** Ship `AnthropicGenerator`
for a genuine cross-family comparison; wire Ollama only if time permits. The cross-family judge
(`ClaudeJudge`) is an explicit Won't for this phase — fast-follow after the baseline report.

**Decision 3: Approach C** (JSONL checkpoint during run, report rendered at the end of the
same invocation). Crash-safe, single-command UX, and re-renderable.

Rationale across all three: the 6h budget is tight. Every recommendation picks the option that
is smallest-while-still-correct — no Protocol breaks, no hidden magic, no premature CLI
complexity. The JSONL persistence is the one non-obvious cost and it is justified by the 500-q
run risk; everything else is additive on top of what Phases 4 and 5 already built.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                                                                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | `EvalRecord` dataclass — one record per question per model: `question_id, model_id, category, answer, verdict (JudgeVerdict), retrieval_ranked_ids, input_tokens, output_tokens, latency_s, run_id`. Written as JSON lines to `results/<run_id>.jsonl` during the run; the runner flushes after each question (crash-safe).         |
| Must     | `generate_with_stats` on `OpenAIGenerator` and `AnthropicGenerator` — returns `(AnswerWithSources, CallStats)` where `CallStats(input_tokens, output_tokens, latency_s, model)` reads `response.usage` from the OpenAI/Anthropic response; `judge_with_stats` on `OpenAIJudge` similarly. Protocol unchanged.                       |
| Must     | `AnthropicGenerator` in `generation/anthropic_generator.py` — implements `Generator` Protocol via Anthropic tool-use structured output for `AnswerWithSources`; `anthropic>=0.40,<1.0` added as a runtime dep.                                                                                                                      |
| Must     | End-to-end runner function (not a CLI yet — a plain function or module) that orchestrates: `load_questions(limit)` → per question: retrieve → assemble → generate_with_stats → judge_with_stats → score retrieval → check abstention → write `EvalRecord` to JSONL. Sequential (not concurrent) in the Must tier.                   |
| Must     | `configs/baseline.yaml` — YAML config listing models, judge model, `limit` (question subset), `k` for retrieval, `output_dir`, `run_id`; parsed by a `pydantic` model (`RunConfig`). Two model entries minimum: one OpenAI generator, one Anthropic generator.                                                                      |
| Must     | `rag-eval` console script in `pyproject.toml [project.scripts]` wired to a `eval/cli.py:main` entry point; sub-command `rag-eval run --config configs/baseline.yaml` drives the runner and writes the report.                                                                                                                       |
| Must     | HTML + Markdown report renderer — reads the JSONL, produces `results/baseline.html` and `results/baseline.md`; sections: overall summary, per-category breakdown (all 10 categories), per-model cost/latency table; `None` cells rendered as "N/A", never 0. Jinja2 or Python stdlib string templates (no Streamlit — Sprint 3).    |
| Must     | `make eval-baseline` target — runs `uv run rag-eval run --config configs/baseline.yaml`; existing `results/` dir is gitignored but the template `configs/baseline.yaml` is committed.                                                                                                                                               |
| Must     | Exit criterion: `make eval-baseline` runs the full 500 questions for one model (or a `limit`-capped subset for dev) in <30 min; the report contains a per-category breakdown across all 10 question categories; cost and latency are visible per model.                                                                             |
| Must     | Per-model price table in config (per-1M input/output tokens), not hardcoded; the runner computes `estimated_cost_usd` from `CallStats.input_tokens + output_tokens` and the price table. Fail loud (warn + continue) if a model has no price entry.                                                                                 |
| Must     | Unit tests for: `EvalRecord` serialization/deserialization; `CallStats` arithmetic (cost formula); `RunConfig` YAML parsing; report renderer (given a hand-built JSONL, assert the rendered sections); `AnthropicGenerator` call shape (fake Anthropic client, offline). All tests pass under `make test` (no API key, no network). |
| Must     | Cassette test for `AnthropicGenerator` live call — one recorded cassette in `tests/eval/cassettes/`; the runner integration test replays it offline (following ADR-0006). The `vcr` marker gates it from the default `make test` run or the cassette is committed so `make test` replays it.                                        |
| Should   | `rag-eval report --results results/<run_id>.jsonl` sub-command — re-renders the report from a JSONL without re-running the eval; a thin CLI wrapper over the renderer function.                                                                                                                                                     |
| Should   | Concurrent runner option (`--concurrency N`) — run N questions in parallel via `asyncio` or `ThreadPoolExecutor`; the sequential Must-tier runner is the default; concurrency is an opt-in flag. Reduces the 500-q wall time substantially.                                                                                         |
| Should   | `results/baseline.html` and `results/baseline.md` committed as the first published baseline numbers (the sprint exit criterion "first published" — the files are gitignored by default but the phase notes them as the published artifact; `/define` decides whether to un-gitignore them for the portfolio milestone).             |
| Should   | Cost overrun guard — the runner checks accumulated `estimated_cost_usd` after each question and logs a warning + optionally halts if it exceeds a configured ceiling (e.g. `cost_ceiling_usd: 10.0` in the YAML).                                                                                                                   |
| Could    | Ollama generator via `OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")` — a $0 local option wired as a third model entry in the config; no new dep (uses the OpenAI SDK's `base_url`). Useful for dev iteration.                                                                                                      |
| Could    | nDCG@k surfaced in the per-category breakdown (the metric is already computed by `aggregate_retrieval_metrics`; rendering it in the report is additive).                                                                                                                                                                            |
| Could    | `results/` directory un-gitignored for the committed baseline files only, via `.gitignore` negation (`!results/baseline.html`, `!results/baseline.md`); the run-specific JSONL files stay gitignored.                                                                                                                               |
| Won't    | `ClaudeJudge` / cross-family judge — the OpenAI judge scores both generators in v1. The same-family concern is noted in the report's methodology; `ClaudeJudge` is the named ADR-0005 fast-follow behind the `Judge` Protocol seam. Not in this phase.                                                                              |
| Won't    | Async streaming from the OpenAI/Anthropic API — the synchronous SDK call is sufficient for the 500-q batch; streaming complicates `usage` capture without benefit for this use case.                                                                                                                                                |
| Won't    | Streamlit dashboard — Sprint 3 (Phase 9). The Phase 6 report is a static HTML/MD artifact, not an interactive app.                                                                                                                                                                                                                  |
| Won't    | Per-fact supporting-doc mapping in the report — the additive `supporting_doc_id` field on `FactVerdict` is a Sprint 2 backlog item (noted in the roadmap); Phase 6 uses the `JudgeVerdict` as-is.                                                                                                                                   |
| Won't    | Fine-tuning, reranker tuning, retrieval architecture changes — the Phase 6 runner measures the substrate, does not improve it.                                                                                                                                                                                                      |
| Won't    | Conflict-resolution scoring on `conflicting_info` — not a Phase 6 deliverable (roadmap backlog).                                                                                                                                                                                                                                    |
| Won't    | Full 512K-doc corpus encode — dev and the published baseline use the gold-aware corpus from Phase 5; final portfolio leaderboard numbers use a rented box after Sprint 4.                                                                                                                                                           |
| Won't    | OpenTelemetry instrumentation / distributed tracing — Sprint 3, Phase 7. The runner logs to Python `logging` only.                                                                                                                                                                                                                  |

---

## Open Questions

**Q1 — Which exact models in the baseline config?**
ADR-0005 names `claude-3-5-haiku-20241022` and `claude-3-5-sonnet-20241022` as the Anthropic
options, and `gpt-5-nano-2025-08-07` as the OpenAI generator. Should the Phase 6 baseline
config run `gpt-5-nano-2025-08-07` vs `claude-3-5-haiku-20241022` (cheapest cross-family pair)
or include a third model (e.g. `claude-3-5-sonnet`)? The answer affects the total cost of one
baseline cycle and the `configs/baseline.yaml` committed defaults. `/define` pins the exact
model IDs, the per-1M token prices, and the default `limit` for dev runs.

**Q2 — Cross-family judge: in-scope or fast-follow?**
ADR-0005 says "run cross-evaluations: evaluate OpenAI-generated answers with an Anthropic-based
judge." Phase 6 is the first place this can be built. Given the 6h budget, the recommendation
above is to defer `ClaudeJudge` to a fast-follow, using `OpenAIJudge` for both generators in
v1. Is this acceptable for the mid-checkpoint go/no-go criterion ("≥2 ADRs written" is
satisfied; "eval credible vs Onyx leaderboard" does not require cross-family judging), or is
the same-family judge-for-Claude-answers a credibility blocker? `/define` closes this.

**Q3 — Cost/latency capture seam: Approach C confirmed?**
The recommendation (augmented `generate_with_stats`/`judge_with_stats` on implementations,
Protocol unchanged) needs an explicit decision before `/design` can write the class interface.
If the user prefers Approach A (widen the Protocol return type), the interface change ripples
into the `rag-ask` CLI, `StubGenerator`, and `StubJudge` — a broader code change with a clear
tradeoff. `/define` confirms the approach and pins the `CallStats` field names.

**Q4 — Report rendering library: Jinja2 vs stdlib string templates?**
Jinja2 (`jinja2>=3.0`) is not currently a dependency; it would be a new runtime dep for a task
the Python `string.Template` class or even f-string-driven templates can handle for a
report of this complexity. Is the cleaner Jinja2 template syntax worth adding a dep, or does
stdlib suffice for the Phase 6 report? `/define` picks one and specifies it as a dep decision.

**Q5 — Eval-record JSONL schema and location.**
`EvalRecord` needs a concrete field list pinned before `/design`. Key questions: does the
record embed the full `JudgeVerdict` (all `per_fact`/`per_citation` lists, which are verbose)
or just the three aggregate floats? Does it include the raw `answer` text (useful for the
report's per-question drill-down but large at 500 × N models)? And does the JSONL live at
`results/` (gitignored by default, un-gitignored selectively) or somewhere else? `/define`
pins the schema fields and the output path convention.

**Q6 — Does the runner reuse one built index across all models, and is the Phase 5 gold-aware corpus the eval corpus?**
The retriever is a shared resource: the same HybridRetriever instance runs for every model
(retrieval is model-agnostic — only the generator swaps). This must be stated explicitly to
avoid the runner re-loading the index per model. Related: the Phase 5 gold-aware corpus
(built with `rag-ingest --gold-aware`) is the assumed eval corpus for Phase 6 numbers — a
reviewer cloning the repo must run `make build-index-gold` before `make eval-baseline`. Does
`make eval-baseline` check for the gold-aware corpus/index and fail fast with a helpful
message if missing, or is that a dependency documented only in the README? `/define` resolves
both the single-retriever-instance design and the corpus prerequisite handling.

**Q7 — Are `results/baseline.html` and `results/baseline.md` committed to the repo?**
The roadmap lists "first published baseline numbers in `results/baseline.{html,md}`" as the
Phase 6 exit criterion. Currently `results/` is gitignored entirely. The committed baseline
files are the portfolio artifact — the stranger test says they belong in the public repo.
Should Phase 6 un-gitignore these two specific files (`.gitignore` negation) and commit the
first real run's output? Or are they treated as local artifacts, with the report template
and the methodology being the committed artifact? `/define` closes this with an explicit
decision; the recommendation is to un-gitignore and commit the first run.

**Q8 — Forward-compatible record shape: confirm the OTEL/trace field mapping.**
Decision 4 commits to shaping `CallStats`/`EvalRecord` to the OTEL GenAI semantic conventions
so the Sprint-3 observability exporter (ADR-0004) is additive, not a rewrite. The exact field
names and the minimal trace/span attribute set come from the pulled-forward deep research →
ADR-0004, which is now **drafted (proposed)** and supplies the field mapping (see
Deep-research outcome above). `/define` lifts the `CallStats`/`EvalRecord` field list directly
from ADR-0004 and pins it alongside the ADR-0007 price table — no longer blocked.

---

## Suggested ADRs

**ADR-0007 — Eval record schema and cost-accounting model.** Phase 6 introduces a new
persisted artifact (`EvalRecord` JSONL) and a cost-accounting model (per-1M token prices in
config, `estimated_cost_usd` computed from `CallStats`). This is a concrete design decision
with consequences (the JSONL schema is the contract between the runner and the renderer; the
cost model determines what the report can say about spend). An ADR captures the schema choice
and the price-table-in-config decision cleanly. Recommended timing: write it in Phase 6 at
decision time (before `/design`), mirroring ADR-0001 (eval framework) and ADR-0006
(cassette/replay). ADR-0007 should reference ADR-0004 and adopt the OTEL GenAI field names.

**ADR-0004 — Observability tool (pulled forward from Sprint 3).** Brainstorm review elevated
this: a focused `--deep-research` pass now backs ADR-0004 (Langfuse vs Arize Phoenix vs
LangSmith vs OTEL-native) so Phase 6's record schema is forward-compatible (Decision 4).
ADR-0004 need not be _accepted_ in Phase 6 — a **drafted/proposed** ADR carrying the trace
data model is enough to constrain `CallStats`/`EvalRecord`. Acceptance can stay at Phase 7
when the tool is actually wired.

ADR-0005 and ADR-0006 already cover the multi-model matrix and cassette/replay respectively —
no new ADR is needed for those. The `AnthropicGenerator` adapter is the ADR-0005 named swap
(a new file implementing the Protocol), not a new decision.

---

## Next Step

→ `/define sprint-2/phase-6-multimodel-report`
