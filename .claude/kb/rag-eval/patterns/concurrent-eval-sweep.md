# Concurrent Eval Sweep: Encoder Lock + Provider Resilience

> **Purpose**: Operational invariants for running the multi-model sweep under
> `--concurrency` — the BGE-M3 thread-safety fix, provider timeout/retry settings,
> and rate-limit behaviour. Captured from the live baseline run.
> **Confidence**: HIGH (codebase — `eval/runner.py`, `generation/anthropic_generator.py`,
> `generation/openai_generator.py`; live baseline run 2026-05-26)

## When to Use

Configure a new sweep run, debug a hung or crashed sweep, or wire in a new provider.

## BGE-M3 Encoder Is Not Thread-Safe

The shared `HybridRetriever`'s BGE-M3 encoder (torch/MPS backend) aborts the process
with a semaphore leak when called concurrently from multiple `ThreadPoolExecutor`
workers. The encode step is fast (CPU-bound, ~10ms); LLM calls are slow (~1–10s).

Fix: serialize encode under `retrieve_lock`, leave LLM calls unserialized:

```python
retrieve_lock = threading.Lock()   # in runner.py scope

def process_one(q):
    with retrieve_lock:            # encode: serialized (fast)
        chunk_hits = retriever.retrieve_chunks(q.question, top_k=config.k)
    # LLM generate + judge: concurrent (slow, where --concurrency pays off)
    answer, gen_stats = generator.generate_with_stats(ctx_chunks, q.question)
    verdict, judge_stats = judge.judge_with_stats(...)
```

This is NOT needed when `concurrency=1` (the `make eval-baseline` default).

## Provider Client Construction: Timeout and Retries

Dead sockets and rate limits require explicit settings on client construction:

```python
# anthropic_generator.py
Anthropic(max_retries=8, timeout=120.0)
# max_retries=8 → rides out Anthropic tier-1 rate limits (10K output-tokens/min)
#   via SDK-managed retry-after backoff
# timeout=120.0 → a dead socket (host sleep mid-sweep) fails fast instead of
#   blocking ~36 min (the SDK's default timeout never fired in testing)

# openai_generator.py / openai_judge.py
OpenAI(timeout=120.0)
# Same timeout rationale; OpenAI SDK has better defaults but 120s is still safer
```

These settings are on **construction**, not per-call. If injecting a test client,
the injected client bypasses these settings — which is fine for offline tests.

## Anthropic Tier-1 Rate-Limit Behaviour

Tier-1 Anthropic accounts cap **output tokens per minute** (~10K). A full sweep of
500 questions with a verbose generator will throttle. The SDK honours the
`retry-after` header with exponential backoff — `max_retries=8` rides out per-minute
windows without manual sleep or retry loops.

Symptom if throttling without retries: `RateLimitError` after a burst. With
`max_retries=8`, the SDK waits and retries transparently.

## Practical Sweep Checklist

```
1. make build-index-gold        # gold-aware index (not make build-index)
2. run a capped dev sweep first:
   rag-eval run configs/baseline.dev.yaml   # limit: 20 questions, same model matrix
3. inspect results/dev.jsonl for sane scores before committing to full run
4. caffeinate rag-eval run configs/baseline.yaml   # prevent sleep mid-sweep
5. rag-eval report results/baseline.jsonl results/
```

`configs/baseline.dev.yaml` is the same as `baseline.yaml` with `limit: 20` — cheap
enough to re-run, catches model-EOL and index misconfiguration early (live findings
#9, #10).

## Known Gap: FR-10 Guard Does Not Verify Gold Awareness

The runner checks that index directories exist, not that they are the gold-aware
build. A `make build-index` (non-gold) passes the guard but yields 0% retrieval
recall. Until a gold-marker file is added to the index artifacts, `make build-index-gold`
must be run deliberately before any baseline sweep.

## Related

- `eval/runner.py` — `retrieve_lock`, `executor.map` consumption
- `generation/anthropic_generator.py` — `Anthropic(max_retries=8, timeout=120.0)`
- `generation/openai_generator.py` — `OpenAI(timeout=120.0)`
- [multi-model-runner.md](multi-model-runner.md)
- [../concepts/cost-accounting.md](../concepts/cost-accounting.md)
