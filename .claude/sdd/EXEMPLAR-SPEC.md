---
status: approved # draft | approved | implemented | archived
governing_adrs: [ADR-0001] # this exemplar is governed by the spec-layer decision
source_charters:
  [CHARTER.md] # models the L0 trace — a feature Spec names the charter it serves
  # (an ADR-born infra module would instead set `infra: true`)
surfaces: "internal: RateLimiter.check()"
ssot: []
sprint: ""
phase: ""
last_updated: "2026-01-01"
---

# SPEC: rate-limiter — fair, per-principal request throttling

> **This is a worked exemplar.** It is intentionally small but complete. Copy it (not the
> bare `_template.md`) when authoring a new spec, then replace the content. It shows the
> shape the "agent-ready" bar expects: scoped boundaries, executable schemas, EARS ACs.

**Changes:** initial contract.

## 1. Purpose & boundaries

A token-bucket limiter that decides whether a given principal (user/API key/IP) may proceed
with a request right now, and how long to wait otherwise. It is a pure decision component —
callers enforce the verdict.

- **Owns:** the bucket algorithm, per-principal state, the `check()` verdict contract.
- **Does NOT own:** transport-level rejection (the HTTP middleware returns 429), persistence
  of buckets across restarts (→ the `cache` module), or quota _policy_ (→ config).
- **Non-goals (v1):** distributed/cross-node coordination (single-node buckets only;
  _reserved decision_: a Redis-backed store is the planned v2 seam, not designed here);
  per-endpoint differentiated limits (one limit per principal class).

## 2. Policies

- **Fail-open on state error.** If bucket state can't be read, `allowed = true` (availability
  beats strictness for a non-security limiter) — but emit a metric.
- **Monotonic refill.** Buckets refill by elapsed wall-clock since last check, capped at
  `capacity`. Never refill above capacity.

## 3. Data model

```python
@dataclass
class Bucket:
    principal: str        # owner key; the only isolation dimension
    tokens: float         # current tokens, 0 .. capacity
    capacity: float       # max tokens (burst size)
    refill_per_sec: float # steady-state rate
    last_refill: float    # epoch seconds, monotonic source
```

## 4. Contracts (API / IO)

```python
@dataclass(frozen=True)
class Verdict:
    allowed: bool
    retry_after_sec: float  # 0.0 when allowed; else seconds until 1 token is available

class RateLimiter(Protocol):
    def check(self, principal: str, cost: float = 1.0) -> Verdict: ...
```

Error contract: `check()` never raises for unknown principals (a fresh full bucket is
created); it raises `ValueError` only for `cost <= 0`.

## 5. State / graph topology

N/A — synchronous decision component, no graph.

## 6. Tool schemas

N/A — not exposed as an agent tool.

## 7. LLM step contracts

N/A — deterministic.

## 8. Eval / validation plan

Ordinary unit tests derived from §10 ACs: a fake monotonic clock drives refill; assert
verdicts at boundaries (empty, full, partial, over-cost). Property test: tokens never exceed
capacity and never go below 0.

## 9. Dependencies & integration points

Reads a monotonic clock (injected). The HTTP middleware calls `check()` and maps
`allowed=false` → `429` with a `Retry-After: ceil(retry_after_sec)` header.

## 10. Acceptance criteria

```
AC-01 WHEN a principal with a full bucket calls check(cost=1)
      THE SYSTEM SHALL return allowed=true and decrement tokens by 1.
AC-02 WHEN a principal's tokens are below cost
      THE SYSTEM SHALL return allowed=false with retry_after_sec > 0 (never allowed=true).
AC-03 WHEN elapsed time would refill above capacity
      THE SYSTEM SHALL cap tokens at capacity (never overfill).
AC-04 WHEN cost <= 0
      THE SYSTEM SHALL raise ValueError (no silent zero-cost bypass).
AC-05 WHEN bucket state cannot be read
      THE SYSTEM SHALL return allowed=true and emit a state-error metric (fail-open).
```

## 11. Open questions → deferred to task design

- Sweep strategy for idle buckets (LRU vs TTL) — an internal detail, decidable at implementation.
- Metric backend — follows the project's existing telemetry choice.
