---
name: diagnose
description: >-
  This skill should be used when debugging a failing test, a flaky eval, or
  unexpected retrieval/generation output in enterprise-rag-ops — e.g. the user
  says "this test is failing", "why is X broken", "I'm stuck on this bug", "the
  retrieval results are wrong", "figure out why", or after a fix attempt has
  already failed once. Encodes a feedback-loop-first debugging method: build a
  fast deterministic pass/fail signal, form falsifiable hypotheses, instrument
  one variable at a time, then lock the fix with a regression test at the right
  seam. Adapted from mattpocock/skills `diagnose` (MIT).
---

# Diagnose — feedback-loop-first debugging

Bugs get fixed by tightening the loop between a change and its signal, not by
reading code harder. Build the right feedback loop and the bug is 90% solved.
Work the six phases in order; resist jumping to a fix before Phase 3.

## Phase 1 — Build the feedback loop first

Before forming any theory, construct a deterministic, repeatable pass/fail signal
that runs in seconds. Prefer, fastest first:

- A focused test: `uv run pytest -k <pattern> -x` (add `-s` to surface prints).
- An existing smoke: `make retrieval-smoke` or `make smoke` for the end-to-end
  retrieve / ask paths.
- A throwaway repro in `/tmp` that calls the smallest failing seam directly
  (e.g. one `HybridRetriever.retrieve()` or one `Generator.generate()` call).

Sharpen it until the signal is unambiguous and fast. A 2-second deterministic
loop is the goal — invest disproportionate effort here; everything downstream
depends on it.

## Phase 2 — Confirm the reproduction is the real one

Verify the failing signal reproduces the user's _actual_ symptom, not a nearby or
coincidental failure. A green-looking repro of the wrong bug wastes the rest of
the loop. State plainly what symptom is now reproduced and confirm it matches.

## Phase 3 — Rank 3–5 falsifiable hypotheses

Write 3–5 hypotheses **before** changing code, each phrased as a prediction the
Phase 1 loop can refute. Rank them by likelihood. Surface the ranked list to the
user — domain knowledge (or the `rag-retrieval` KB) often re-ranks them instantly
and saves a probe. Example shape: "If the RRF `k` constant is off, the fused order
changes but BM25-only order is stable — test by fusing with `k=0`."

## Phase 4 — Instrument one variable at a time

Add probes tagged `[DEBUG-diagnose]` so they are trivially greppable later. Change
**one** variable per run and re-check the loop. For ranking, scoring, or
performance bugs, _measure_ — do not trust logs about scores. Print the actual
fused scores out of RRF, the real chunk boundaries, the true `top_k` set; bisect
the pipeline (chunk → embed → store → fuse) to localize the stage.

## Phase 5 — Lock the fix at the right seam

Write the regression test at the architectural seam where the bug actually lives,
not a shallow unit boundary that won't catch a recurrence. The repo's seams are
the Protocols in `src/enterprise_rag_ops/retrieval/interfaces.py`
(`Embedder` / `VectorStore` / `Retriever`) and the `Generator` seam in
`generation/`. Follow the repo convention: a new module gets a mirrored test file.
For eval / LLM-API paths, use the cassette/replay pattern — never mock the API
inline (see CLAUDE.md § Conventions).

## Phase 6 — Verify and clean up

- Re-run the Phase 1 loop and confirm the original scenario no longer reproduces.
- Remove every probe: `grep -rn "DEBUG-diagnose" src/ eval/ tests/` must return
  nothing.
- Widen validation: `make verify`.
- If the bug was a re-derivation of domain knowledge, or it recurred, propose a
  KB pattern in `rag-retrieval` or an ADR — per CLAUDE.md § Self-Improvement
  Protocol (a bug class that slipped through twice is a missing-quality-gate
  trigger).
