# BRAINSTORM: phase-8-failure-taxonomy — Rule-Based Failure-Mode Classifier

**Sprint/Phase:** sprint-3/phase-8-failure-taxonomy | **Date:** 2026-05-30

## Problem Statement

The Phase 6 eval sweep produces one `EvalRecord` per question per model but gives no
answer to "why did this fail?" Phase 8 builds a deterministic rule-based classifier that
maps each record to exactly one failure-mode label — retrieval miss, hallucination,
abstention error, formatting, or correct — using only the aggregate signal already
persisted in the JSONL. The output powers the Phase 9 dashboard's failure-mode breakdown
and, combined with the Phoenix traces from Phase 7, lets a reviewer tell at a glance
where the pipeline broke.

---

## Research & KB Scan

| Topic                                                                   | KB file / domain                                                           | Coverage                                                                                                                                                                                                                                                                                                                                       |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EvalRecord` schema, aggregate fields, None convention                  | `.claude/kb/rag-eval/concepts/eval-record-schema.md`, ADR-0007             | Sufficient — schema is locked; the signal constraints (no per-fact/per-citation lists) are documented explicitly in ADR-0007.                                                                                                                                                                                                                  |
| None-empty-denominator convention                                       | `.claude/kb/rag-eval/concepts/none-empty-denominator.md`                   | Sufficient — the exact None semantics the classifier must honour (None faithfulness on a correct abstention is not a hallucination).                                                                                                                                                                                                           |
| Abstention scoring — predicate and two-layer gate                       | `.claude/kb/rag-eval/concepts/abstention-scoring.md`, `eval/abstention.py` | Sufficient — `should_abstain = len(expected_doc_ids) == 0`; `did_abstain_e2e` + `did_abstain_retrieval` are the two flags.                                                                                                                                                                                                                     |
| RAG failure taxonomies from the literature                              | Not in KB                                                                  | Thin — a light Exa/Context7 scan is noted in SPRINT.md as pre-work "before/at Phase 8 brainstorm." In practice, the available signal (five aggregates + two booleans + gold set) already constrains the taxonomy to a small decision space. No `/new-kb` pass is needed before `/define`; the SPRINT.md guidance to "not over-survey" applies. |
| `Question` gold fields — `expected_doc_ids`, `answer_facts`, `category` | `src/enterprise_rag_ops/eval/questions.py`                                 | Sufficient — the join key and retrieval-hit predicate are fully defined.                                                                                                                                                                                                                                                                       |
| EvalRecord schema change / ADR-0007 amendment path                      | ADR-0007 (accepted)                                                        | Sufficient — ADR-0007 explicitly records that only aggregate floats are persisted; adding a `failure_mode` tag field is an additive, non-breaking change that would amend ADR-0007 (or land in ADR-0008 as the schema decision).                                                                                                               |

**Conclusion.** No `/new-kb`, `/update-kb`, or `--deep-research` passes are needed to
unblock `/define`. The `rag-eval` KB domain covers the prerequisite contracts. The
`observability` KB domain (`/new-kb observability`) is scheduled after both ADR-0004
(accepted in Phase 7) and ADR-0008 (this phase) are settled — it will capture the
decided failure-taxonomy schema alongside the tracing pattern.

---

## Approaches Considered

### Decision 1 — Classification logic shape

Three designs for how the five labels get assigned from the available aggregate signal:

| Approach                                                            | How it works                                                                                                                                                                                                                                                                              | Pros                                                                                                                                                                                         | Cons                                                                                                                                                                                                                                                                                                                                                   | Effort |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. Priority-ordered decision cascade                                | A single function tests predicates in a fixed priority order; first-match wins a single label. Rules read like: `if abstention_error → "abstention_error"; elif retrieval_miss → "retrieval_miss"; elif hallucination → "hallucination"; elif formatting → "formatting"; else "correct"`. | Trivially unit-testable with hand-built fixtures; exactly one label guaranteed by construction; priority order is explicit in code and auditable; maps 1:1 to a documentable ADR rule table. | Priority order is a design decision that must be explicit and justified (e.g. should abstention error outrank retrieval miss?); coarse-grained — a record with both a retrieval miss and a hallucination-like score gets only one label.                                                                                                               | S      |
| B. Independent boolean predicates → multi-label, reduced to primary | Compute all five flags independently, emit a set of labels, then select primary by priority. The set is persisted as `failure_modes: list[str]`; `failure_mode: str` is the primary.                                                                                                      | Richer downstream analytics (e.g. "retrieval miss + abstention error co-occur 30% of the time"); Phase 9 dashboard can slice by any flag.                                                    | Schema is wider (two fields instead of one); the multi-label set requires more test cases; `failure_modes` is harder to explain in ADR-0008; a record with a retrieval miss will also have low recall, so "retrieval miss" and "hallucination" flags will almost always co-fire — the multi-label adds noise, not signal, given the signal resolution. | S–M    |
| C. Lookup table keyed on a tuple of discretized predicates          | Build a dict mapping `(should_abstain, did_abstain_e2e, retrieval_hit, recall_bucket, faithfulness_bucket) → label`. Thresholds bucket the continuous values; the table is the full decision space.                                                                                       | Exhaustive — every combination is explicitly handled; easy to spot missing/contradictory branches; readable in ADR-0008 as a table.                                                          | More boilerplate for a simple classifier; requires discretization constants for `recall_bucket` and `faithfulness_bucket` to be specified up front; overkill for a 5-label, 2-bool, 3-float classifier.                                                                                                                                                | M      |

**Leaning: A.** The priority cascade is the right shape for a 5-label single-output
classifier over coarse aggregates. The approach is easiest to document in ADR-0008 as
an explicit rule table, and the priority order itself is a first-class design decision
(not a hidden side-effect). Multi-label (B) adds analytical richness but at the cost of
schema complexity and misleading co-occurrence — given that low `fact_recall` and a
retrieval miss are causally linked, the multi-label set would require a suppression rule
anyway, which brings it back toward a cascade. Lookup table (C) is useful only when the
number of independent boolean dimensions exceeds ~4; here it adds no clarity.

---

### Decision 2 — Predicate definitions for each label

Given the cascade shape, the key design sub-question is how to derive each label from
the available signal. The column below is the proposed concrete predicate set; the
alternatives column captures where there is genuine ambiguity.

| Label              | Proposed predicate (from `EvalRecord` + `Question`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Alternatives / tensions                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `abstention_error` | `should_abstain != did_abstain_e2e` — covers both false abstention (answerable question, model refused) and failure-to-abstain (unanswerable question, model answered). Checked first in cascade because an abstention error overrides all other labels: a false abstention trivially has 0 fact_recall (no facts stated) which would look like "formatting" or "hallucination" if not caught first.                                                                                                                      | Could split into two sublabels: `false_abstention` (FP) and `failure_to_abstain` (FN). SPRINT.md uses a single label "abstention error"; sublabels are a Could (see scope).                                                                                                                                                                                                                                                                                |
| `retrieval_miss`   | `len(expected_doc_ids) > 0` (answerable question) AND `set(expected_doc_ids) ∩ set(retrieval_ranked_ids[:k]) == ∅` — the retriever returned zero gold docs in the top-k. Checked second because a retrieval miss is the root cause; the answer quality labels below are only meaningful when retrieval had signal to work with.                                                                                                                                                                                           | Could use a weaker predicate: `expected_recall = len(set(expected_doc_ids) ∩ set(retrieval_ranked_ids[:k])) / len(expected_doc_ids) < threshold` (e.g. < 0.5). Binary miss is simpler and maps cleanly to the retrieval metrics the eval harness already computes.                                                                                                                                                                                         |
| `hallucination`    | Retrieval hit (not a retrieval miss) AND (`faithfulness_ratio is not None` AND `faithfulness_ratio < threshold`, e.g. < 0.5) — the answer cites sources but the judge found low faithfulness (the generation fabricated content relative to its own sources). `faithfulness_ratio is None` on a correct abstention (no sources cited) — this must be guarded: if `did_abstain_e2e` is True and we reach this branch, it is never a hallucination (already guarded by abstention_error check at top; belt-and-suspenders). | The `faithfulness_ratio` aggregate does not tell us which specific fact hallucinated — only that < N% of cited docs supported the answer. This is the central precision limitation ADR-0008 must document. The threshold (0.5?) needs to be named; whether it is config-driven or a constant is Decision 3.                                                                                                                                                |
| `formatting`       | Retrieval hit AND faithfulness threshold passed (or faithfulness is None due to no sources cited AND not abstaining AND not abstention_error) AND `fact_recall is not None` AND `fact_recall < threshold` (e.g. < 0.5) AND `did_abstain_e2e == False`. Rationale: the retriever found relevant docs, the model cited them faithfully, but the final answer missed facts — a failure in answer construction / completeness, not in retrieval or hallucination.                                                             | "Formatting" is the weakest label in this taxonomy — it conflates true formatting issues (schema violations, truncation) with completeness failures (answered correctly but missed some facts). Given the available signal, these two modes are indistinguishable; ADR-0008 must be explicit that `formatting` here means "answer construction failure" not purely a structural format violation. Alternative name: `incomplete` or `answer_construction`. |
| `correct`          | Falls through all of the above — a valid positive classification, not just a catch-all. A record lands here if: no abstention error, retrieval hit (or unanswerable question with correct abstention), faithfulness above threshold (or no sources cited on a correct abstention), fact_recall above threshold.                                                                                                                                                                                                           | None — this is the right-hand leaf of the cascade.                                                                                                                                                                                                                                                                                                                                                                                                         |

---

### Decision 3 — Persistence: new field on `EvalRecord` vs sidecar JSONL vs compute-on-read

Where does the tag live after classification runs?

| Approach                                                                                                   | How it works                                                                                                                                                                               | Pros                                                                                                                                                                                 | Cons                                                                                                                                                                                                   | Effort |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| A. New field on `EvalRecord` — `failure_mode: str \| None = None`                                          | Classify once, store the tag in the record. The existing JSONL schema grows by one field; old records without the tag read as `None` (Pydantic default). Phase 9 reads the field directly. | Tag is always co-located with the record; Phase 9 has no runtime dependency on the classifier; the JSONL is self-contained; `None` sentinel cleanly represents "not yet classified." | Requires ADR-0007 amendment (or ADR-0008 to own the schema extension); the JSONL must be regenerated or augmented to carry the tag (a `rag-classify` step that reads + re-writes the JSONL).           | S      |
| B. Sidecar JSONL — separate `results/baseline_failure_modes.jsonl` keyed on `(run_id, question_id, model)` | Classifier writes a parallel file; Phase 9 joins on the key at read time.                                                                                                                  | Zero changes to `EvalRecord`; additive artifact; existing JSONL untouched.                                                                                                           | A join key must be managed; Phase 9 must load two files; two artifacts can drift out of sync; harder to distribute as a single demo artifact.                                                          | S      |
| C. Compute-on-read — Phase 9 dashboard calls the classifier inline when loading the JSONL                  | No persistence; classification happens at dashboard startup.                                                                                                                               | Zero schema change; classifier is always fresh.                                                                                                                                      | Dashboard startup is slower; Phase 9 must depend on Phase 8's classifier module; classification bugs only surface at dashboard runtime; makes the classifier's output invisible without the dashboard. | S      |

**Leaning: A.** A single persisted field is the cleanest: it makes the tag inspectable in
the JSONL without the dashboard, it is a natural additive change to a `None`-defaulted
Pydantic field, and it keeps Phase 9's data loading simple. The ADR-0008 schema decision
is precisely this field: its name, type, and the taxonomy vocabulary.

The trade-off with Approach A is that it adds a new CLI step (`rag-classify` or
`rag-eval classify`) that re-writes the JSONL with the tag. Whether this is a new
console script or a subcommand of `rag-eval` is a `/define` decision; both are S-effort.

---

## Recommended Approach

**Decision 1: Priority-ordered cascade** (Approach A). Five labels, one tag, explicit
priority order in code and ADR-0008.

**Decision 2: Predicate set as proposed.** Cascade order: abstention error → retrieval
miss → hallucination → formatting → correct. Thresholds for hallucination and formatting
as named constants in a config block (see Decision 3 note below).

**Decision 3: New `failure_mode` field on `EvalRecord`** (Approach A). Additive Pydantic
field defaulting to `None`; ADR-0008 owns the schema extension. A `rag-classify`
console script reads a JSONL and writes the tags back in-place (or to a new file with a
`--output` option).

**Overall rationale.** The minimal-scope constraint favours the smallest thing that
proves the point. The
pure-Python rule logic over persisted records needs zero LLM calls — tests are plain
fixtures, no cassettes. The cascade is the simplest shape that meets the stated
acceptance criteria (one tag per answer, ADR-0008 schema). The persistence decision
makes Phase 9 simple (single-file read). The thresholds as named module constants
(not hard-coded inline, not full config-file overhead) strikes the right balance for
this phase.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                                                                                                                                             |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | `src/enterprise_rag_ops/eval/failure_taxonomy.py` — pure-Python module: `FailureMode` enum (5 values), `classify(record: EvalRecord, question: Question) → FailureMode` function implementing the priority cascade with documented predicates. Zero LLM calls; deterministic.                                    |
| Must     | Cascade priority order: `ABSTENTION_ERROR` → `RETRIEVAL_MISS` → `HALLUCINATION` → `FORMATTING` → `CORRECT`. Each branch implemented as a named predicate function for testability.                                                                                                                               |
| Must     | Concrete predicate implementations: retrieval-hit from `expected_doc_ids ∩ retrieval_ranked_ids[:k]`; abstention-error from `should_abstain != did_abstain_e2e`; hallucination from faithfulness < threshold (with None guard); formatting from fact_recall < threshold (with None guard).                       |
| Must     | Threshold constants as module-level named values (e.g. `HALLUCINATION_FAITHFULNESS_THRESHOLD = 0.5`, `FORMATTING_RECALL_THRESHOLD = 0.5`). Not inlined as magic numbers; not yet in a config file (Could item).                                                                                                  |
| Must     | `failure_mode: str \| None = None` additive field added to `EvalRecord` in `eval/records.py`. Pydantic default `None` means "not yet classified" — backward-compatible with existing JSONL.                                                                                                                      |
| Must     | `rag-classify` console script in `pyproject.toml`; entry point `eval/classify_cli.py:main`; reads `--results` JSONL + `--questions` (question IDs loaded from gold, or streamed via `load_questions`); writes tagged records to `--output` (default: overwrite input).                                           |
| Must     | `tests/test_failure_taxonomy.py` — unit tests with hand-built `EvalRecord` + `Question` fixtures, one per label + edge cases: `None` faithfulness on correct abstention, retrieval miss with None fact_recall, full-hit correct record. No mocks, no cassettes — pure Python.                                    |
| Must     | `docs/adr/0008-failure-taxonomy.md` — ADR-0008 written and accepted in this phase. Must decide: taxonomy vocabulary (5 labels), cascade priority order, predicate definitions, threshold values and their rationale, what "formatting" means given aggregate-only signal, and the `EvalRecord` schema extension. |
| Should   | `make classify` Makefile target — runs `uv run rag-classify --results results/baseline.jsonl` after `make export-traces`.                                                                                                                                                                                        |
| Should   | ADR-0008 explicitly documents the precision limitation: classification is at aggregate granularity (e.g. hallucination means "low faithfulness ratio," not "specific fact fabricated"); the fine-grained mode (which fact, which citation) requires the deferred `supporting_doc_id` backlog.                    |
| Should   | `FailureMode` is a `str`-valued enum (compatible with Pydantic JSON serialization) so the tag round-trips cleanly through the JSONL without custom serializers.                                                                                                                                                  |
| Could    | Threshold values moved from module constants to the eval run config YAML (`configs/baseline.yaml`), following the price-table-in-config pattern. Adds config-parsing overhead; useful if thresholds need per-run tuning.                                                                                         |
| Could    | Split `abstention_error` into two sublabels: `false_abstention` (model refused an answerable question) and `failure_to_abstain` (model answered an unanswerable question). Richer analytics; wider enum.                                                                                                         |
| Could    | `--dry-run` flag on `rag-classify` — prints the classification distribution without writing the JSONL.                                                                                                                                                                                                           |
| Won't    | Fine-grained per-fact or per-citation failure attribution — requires raw verdict lists that ADR-0007 explicitly excludes from the persisted record.                                                                                                                                                              |
| Won't    | ML/learned classifier — rule-based is the stated requirement; a trained classifier would reopen the LLM dependency and require labelled training data neither available nor in scope.                                                                                                                            |
| Won't    | Changes to the eval runner (Phase 6) or the Phoenix exporter (Phase 7) — this phase is additive over the existing JSONL; no eval-path or tracing-path code is modified.                                                                                                                                          |
| Won't    | Dashboard integration — Phase 9.                                                                                                                                                                                                                                                                                 |
| Won't    | Live classification during the eval run — the classifier reads the persisted JSONL; online tagging would couple eval and taxonomy paths unnecessarily.                                                                                                                                                           |

---

## Open Questions

**Q1 — Threshold values: what do 0.5 for faithfulness and 0.5 for recall actually mean empirically?**
The proposed thresholds are placeholders. Without examining the distribution of
`faithfulness_ratio` and `fact_recall` values in the existing baseline JSONL, a 0.5
cutoff may over-classify as hallucination/formatting or under-classify. Before `/define`
pins the thresholds in the ADR, it should be clear whether (a) we pick principled values
up front and document them as design choices, (b) we look at the baseline distribution
and pick empirically, or (c) we make thresholds a config value that the user can adjust.
This is the single most consequential parameter decision in this phase.

**Q2 — What does `formatting` label actually mean, and is the name defensible?**
Given the available signal, "formatting" maps to: retrieval hit, faithfulness acceptable,
but `fact_recall` below threshold. This is better described as "incomplete answer" or
"answer construction failure" — the model found the right docs, cited them faithfully,
but still missed required facts. The name "formatting" (from SPRINT.md) implies a
structural format violation (schema, truncation), which is not detectable from the
aggregates. ADR-0008 must either rename the label or explicitly define "formatting" in
this narrowed sense. `/define` should resolve this naming decision — it affects what the
Phase 9 dashboard communicates to a reviewer.

**Q3 — EvalRecord schema extension: amend ADR-0007 or fully own the extension in ADR-0008?**
Adding `failure_mode: str | None = None` to `EvalRecord` touches ADR-0007 (accepted,
schema locked). The options: (a) ADR-0008 explicitly notes the additive extension and
acts as the authority for the new field; (b) ADR-0007 gets an amendment section. Since
ADR-0008 owns the taxonomy vocabulary, owning the field definition there too seems
natural — but the pattern for ADR amendments set by Phase 7 (ADR-0004 acceptance note)
favors amending the original ADR for schema changes. `/define` should pick the convention
so the accepted ADRs remain consistent.

**Q4 — `rag-classify` as a new console script vs a subcommand of `rag-eval`?**
Phase 6 ships `rag-eval` as the CLI entry point for evaluation. The classifier could be
`rag-classify` (new console script) or `rag-eval classify` (subcommand). A subcommand
keeps the CLI surface smaller and groups eval-adjacent functionality. A new script is
consistent with the existing console-script-per-concern pattern (`rag-ingest`,
`rag-index`, `rag-ask`, `rag-eval`, `rag-export-traces`). This is a style decision with
no functional consequence — `/define` should pick one.

**Q5 — Does the classifier need to load `Question` gold data from HF at classify time, or can it work purely from the JSONL?**
The retrieval-hit predicate requires `expected_doc_ids` from the gold `Question`, which
is not stored in `EvalRecord`. The `should_abstain` predicate also requires it. Two
options: (a) `rag-classify` loads questions from HF (requires network + pinned revision)
or from a local cache (requires the cache to exist); (b) the JSONL is augmented at eval
time to include `expected_doc_ids` and `should_abstain` directly in `EvalRecord` (a
broader schema change that is clearly Phase 6 territory). Option (b) would make the
classifier self-contained from the JSONL alone, but is out of Phase 8's stated scope. If
option (a), the `load_questions` function already handles this and the classifier simply
joins on `question_id` — the latency is acceptable for a one-time post-processing step.
`/define` must pick, because it determines whether `rag-classify` requires network access.

---

## What ADR-0008 Must Decide

1. **Taxonomy vocabulary** — the five label names (exact strings), their definitions in
   terms of the available signal, and whether "formatting" is renamed.
2. **Cascade priority order** — which label wins when multiple predicates could fire;
   the justification for abstention error being checked first.
3. **Predicate definitions** — formal predicate for each label, referencing `EvalRecord`
   fields and `Question` fields by name.
4. **Threshold values** — exact numeric constants for `faithfulness_ratio` (hallucination
   cutoff) and `fact_recall` (formatting/incomplete cutoff), with rationale for the chosen
   values.
5. **Precision limitation** — explicit statement that classification is at aggregate
   granularity; fine-grained attribution (which fact, which citation) is not achievable
   from the persisted signal alone.
6. **Schema extension** — whether `failure_mode` is added to `EvalRecord`, its type
   (`str | None`), its serialization as a `str`-valued enum, and whether this is an
   ADR-0007 amendment or fully owned by ADR-0008.

---

## Next Step

→ `/define sprint-3/phase-8-failure-taxonomy`
