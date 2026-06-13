# Multi-Model Evaluation Runner

> **Purpose**: How the runner orchestrates a full sweep — single retriever, multiple
> generator models, per-question flush, cost ceiling, concurrency, transient-error
> skip, and `--resume` — and the operational invariants from the live baseline run.
> **Confidence**: HIGH (codebase — `eval/runner.py`, `eval/config.py`)
> **ADR**: `docs/adr/0007-eval-record-schema.md`

## When to Use

Implement or debug any full-sweep eval: multi-model JSONL generation, cost-guarded
runs, or `--concurrency` use.

## Core Orchestration Shape

```python
# eval/runner.py (simplified)
retriever = pipeline.load_retriever()   # loaded ONCE, reused for all models

for model in config.models:
    generator = _GENERATOR_FACTORY[model.system](model=model.model_id)
    judge = OpenAIJudge(model=config.judge_model)

    for q in questions:
        with retrieve_lock:                          # serialize encode — see below
            chunk_hits = retriever.retrieve_chunks(q.question, top_k=config.k)
        answer, gen_stats  = generator.generate_with_stats(ctx_chunks, q.question)
        verdict, judge_stats = judge.judge_with_stats(question=q.question, ...)
        gen_stats.cost_usd   = compute_cost_usd(gen_stats,  prices.get(gen_model))
        judge_stats.cost_usd = compute_cost_usd(judge_stats, prices.get(judge_model))
        record = EvalRecord(...)
        f.write(record.model_dump_json() + "\n")
        f.flush()                                    # crash-safe checkpoint
```

`_GENERATOR_FACTORY = {"openai": OpenAIGenerator, "anthropic": AnthropicGenerator, "google": GeminiGenerator}`
Adding a new provider requires only a new entry here plus a YAML price row (Gemini
was added this way in Sprint 4 / Phase 10 — see ADR-0005 amendment).

## The FR-10 Fail-Fast Guard and Its Known Gap

The runner checks index dirs exist before loading the retriever:

```python
if not (BM25_INDEX_DIR.exists() and LANCEDB_DIR.exists() and CHUNK_ORDER_PATH.exists()):
    raise RuntimeError("... Please run `make build-index-gold` first.")
```

**Known gap (live baseline finding #10):** the guard checks dir _existence_, not that
it is the gold-aware build. A plain index (built without gold docs) passes the guard
but yields 0% retrieval recall silently. Always run `make build-index-gold` before a
sweep — not `make build-index`. A future improvement: add a gold-marker file to the
index artifacts and assert its presence.

## BGE-M3 Encoder Thread-Safety: `retrieve_lock`

The shared BGE-M3 encoder (torch/MPS) is **not thread-safe** under concurrent calls
from `ThreadPoolExecutor`. Concurrent encodes abort the process with a semaphore
leak. The fix: serialize the fast encode under `retrieve_lock` while LLM calls
(the slow part) run concurrently:

```python
retrieve_lock = threading.Lock()

def process_one(q):
    with retrieve_lock:               # encode serialized
        chunk_hits = retriever.retrieve_chunks(q.question, top_k=config.k)
    # LLM generate + judge calls proceed concurrently without the lock
    answer, gen_stats = generator.generate_with_stats(...)
```

This gives most of the concurrency benefit (LLM latency >> encode latency) with no
correctness risk.

## Exception Propagation Under Concurrency

`executor.map` returns a lazy iterator — consuming it is mandatory:

```python
with ThreadPoolExecutor(max_workers=concurrency) as executor:
    for _ in executor.map(process_one, questions):   # consume — propagates exceptions
        pass
```

Without the `for _ in ...` loop, a worker exception is silently swallowed and the run
appears to succeed with a short JSONL.

## Transient-Error Skip

One unhandled network exception used to kill an entire ~2500-call sweep. The runner
now wraps generation and judge calls in a `try/except _TRANSIENT_ERRORS` block:

```python
# eval/runner.py — _TRANSIENT_ERRORS tuple
_TRANSIENT_ERRORS = (
    openai.APIConnectionError,   # includes APITimeoutError
    openai.InternalServerError,
    openai.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    httpx.TransportError,        # RemoteProtocolError, TimeoutException, ConnectError, …
    google.genai.errors.ServerError,  # imported defensively; absent if SDK reshuffles
)
```

A caught transient error: logs a `WARNING` with `(question_id, system, model, exc)`,
increments `failed_count`, and **returns** — leaving a gap in the JSONL (no record
written for that `(system, question_id)` pair). The gap is resumable via `--resume`.

Non-transient errors (auth/4xx config errors, `RuntimeError` bugs) still propagate
immediately — a misconfigured run fails fast on the first call rather than silently
skipping everything.

At run end: `logger.warning("%d question(s) hit a transient error ... Re-run with
--resume to fill the gaps.")` if `failed_count > 0`.

## Resume (`run_evaluation(..., resume=True)`)

`resume=True` (CLI: `--resume`) lets an interrupted or gap-filled sweep converge to
complete without re-spending on already-finished calls.

**Mechanics (eval/runner.py lines 191–208):**

1. If `resume=True` and `{output_path}.jsonl` exists, read all lines, parse JSON.
2. Collect `completed: set[tuple[str, str]]` of `(gen_ai.system, question_id)` pairs.
3. Re-accumulate `total_cost_usd` from prior records so the ceiling stays meaningful.
4. Open the file in `"a"` (append) mode; `"w"` (truncate) if not resuming.
5. In `process_one`, skip if `(model.system, q.question_id) in completed`.

```python
# eval/runner.py — resume skip guard (per worker)
if (model.system, q.question_id) in completed:
    return
```

**Contract:** `resume=False` (default) truncates on re-run — the original behavior,
preserved for clean restarts. This **supersedes** the old workaround of using a
separate `run_id` + manual JSONL concat when a sweep died mid-run.

**Workflow for gapped sweeps:**

```bash
uv run rag-eval run --config configs/routing-eval.yaml --concurrency 8 --resume
# Re-run until the end-of-run "N hit a transient error" warning is gone.
```

## Adding a New Generator

1. Implement `generate_with_stats` returning `(AnswerWithSources, CallStats, RawCall)`.
2. Add `"<system>": MyGenerator` to `_GENERATOR_FACTORY`.
3. Add price entry to `configs/baseline.yaml`.
4. Add `ModelConfig(model_id=..., system="<system>")` to `RunConfig.models`.

## Related

- `eval/runner.py`, `eval/config.py`, `eval/records.py`
- [../concepts/eval-record-schema.md](../concepts/eval-record-schema.md)
- [../concepts/cost-accounting.md](../concepts/cost-accounting.md)
- [concurrent-eval-sweep.md](concurrent-eval-sweep.md)
- [eval-report-render.md](eval-report-render.md)
