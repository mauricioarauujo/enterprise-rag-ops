# BRAINSTORM: phase-18-evalrecord-reasoning — Persist Judge Reasoning + Generation Input (ADR-0010)

**Sprint/Phase:** sprint-6/phase-18-evalrecord-reasoning | **Date:** 2026-06-02

---

## Problem Statement

After Phase 17, a failed Phoenix trace shows the question, the retrieved-doc content, and
the generated answer — but **two legibility fields are still missing**: the **judge's
verdict reasoning** (`per_fact` / `per_citation`) and the **generation input prompt**
(the assembled system+user messages the generator saw). Neither is persisted today:

- `JudgeVerdict` carries `per_fact` / `per_citation` in memory at runner time, but
  `EvalRecord` **deliberately excludes them** (ADR-0007: clone-footprint / "only
  python-derived aggregates persisted").
- The generation input prompt is built inside `generate_with_stats`, used for the API
  call, then discarded — never stored anywhere.

This is the **decision/data phase**: decide _what to persist and where_ so these become
inspectable, and write **ADR-0010** (amending ADR-0007). **No hydration, no re-run** here
— Phase 19 owns the costly sweep + span hydration. This phase only makes the data
_persistable_.

A pre-existing planning decision frames the central fork — see
`docs/planning/sprint-6-raw-payload-note.md` (gitignored). The user's instinct: _"we
should have stored the full payload so a future feature doesn't force another re-run."_
That note recommends a **bronze/gold split** on a cost-asymmetry argument. This brainstorm
honours that input but presents the real alternatives so `/define` and ADR-0010 ratify
the choice on its merits, not by default.

---

## Suggested Research & KB Work

| Topic                                                                        | Coverage                                                                                                                                                       | Action                           |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| `EvalRecord` schema being amended (the ADR-0007 exclusion)                   | **Sufficient** — `rag-eval` KB `eval-record-schema`; ADR-0007 read this session. KB refresh is scheduled **after** ADR-0010 lands (per SPRINT.md), not before. | None now; `/update-kb` after ADR |
| Raw capture rides the `*_with_stats` seam                                    | **Sufficient** — `rag-eval` KB `stats-capture-seam`; verified in `openai_judge.py` / `openai_generator.py` (raw response + prompts are in scope at call time)  | None                             |
| Bronze capture vs. cassette/replay (ADR-0006) overlap — reuse, not duplicate | **Sufficient** — `rag-eval` KB `cassette-replay-eval` + ADR-0006; the note flags this as an explicit open sub-question (see Q5)                                | None — resolve in `/define`      |
| Bronze/gold ("medallion") data-layering convention                           | **Sufficient** — standard, tech-agnostic vocabulary; no library specifics needed                                                                               | None                             |
| Phoenix span hydration of reasoning fields                                   | **Phase 19 concern**, not this phase — `observability/span-attribute-mapping` covers it then                                                                   | Deferred to Phase 19             |

Coverage is sufficient. **No `--deep-research` needed** — Phase 18 is a pure decision →
ADR; SPRINT.md confirms "coverage holds."

---

## Approaches Considered

| Approach                                               | What it persists / where                                                                                                                                                                                                                                                                                   | Pros                                                                                                                                                                                                                                                                                                                                          | Cons                                                                                                                                                                                                                                                                                                           | Effort          |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| **A — Bronze raw-archive** (note's recommendation)     | Full request (messages + params) + full raw API response for **both** gen + judge calls → `data/raw_eval/{run_id}/...` (gitignored). Gold `results/*.jsonl` (`EvalRecord`) **untouched**. Legibility fields are _derived offline_ from bronze for Phase 19 hydration.                                      | **Resolves** ADR-0007 tension instead of reversing it (gold stays lean + cloneable). Future-proof: captures _everything_ dropped today (usage, finish_reason, logprobs, refusal, full prompts) — likely makes Phase 19 the **last** re-run. Footprint ~25–30 MB raw / 5–8 MB gz, gitignored = trivial.                                        | New write path + key-scheme + idempotency to design. A _separate_ derivation step (bronze → span attrs) Phase 19 must build. Bronze is gitignored → a fresh clone has **no** reasoning data (only the original author's machine does) — reproducibility relies on re-running.                                  | M               |
| **B — Extend `EvalRecord`** (direct ADR-0007 reversal) | Add bounded fields to `EvalRecord` → persisted into gold `results/*.jsonl`. Two sub-variants: **B1** full `per_fact`/`per_citation` lists + full gen prompt; **B2** a _compact rationale summary_ (e.g. counts + the contradicted/unsupported items only) + a truncated/elided prompt.                     | Simplest data flow — fields already exist in memory at runner time (`JudgeVerdict` carries the lists; prompt is local). Backward-compat is the established pattern (optional + default, like `k`, `failure_mode`). Phase 19 hydration reads straight from `EvalRecord` — no new derivation step. Data travels **with the clone** (committed). | **B1 reverses ADR-0007 wholesale** — re-adds the exact bloat it excluded (full prompts embed k=10 context chunks → large JSONL, slow clone). **B2** needs a summary-shape decision and _still_ throws away the rest of the payload (a future field = another re-run — the very thing the user wants to avoid). | S (B1) / M (B2) |
| **C — Hybrid: compact field in gold + bronze archive** | Persist a **small, bounded** derived field in gold `EvalRecord` (enough for Phase 19's trace: the `per_fact`/`per_citation` verdict lists — these are _discrete labels_, small — and optionally a compact prompt reference) **AND** capture the full raw payload to gitignored bronze for future-proofing. | Best of both: the trace is legible **from a fresh clone** (gold carries the verdicts), _and_ the full payload is archived so no future field forces a re-run. Verdict lists are genuinely small (label enums, not prose) — modest, justifiable JSONL growth. Bronze covers the bulky bits (full prompts, raw response objects).               | Largest surface this phase: both a gold-schema change **and** a bronze writer. Two things to test + keep consistent. Risk of over-engineering for a portfolio-scale dataset (~1500 records).                                                                                                                   | M–L             |

---

## Recommended Approach

**Approach C (hybrid), leaning toward its lighter end** — persist the **verdict lists**
(`per_fact` / `per_citation`) as bounded optional fields on `EvalRecord` (gold), **plus**
capture the full raw gen+judge payload to a gitignored **bronze** archive. The generation
input _prompt_ (the bulky part) goes to **bronze only**, not gold.

Rationale:

1. **The two missing fields have very different footprints — treat them differently.**
   The judge verdict lists are _discrete labels_ (`present`/`absent`/`contradicted`,
   `supported`/`unsupported`) keyed by short strings — small, and they're the actual
   "reasoning" a reviewer reads on a failed trace. The **generation input prompt** embeds
   the k=10 retrieved context chunks — this is the real bloat ADR-0007 feared. So put the
   small, high-value verdicts in gold (clone-friendly, trace legible from a fresh clone)
   and bank the bulky prompt + full raw response in gitignored bronze.

2. **It honours the user's instinct without the cost-asymmetry gamble being load-bearing.**
   The note's bronze recommendation rests on "capture is ~free during a re-run we're
   already paying for." True — but a _pure_ bronze approach (A) means a fresh clone shows
   **no** reasoning on its traces (bronze is gitignored), which undercuts the sprint's own
   "a failed trace explains itself" success criterion for anyone but the author. The
   hybrid keeps the legibility win committed while still archiving the full payload so a
   future field never forces another sweep.

3. **It resolves rather than reverses ADR-0007 — selectively.** ADR-0007's concern was
   clone footprint from _raw verdict checklists and big payloads_. The verdict label
   lists are small; the prompt is not. ADR-0010 can defend "persist the small discrete
   verdicts; exile the bulky prompt + raw objects to gitignored bronze" as a _scoped_
   amendment, not a blanket reversal.

4. **Backward-compat is the established pattern.** New gold fields are optional with
   defaults (`per_fact: list[...] | None = None`), exactly like `k` and `failure_mode`.
   Old `results/*.jsonl` keep loading; the dashboard / report / triage / inspect readers
   (Pydantic) ignore-or-default the absent fields.

5. **Bronze reuses, not duplicates, the cassette infra (ADR-0006).** vcrpy cassettes
   already record raw responses for the _test_ path. `/define` must check whether bronze
   capture can ride that recording or whether it's a distinct runtime concern (cassettes
   are test fixtures; bronze is a production-sweep artifact — likely distinct, but the
   serialization shape can be shared). Flagged as Q5.

6. **Minimal-scope guardrail.** If `/define` judges the bronze writer too much surface for
   this phase's budget, the **fallback is B2-in-gold-only** (verdict lists + _no_ prompt
   persistence) — Phase 19 hydrates verdicts onto the judge span and the generation
   span's `input.value` simply stays a "Won't" until a later phase. The verdict lists are
   the higher-value half of the legibility goal; the generation-input prompt is the
   nice-to-have. ADR-0010 should record this fallback explicitly.

Implementation shape (no commitment — for `/define` to ratify):

- `records.py`: add `EvalRecord.per_fact: list[FactVerdict] | None = None` and
  `per_citation: list[CitationVerdict] | None = None` (reuse the existing `eval/schema.py`
  models; optional + defaulted for backward-compat). **No** prompt field in gold.
- `runner.py`: populate the two new fields from the already-in-memory `verdict` when
  building `EvalRecord` (zero extra API cost — `JudgeVerdict` already carries them).
- **Bronze writer** (new, small module — e.g. `eval/bronze.py`): given a `run_id`,
  `question_id`, `model`, call type, request payload, and raw response, write
  `data/raw_eval/{run_id}/{question_id}__{model}__{gen|judge}.json`. Thread-safe (the
  runner uses `--concurrency` + per-record flush); idempotent on re-run (overwrite by
  key). Opt-in via a runner flag / config (default off, so existing sweeps don't suddenly
  write bronze). Gitignored path.
- `.gitignore`: add `data/raw_eval/` (confirm it isn't already covered by `data/`).
- ADR-0010: record the bronze/gold split, the _scoped_ amendment to ADR-0007, the
  footprint numbers, the privacy note (no secrets in payloads), and the B2-only fallback.

---

## Scope (MoSCoW)

| Priority   | Item                                                                                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Must**   | **Write ADR-0010** — bronze/gold split, scoped amendment to ADR-0007, footprint numbers, privacy note, fallback. This is the phase deliverable.             |
| **Must**   | Decide the **gold** shape: add optional `per_fact` / `per_citation` (reusing `eval/schema.py` models) to `EvalRecord`, defaulted `None` for backward-compat |
| **Must**   | Backward-compat: existing `results/*.jsonl` must still load; dashboard / report / triage / inspect readers unaffected (new fields optional)                 |
| **Must**   | Decide the **bronze** key scheme (`{run_id}/{question_id}__{model}__{gen\|judge}.json`) + idempotency-on-re-run rule, and that bronze is **gitignored**     |
| **Must**   | Confirm no secrets / API keys ever land in a bronze payload (request params are model + messages, not auth)                                                 |
| **Must**   | `runner.py` populates the new gold fields from the in-memory `verdict` (zero extra API cost)                                                                |
| **Should** | Bronze writer module + opt-in flag/config (default off); thread-safe + idempotent, respecting the runner's concurrency + crash-safe-flush model             |
| **Should** | Unit test: `EvalRecord` round-trips with and without the new fields (old-JSONL load + new-record dump)                                                      |
| **Should** | Resolve the cassette/replay (ADR-0006) overlap explicitly in ADR-0010 (reuse serialization vs. distinct artifact)                                           |
| **Could**  | A bronze→derived helper stub (signature only) anticipating Phase 19's hydration consumer — _seam named, not built_                                          |
| **Could**  | `data/raw_eval/` gzip-on-write option (footnote in ADR; ~5–8 MB gz vs. ~25–30 MB raw)                                                                       |
| **Won't**  | Any eval **re-run** — Phase 19 owns the costly sweep                                                                                                        |
| **Won't**  | Any Phoenix **hydration** of the new fields onto spans — Phase 19                                                                                           |
| **Won't**  | Persisting the **generation input prompt into gold JSONL** — bulky (embeds k=10 chunks); bronze-only if captured at all                                     |
| **Won't**  | A new derivation/replay pipeline that _reads_ bronze — Phase 19 builds the consumer; this phase only writes                                                 |
| **Won't**  | Parquet / DB storage for bronze — JSON-per-call is enough at ~1500-record scale (revisit only if the dataset grows)                                         |

---

## Open Questions (for `/define` / ADR-0010)

1. **Gold field shape — full verdict lists vs. a compact summary?** `per_fact` /
   `per_citation` reuse the existing closed `FactVerdict` / `CitationVerdict` models (small,
   discrete labels). Is the _full_ list the right gold shape, or a compact summary (counts +
   only the `contradicted` / `unsupported` items — the ones a reviewer actually inspects)?
   Full lists are simpler (models already exist) and small; the summary is even smaller but
   needs a new shape. Lean: full lists (reuse, no new model).

2. **Generation input prompt — bronze-only, or skip entirely this sprint?** The hybrid says
   bronze-only. But if the bronze writer is descoped to "Should" and slips, does Phase 19
   want the prompt at all, or is the answer (`output.value`, shipped Phase 17) + verdicts
   enough to "explain a failed trace"? ADR-0010 should state whether the generation
   `input.value` is in-scope for the sprint goal or a later add.

3. **Is bronze in-scope for Phase 18, or deferred to Phase 19 (the re-run)?** The note says
   capture _during_ the Phase-19 re-run (it's the cheap moment). So arguably Phase 18 only
   _designs_ bronze (ADR + writer module) and Phase 19 _wires it into the sweep_. Should the
   bronze writer be built+tested here (ready to use) but only _activated_ in Phase 19?

4. **Bronze idempotency on re-run.** Overwrite-by-key (same `{run_id}/{question_id}__{model}__{call}`
   path) is simplest. Confirm a re-run with the _same_ `run_id` is meant to overwrite (not
   append/version), matching the eval runner's "open output JSONL in `w` mode" semantics.

5. **Cassette/replay (ADR-0006) overlap.** vcrpy already records raw responses for tests.
   Does bronze reuse that serialization, or is it a distinct production-sweep artifact?
   (Likely distinct — cassettes are test fixtures keyed by request hash, bronze is keyed by
   `question_id` — but the JSON-serialization of a response object could be shared.)

6. **Fresh-clone legibility vs. gitignored bronze.** A pure-bronze design (Approach A)
   means a cloner sees no reasoning on traces (bronze isn't committed). The hybrid commits
   the verdicts to gold to preserve fresh-clone legibility. Does ADR-0010 accept that the
   _generation prompt_ legibility is author-machine-only (bronze), while _verdict_
   legibility travels with the clone (gold)? (Recommended: yes — verdicts are the high-value
   half and are small.)

---

## Next Step

-> `/define sprint-6/phase-18-evalrecord-reasoning`
