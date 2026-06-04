# Bronze Raw Archive: `BronzeWriter` and ADR-0010 §2

> **Purpose**: Design invariants of the bronze persistence layer — key scheme,
> thread model, idempotency, opt-in flag, and privacy constraints. Complements
> `stats-capture-seam.md` (which covers the `RawCall` transport that feeds it).
> **Confidence**: HIGH (codebase — `eval/bronze.py`, `eval/runner.py`,
> `eval/config.py`, `docs/adr/0010-persist-judge-reasoning-bronze-gold.md`)

## Why a Separate Bronze Layer

ADR-0007 enforces strict footprint discipline on `EvalRecord` (gold): bulky
generation prompts and raw LLM response payloads are excluded. ADR-0010 §2
designs a gitignored bronze layer to hold those payloads without polluting
either the gold JSONL or the repository.

Bronze and gold are **independently written and independently safe to lose**:
a crashed sweep leaves a complete gold JSONL and zero or partial bronze files;
either is usable without the other.

## Key Scheme

```
data/raw_eval/{run_id}/{question_id}__{model}__{call_type}.json
```

- `call_type ∈ {gen, judge}` — one file per API call per question per model.
- `run_id` is bound at `BronzeWriter.__init__` and **sanitized** there: raises
  `ValueError` if `run_id` is empty, contains `/`, `os.sep`, or `..` (prevents
  path traversal into unintended parent directories).
- `data/raw_eval/` is gitignored. The directory is created on demand by the
  first `write()` call.

## Payload Shape

```json
{
  "schema_version": 1,
  "meta": {
    "run_id": "...",
    "question_id": "...",
    "model": "...",
    "system": "openai | anthropic | google",
    "call_type": "gen | judge"
  },
  "request": { ... },
  "response": { ... }
}
```

`request` and `response` come directly from the `RawCall` returned by
`generate_with_stats` / `judge_with_stats`. Auth headers and client
credentials are never included — they never reach `RawCall`.

## Idempotency

`BronzeWriter.write()` opens in `"w"` mode (overwrite). Re-running a sweep
with the same `run_id` overwrites existing bronze files key-by-key, matching
the runner's JSONL `"w"` mode semantics. A partial re-run leaves prior bronze
files that were not re-covered — same behaviour as a partial gold JSONL.

## Thread Model

`BronzeWriter` owns **its own `threading.Lock`** — independent of the
runner's `write_lock` (JSONL flush), `cost_lock`, and `retrieve_lock`. This
is correct because the key scheme guarantees **one file per call** (distinct
paths = no contention between workers); the lock only serializes the
`mkdir + open` sequence for the same path under concurrent workers, which
would otherwise race on the first write to a new directory.

Bronze writes happen **outside** the JSONL `write_lock`. A bronze failure
(e.g., disk full) raises in the worker but does not corrupt the JSONL flush
— they are independent write paths.

## Opt-In Flag

`RunConfig.persist_bronze: bool = False` (default off). The default sweep is
byte-for-byte unchanged. The CLI exposes `--persist-bronze`.

When `persist_bronze` is `True`, one `BronzeWriter(run_id=config.run_id)` is
constructed once before the per-question loop. When `False`, `bronze_writer`
is `None` and the write block is skipped entirely.

## Retrieval-Abstain Exemption

When the retriever returns zero chunks, the runner skips the generation call
and sets `gen_raw = None`. The bronze write for `call_type=gen` is guarded:

```python
if gen_raw is not None:
    bronze_writer.write(..., "gen", ...)
```

The judge always runs (even on a retrieval abstain), so `judge_raw` is never
`None` and the judge bronze is always written when `persist_bronze` is `True`.

## Related

- `eval/bronze.py` — `BronzeWriter`
- `eval/raw_call.py` — `RawCall` (the transport feeding bronze)
- `eval/config.py` — `RunConfig.persist_bronze`
- `eval/runner.py` — wiring: construction, guard, payload assembly
- `docs/adr/0010-persist-judge-reasoning-bronze-gold.md` — decision record
- [stats-capture-seam.md](stats-capture-seam.md) — `RawCall` 3-tuple design
