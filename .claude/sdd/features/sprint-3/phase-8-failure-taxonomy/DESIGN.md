# DESIGN: sprint-3/phase-8-failure-taxonomy — Rule-Based Failure-Mode Classifier

**Sprint/Phase:** sprint-3/phase-8-failure-taxonomy | **Date:** 2026-05-30

This DESIGN is the **sole implement contract** — the implement stage runs in
Antigravity/Gemini against it with no other context. Every file below carries its
signatures, predicate bodies, and the FR/AC it satisfies so an executor needs no extra
discovery. The single sharpest `/design` decision DEFINE deferred — the **exact numeric
threshold values** — is **RESOLVED here** from the committed `results/baseline.jsonl`
(999 records) distribution, with the rationale to be transcribed into ADR-0008. No
`[CONFIRM @impl]` item reopens a DEFINE-level question; the residual ones are noted inline.

---

## Architecture

### Module shape

```
src/enterprise_rag_ops/eval/
├── records.py            # EDIT (the ONLY Phase 6 edit): add failure_mode: str | None = None
├── failure_taxonomy.py   # CREATE: FailureMode enum + named predicates + threshold consts + classify cascade
└── classify_cli.py       # CREATE: rag-classify entry — JSONL → gold join → classify → tagged JSONL

tests/eval/               # dir already exists (has __init__.py, conftest.py) — NO new __init__.py
└── test_failure_taxonomy.py  # CREATE: fully offline; hand-built fixtures; per-label + edges + CLI + round-trip

docs/adr/
├── 0007-eval-record-schema.md   # EDIT: ONE-LINE cross-reference to ADR-0008 (not an amendment)
└── 0008-failure-taxonomy.md     # CREATE (status accepted): vocabulary + cascade + predicates + thresholds

pyproject.toml            # EDIT: add rag-classify console script (deps unchanged — NFR-3)
Makefile                  # EDIT: add `classify` target + .PHONY entry (Should, FR-8)
```

### Why this shape

The classifier is a **pure-Python, deterministic, zero-LLM** mapping from the persisted
`EvalRecord` aggregates (+ the gold `Question` joined on `question_id`) to exactly one of
five failure modes. Unlike Phase 7's vendor-seam split, there is **no tool boundary to
isolate** here — so the design is deliberately flat: one logic module
(`failure_taxonomy.py`), one thin CLI (`classify_cli.py` mirroring `eval/cli.py`), one
additive schema field, one mirrored test, one ADR. This matches NFR-6 (minimal scope: one
module + CLI + ADR) and the house "minimal scope, clean structure" principle — there is no
likely future swap that justifies a seam, so none is built.

The logic/CLI split exists for the one reason that matters: **testability without
network**. `classify(record, question)` is pure and unit-tested with hand-built fixtures
(NFR-1); the CLI owns the one network touch (`load_questions`) and is tested with an
injected/patched `{question_id: Question}` map, never a live loader.

### Data flow

```
results/baseline.jsonl  (input contract — one EvalRecord per line; default = overwrite in place)
        │  rag-classify --results <in> [--output <out>]
        ▼
  load_questions(revision=DATASET_REVISION)  ── ONCE ──►  {question_id: Question}   # the one network touch (Q5)
        │
        ▼
  for each line → EvalRecord.model_validate_json(line)         # pydantic parse
        │
        ├─ question_id ABSENT from gold map → log warning, SKIP record (pass through untagged), continue
        ▼
  classify(record, question) -> FailureMode                    # pure cascade, zero LLM
        │   abstention_error → retrieval_miss → hallucination → incomplete → correct
        ▼
  record.failure_mode = classify(...).value                    # store the str, not the enum
        │
        ▼
  write tagged record as one JSON line  → temp file → atomic os.replace(tmp, output)   # crash-safe (Q: --output)
        │   (--dry-run: collect Counter[FailureMode], print distribution, write NOTHING)
        ▼
  committed tagged results/baseline.jsonl → Phase 9 dashboard + exit demo stay offline (NFR-5)
```

The classifier imports **nothing** under `observability/` (Phase 7) and touches **no**
eval runner / judge / retrieval / abstention logic — it depends only on
`EvalRecord` (read+write the additive field), `Question`, and `load_questions` as a
read-only collaborator (NFR-2).

---

## File Manifest

| File                                              | Change | Owner  | Phase order | Purpose / key signatures                                                                                                                                                                                                                                                                                                | FR / AC                                  |
| ------------------------------------------------- | ------ | ------ | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `docs/adr/0007-eval-record-schema.md`             | edit   | direct | 1           | Add **one line** cross-referencing ADR-0008 as the owner of the additive `failure_mode` field. **No** full amendment.                                                                                                                                                                                                   | FR-6, AC-9, Q3                           |
| `src/enterprise_rag_ops/eval/records.py`          | edit   | direct | 1           | The **only** Phase 6 edit (NFR-2). Add `failure_mode: str \| None = None` to `EvalRecord` (after `did_abstain_e2e`). Store as `str \| None` (not the enum) so old JSONL parses cleanly and `.value` round-trips. `None` = not classified.                                                                               | FR-6, AC-6, AC-11                        |
| `src/enterprise_rag_ops/eval/failure_taxonomy.py` | create | direct | 2           | `class FailureMode(str, Enum)` (5 members); `HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5`, `INCOMPLETE_RECALL_THRESHOLD = 0.5`; predicates `is_abstention_error / is_retrieval_miss / is_hallucination / is_incomplete`; `classify(record, question) -> FailureMode` first-match cascade. Pure, zero LLM, deterministic. | FR-1..FR-5, AC-1..AC-5                   |
| `tests/eval/test_failure_taxonomy.py`             | create | direct | 2           | Fully offline. Per-label fixtures + 5 edge cases (FR-12); enum-membership + Pydantic round-trip (AC-1, AC-6); offline CLI test over a 2-record JSONL with an **injected gold map** (FR-7/AC-7); `--dry-run` no-write + `--questions-revision` forwarding (AC-14). **No cassette, no network, no key.**                  | FR-12, AC-1..AC-2, AC-6..7, AC-10, AC-14 |
| `src/enterprise_rag_ops/eval/classify_cli.py`     | create | direct | 3           | `rag-classify`. `_build_parser()`; `main(argv: list[str] \| None = None) -> int`. Flags `--results`, `--output` (default overwrite), `--dry-run`, `--questions-revision`. Reads JSONL → gold join → `classify` → atomic write. Absent `question_id` → skip-with-warning.                                                | FR-7, FR-9, FR-10, AC-7, AC-14           |
| `pyproject.toml`                                  | edit   | direct | 3           | Add to `[project.scripts]`: `rag-classify = "enterprise_rag_ops.eval.classify_cli:main"`. **`[project.dependencies]` UNCHANGED** (NFR-3, AC-12).                                                                                                                                                                        | FR-7, AC-8, AC-12                        |
| `Makefile`                                        | edit   | direct | 3           | Add `classify` to `.PHONY` (line 1) and a `classify:` target running `uv run rag-classify --results $(RESULTS_FILE)` (reuse existing `RESULTS_FILE ?= results/baseline.jsonl`). Should — absence does not fail the phase.                                                                                               | FR-8, AC-13                              |
| `results/baseline.jsonl`                          | commit | direct | 4           | Run `rag-classify` once against the committed baseline (the one network step — gold join), then **commit the tagged JSONL** so Phase 9 + the exit demo stay offline (NFR-5).                                                                                                                                            | FR-7, NFR-5                              |
| `docs/adr/0008-failure-taxonomy.md`               | create | direct | 5           | Status **accepted**, date 2026-05-30. Records vocabulary, cascade order + `abstention_error`-first justification, per-label predicates by field name, **empirical thresholds (0.5/0.5) + baseline-distribution rationale**, the `incomplete` definition, the aggregate-granularity limitation, the field ownership.     | FR-11, AC-4, AC-5, AC-9, NFR-4           |

**Owner = `direct` for every entry.** No specialist agent exists for failure taxonomy
and none is warranted (NFR-3) — one additive pure-Python module + a thin CLI over a
well-documented input contract; no recurring specialist context-loading across sessions.
This mirrors the Phase 7 DESIGN's `direct`-only manifest.

---

## Pinned facts (resolve DEFINE deferrals)

### Threshold values — RESOLVED from the committed `results/baseline.jsonl` (999 records)

The empirical distribution of the committed baseline (500 Haiku-4.5 + 499 gpt-5-nano) was
measured at design time. The values below are **final** — the executor does **not**
re-pick them; it transcribes them + the rationale into ADR-0008.

- **`HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5`**, predicate `faithfulness_ratio < 0.5`
  (**strict `<`**).
  - **Distribution:** `faithfulness_ratio` is 519 non-null, 480 `None` (≈ the 478 e2e
    abstentions → no sources cited → `None` per ADR-0007 empty-denominator). Strongly
    **bimodal**: **433 records at exactly 1.0**, a low tail, **37 records < 0.5**, with a
    borderline cluster of **21 at exactly 0.5**, 58 < 0.6.
  - **Why strict `<` 0.5:** the conservative "majority of cited docs unfaithful" reading.
    The 21 `==0.5` borderline records stay **OUT** of hallucination (exactly half faithful
    is not flagged). Flags 37/519 ≈ 7.1% of grounded answers — a real, non-trivial tail,
    not noise. ADR-0008 must document the bimodal shape, the strict-`<` choice, and the
    explicit treatment of the 21 `==0.5` records.

- **`INCOMPLETE_RECALL_THRESHOLD = 0.5`**, predicate `fact_recall < 0.5`.
  - **Distribution:** `fact_recall` is 999 non-null, 0 `None`. Zero-inflated: **630 at
    exactly 0.0**, median 0.0, p75 = 0.4, p90 = 1.0, mean 0.243.
  - **Why 0.5:** "fewer than half the gold facts recovered = incomplete", symmetric with
    the faithfulness cut. The mass of zeros is dominated by the 478 abstentions +
    retrieval failures, which the cascade strips **before** `incomplete` is reached
    (`abstention_error` + `retrieval_miss` are checked first) — so the raw zeros are **not**
    the population the `incomplete` predicate sees. ADR-0008 notes the threshold is applied
    only on the **post-cascade population** (retrieval hit, faithfulness OK, not abstaining),
    so abstention/miss zero-inflation does not distort it.

### CRITICAL predicate fact — `retrieval_miss` is NOT keyed off `did_abstain_retrieval`

`did_abstain_retrieval` is `True` for **0/999** records — the retriever **never** returns
an empty list in the baseline. Therefore `retrieval_miss` MUST be computed from the
**gold-set intersection**:
`set(question.expected_doc_ids) ∩ set(record.retrieval_ranked_ids[:record.k]) == ∅`
(answerable questions only). It must **never** key off the always-`False`
`did_abstain_retrieval` flag. The retrieval-hit slice uses **`record.k`** (the persisted
per-run cut-off), not `len(retrieval_ranked_ids)`.

### `FailureMode` enum + threshold constants (FR-1, FR-4)

```python
class FailureMode(str, Enum):
    ABSTENTION_ERROR = "abstention_error"
    RETRIEVAL_MISS = "retrieval_miss"
    HALLUCINATION = "hallucination"
    INCOMPLETE = "incomplete"
    CORRECT = "correct"

HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5
INCOMPLETE_RECALL_THRESHOLD = 0.5
```

`str`-valued so the tag round-trips through the JSONL via Pydantic with no custom
serializer; the CLI assigns `record.failure_mode = classify(record, question).value` (a
plain string, never the enum object) so the schema field stays `str | None`.

### Predicate bodies (FR-3 — pin exactly; encode the `None` guards)

Each predicate takes `(record: EvalRecord, question: Question) -> bool`.

```python
def _should_abstain(question: Question) -> bool:
    return len(question.expected_doc_ids) == 0          # eval/abstention.py convention

def _retrieval_hit(record: EvalRecord, question: Question) -> bool:
    # answerable AND at least one gold doc in the top-k
    return (
        len(question.expected_doc_ids) > 0
        and bool(set(question.expected_doc_ids) & set(record.retrieval_ranked_ids[: record.k]))
    )

def is_abstention_error(record, question) -> bool:          # checked FIRST
    return _should_abstain(question) != record.did_abstain_e2e

def is_retrieval_miss(record, question) -> bool:
    return (
        len(question.expected_doc_ids) > 0
        and not (set(question.expected_doc_ids) & set(record.retrieval_ranked_ids[: record.k]))
    )

def is_hallucination(record, question) -> bool:
    # None faithfulness (no sources cited) must NEVER classify as hallucination
    return (
        _retrieval_hit(record, question)
        and record.faithfulness_ratio is not None
        and record.faithfulness_ratio < HALLUCINATION_FAITHFULNESS_THRESHOLD
    )

def is_incomplete(record, question) -> bool:
    # retrieval hit, faithfulness OK (above threshold OR None due to no sources on a
    # non-abstaining answer), recall known and below threshold, not abstaining.
    # None fact_recall must NEVER classify as incomplete.
    return (
        _retrieval_hit(record, question)
        and not is_hallucination(record, question)
        and not record.did_abstain_e2e
        and record.fact_recall is not None
        and record.fact_recall < INCOMPLETE_RECALL_THRESHOLD
    )
```

`classify` is the first-match-wins cascade in the fixed order, returning exactly one label
by construction:

```python
def classify(record: EvalRecord, question: Question) -> FailureMode:
    if is_abstention_error(record, question):
        return FailureMode.ABSTENTION_ERROR
    if is_retrieval_miss(record, question):
        return FailureMode.RETRIEVAL_MISS
    if is_hallucination(record, question):
        return FailureMode.HALLUCINATION
    if is_incomplete(record, question):
        return FailureMode.INCOMPLETE
    return FailureMode.CORRECT
```

**Why `abstention_error` first:** a false abstention (answerable question, model refused)
has `fact_recall` near 0 / `None` and no sources cited, and would mis-fire as
`incomplete` (or be a `None`-guarded `correct`) otherwise. Checking it first guarantees
the abstention mismatch is named, not masked. (FR-2, AC-2)

### `classify_cli.py` behaviour (FR-7, FR-9, FR-10 — pin the two open decisions)

Mirrors `eval/cli.py`: `argparse`, `_build_parser()`, `main(argv: list[str] | None =
None) -> int` returning `0`/`1`, `logging.basicConfig(level=logging.INFO, ...)`,
`print(f"Error: {e}", file=sys.stderr); return 1` on caught exceptions, and
`if __name__ == "__main__": sys.exit(main())`. **No subcommands** — flat flags:

| Flag                         | Required | Default                   | Behaviour                                                                            |
| ---------------------------- | -------- | ------------------------- | ------------------------------------------------------------------------------------ |
| `--results <path>`           | yes      | —                         | Input JSONL (one `EvalRecord` per line).                                             |
| `--output <path>`            | no       | = `--results`             | Tagged output. Default overwrites the input.                                         |
| `--dry-run` (Could, FR-9)    | no       | `False`                   | Print the per-`FailureMode` distribution (`collections.Counter`); write **nothing**. |
| `--questions-revision <sha>` | no       | `config.DATASET_REVISION` | Forwarded to `load_questions(revision=...)`; overrides the pinned SHA.               |

Flow: build the gold map once —
`gold = {q.question_id: q for q in load_questions(revision=args.questions_revision)}`;
read each `--results` line into `EvalRecord.model_validate_json(line)`; look up
`gold[record.question_id]`; on hit `record.failure_mode = classify(record, question).value`.

- **`--output` write semantics (DECIDED — temp-then-atomic-rename):** write tagged
  records to a temp file in the output's parent dir, then `os.replace(tmp, output)`. Because
  the default overwrites `--results` in place, an atomic replace prevents truncating the
  input on a mid-run crash. (Pinned to resolve DEFINE's open `--output` semantics.)
- **Missing `question_id` (DECIDED — skip-with-warning, do NOT crash):** if
  `record.question_id` is absent from the gold map, `logger.warning("question_id %s not in
gold set; skipping classification", record.question_id)` and **pass the record through
  untagged** (`failure_mode` stays `None`); do **not** raise. Rationale: a partial JSONL
  (e.g. a dev subset, or gold drift) still classifies the records it can — robustness over
  fail-fast for a one-time idempotent classifier whose default overwrites in place.
  (Pinned to resolve DEFINE's open raise-vs-skip question.)
- `--dry-run` short-circuits the write entirely (no temp file created), returns `0` after
  printing the distribution.

---

## Implementation Phases

Per DEFINE § Sequencing Notes — one PR on `sprint-3/phase-8-failure-taxonomy`, this commit
order (Data schema → core logic + tests → CLI wiring → tagged-data commit → docs/ADR):

1. **Additive schema field + ADR-0007 cross-ref.** Add `failure_mode: str | None = None`
   to `EvalRecord` (`eval/records.py`); add the one-line ADR-0008 cross-reference to
   `docs/adr/0007-eval-record-schema.md`. Commit:
   `feat(eval): add additive failure_mode field to EvalRecord (ADR-0008)`.
2. **Classifier core + offline tests.** `eval/failure_taxonomy.py` (`FailureMode`, named
   threshold constants, named predicates, `classify` cascade) →
   `tests/eval/test_failure_taxonomy.py` (per-label + 5 edge fixtures, enum membership,
   Pydantic round-trip). Commit:
   `feat(eval): rule-based failure-mode classifier + offline tests`.
3. **CLI + console script + (Should) `make classify`.** `eval/classify_cli.py`
   (flags, gold join, atomic write, skip-with-warning) + the `rag-classify` entry in
   `pyproject.toml [project.scripts]` + `make classify` (+ `.PHONY`). Extend the test file
   with the offline CLI test (injected gold map), `--dry-run` no-write, and
   `--questions-revision` forwarding. Commit:
   `feat(eval): rag-classify CLI + make classify`.
4. **Run once + commit the tagged baseline.** Run
   `uv run rag-classify --results results/baseline.jsonl` (the one network step — gold
   join), then commit the tagged JSONL. Commit:
   `chore(results): tag baseline.jsonl with failure_mode for Phase 9`.
5. **ADR-0008 written + accepted.** `docs/adr/0008-failure-taxonomy.md` (status accepted,
   date 2026-05-30) with the seven required sections (FR-11a–g), incl. the empirical
   threshold values + the baseline-distribution rationale from § Pinned facts above.
   Commit: `docs(adr): accept ADR-0008 — failure taxonomy + thresholds`.

**Coulds (absence does not fail the phase):** `--dry-run` (FR-9) and
`--questions-revision` (FR-10) fold into phase 3 (both cheap — argparse flags already in
the parser spec above, gated in the flow). `make classify` (FR-8, a Should) is in phase 3.

**Validation gate:** `make lint test` — offline, no network, no API key, no cassette.
The classifier issues zero LLM calls, so ADR-0006's cassette/replay rule is correctly N/A.

---

## Infrastructure Gaps

| Gap Type           | Area             | Detail                                                                                                                                                                                                                                                                                    | Recommendation                                                                 |
| ------------------ | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Missing domain     | `observability`  | No `observability` KB domain in `_index.yaml` (`domains:` has only `rag-eval`, `rag-retrieval`). **Correctly deferred** per SPRINT.md — `/new-kb observability` runs **after** ADR-0008 acceptance, to capture the _decided_ taxonomy schema. **Not blocking** `/design` or `/implement`. | `/new-kb observability` at `/review` / sprint-close (deferred, not now).       |
| Concept coverage   | `rag-eval`       | The classifier's **input contract** is fully covered: `eval-record-schema` (the aggregates + the additive field), `none-empty-denominator` (the `None` faithfulness/recall guards), `abstention-scoring` (the `should_abstain` empty-gold predicate). No new concept needed for input.    | None for input. The decided taxonomy lands in the deferred `observability` KB. |
| Concept coverage   | `rag-generation` | Empty unregistered scaffold. The classifier reads the abstention sentinel contract, but `rag-eval`'s `abstention-scoring` already documents `should_abstain` — prerequisite met. Off the critical path.                                                                                   | `/new-kb rag-generation` is an optional cheap-debt cleanup, **not** a gate.    |
| Missing dependency | —                | **None.** `datasets` (for `load_questions`) and `pydantic` (`EvalRecord` parse/serialize) are already runtime deps. `pyproject.toml [project.dependencies]` is unchanged (NFR-3, AC-12).                                                                                                  | No action.                                                                     |
| Missing specialist | failure taxonomy | No specialist agent exists or is warranted (registry: kb-architect, brainstorm/define/design-agent, code-reviewer). One additive pure-Python module + CLI over a documented contract — no recurring context-loading.                                                                      | None. Revisit only if Phase 9 + future taxonomy work create a recurring loop.  |

**No `/new-kb` or `/new-agent` blocks `/design` or `/implement`.** Both KB items
(`observability` deferred to sprint-close, `rag-generation` optional) are non-blocking, as
the DEFINE Infrastructure Readiness table already established.

---

## Consistency Check

Scope: one logic module + a thin CLI + an additive field + two ADR edits + pyproject/Makefile
wiring — above the trivial single-module bar, so a LIGHT six-pass cross-check was run
(DEFINE↔DESIGN + constitution: AGENTS.md Conventions/Engineering Behavior, ADR-0006
cassette rule, ADR-0007 schema authority, NFR-2 additive invariant).

**Verdict: ✅ CONSISTENT** — no CRITICAL/HIGH/MEDIUM. One strength noted: the threshold
number-picking DEFINE deferred to `/design` is **RESOLVED here** with concrete empirical
values + rationale (S1), so the implementer has no parameter to invent.

| ID  | Severity | Pass         | Location                                  | Finding                                                                                                                                                                                                                               | Suggested fix / note                                                                                    |
| --- | -------- | ------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| S1  | —        | 2/3 strength | DEFINE Q1/FR-4 vs DESIGN                  | DEFINE deliberately deferred the exact threshold values to `/design` + `/implement`. This DESIGN resolves them (0.5/0.5) from the measured 999-record distribution, with the strict-`<` and post-cascade-population rationale pinned. | A strength, not a gap. Executor transcribes into ADR-0008; does not re-pick.                            |
| N1  | LOW      | 3 Underspec  | DEFINE Q5 / FR-7 (`--output`, missing id) | DEFINE left `--output` in-place-vs-rename and the absent-`question_id` raise-vs-skip open.                                                                                                                                            | Pinned: temp-then-atomic-rename; skip-with-warning. Both justified in § Pinned facts. No DEFINE change. |

**Pass-by-pass (no findings → confirmations):**

1. **Duplication** — no overlapping requirements. `is_hallucination` (faithfulness) and
   `is_incomplete` (recall) are cleanly separated by field and by cascade order. No drift.
2. **Ambiguity** — the one vague descriptor DEFINE left ("empirically grounded thresholds")
   is now concrete (0.5/0.5 + distribution). No unresolved `TODO`/`???`/placeholder.
3. **Underspecification** — only N1 (resolved). Every manifest entry maps to a named FR/AC;
   every FR has a signature/predicate/behaviour pinned here.
4. **Constitution** — **no violations.** NFR-2 additive invariant holds: the **only** edit
   to existing `eval/` code is the single `failure_mode` field (AC-11); no `configs/`, no
   `observability/`, no runner/judge/retrieval/abstention change. **ADR-0006 cassette rule
   is correctly N/A** — the classifier issues no LLM calls, so there is nothing to
   record/replay; the CLI test injects a `{question_id: Question}` map, never a mocked LLM
   API or a live `load_questions` (NFR-1). **ADR-0007 stays the schema authority** — ADR-0008
   owns the additive field with a one-line cross-ref, not an amendment (Q3). Stranger test
   holds (no career/personal content in any tracked Phase 8 file). Conventions: English,
   YYYY-MM-DD, Conventional Commits, **mirrored subdir test** (`tests/eval/test_failure_taxonomy.py`,
   not a flat file) — all honoured.
5. **Coverage** — all 12 FRs + 7 NFRs map to ≥1 manifest entry: FR-1/FR-2/FR-3/FR-4/FR-5 →
   `failure_taxonomy.py`; FR-6 → `records.py` + ADR-0007 edit; FR-7 → `classify_cli.py` +
   pyproject; FR-8 → Makefile; FR-9/FR-10 → `classify_cli.py` + test; FR-11 → ADR-0008;
   FR-12 → `test_failure_taxonomy.py`. NFRs are cross-cutting (additive scope, offline
   tests, no-new-dep) and satisfied by the manifest as a whole. No orphan manifest entries.
6. **Inconsistency** — none. Terminology consistent: "cascade", "first-match-wins",
   "retrieval hit", "gold-set intersection", "post-cascade population", the five exact label
   strings — all match DEFINE. The `incomplete` (not `formatting`) rename is honoured
   throughout (Q2).

---

## Risks & Trade-offs

- **Threshold sensitivity (the resolved S1).** Both cuts are 0.5, derived from the
  baseline's bimodal faithfulness + zero-inflated recall. The `==0.5` faithfulness cluster
  (21 records) sits exactly on the strict-`<` boundary, so a future model whose distribution
  is centred differently could shift the hallucination rate noticeably. Mitigation: the
  values are **named module constants** (FR-4) and ADR-0008 documents the distribution they
  came from — re-tuning is a one-line constant change + an ADR addendum, not a redesign.
  No config-YAML (explicit Won't — over-engineering for a one-time classifier).
- **`did_abstain_retrieval` is always `False` in the baseline.** Keying `retrieval_miss`
  off the always-`False` flag would silently make the predicate never fire. The gold-set
  intersection on `record.retrieval_ranked_ids[:record.k]` is the correct signal and is
  pinned in § Pinned facts. Risk is mitigated by an explicit per-label fixture (FR-12) plus
  the edge-case fixture (retrieval miss with `None` `fact_recall` → `retrieval_miss`, not
  `incomplete`).
- **One network step (the gold join).** `load_questions` streams from HF once at
  `rag-classify` time; the committed tagged JSONL keeps Phase 9 + the exit demo offline
  (NFR-5). If HF is unreachable during the one-time run, the maintainer can pass a pinned
  `--questions-revision`; tests never touch the network (injected gold map).
- **Atomic-write / skip-with-warning.** The temp-then-rename avoids truncating the input on
  a crash (default overwrites in place); skip-with-warning keeps a partial JSONL usable.
  Both favour robustness for a one-time idempotent classifier over fail-fast — a deliberate,
  documented trade-off.
- **ADR-worthy decisions:** **ADR-0008 only** (written + accepted this phase — it owns the
  taxonomy + the additive field). No new ADR number beyond 0008; ADR-0007 is cross-referenced,
  not amended. The aggregate-granularity precision limitation (no per-fact / per-citation
  attribution — NFR-4) is a stated ADR-0008 consequence, with the `supporting_doc_id`
  backlog left out of scope.

---

## Next Step

→ `/implement sprint-3/phase-8-failure-taxonomy`

The implement stage runs in **Antigravity / Gemini** against this DESIGN.md as the sole
contract (per AGENTS.md § Implement Contract). The thresholds and predicate bodies are
fully pinned — no `[CONFIRM @impl]` parameter remains. Follow the phase order, then run
`make lint test` (offline, no network/key/cassette) as the gate, and commit the tagged
`results/baseline.jsonl` from the one-time `rag-classify` run.
