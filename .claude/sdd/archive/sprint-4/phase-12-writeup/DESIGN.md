# DESIGN: sprint-4/phase-12-writeup — Written Analysis: Over-Abstention Finding

**Sprint/Phase:** sprint-4/phase-12-writeup | **Date:** 2026-06-01

This is a **prose / docs phase** — no `src/` module, no config, no eval re-run, no
tests. The "design" is therefore a **content architecture**: a section-by-section
skeleton with a per-section word budget, an evidence map pinning every cited number to
its source, and the finalized featured example. It is written to be self-sufficient: an
executor (Claude Code or Antigravity/Gemini per the Implement Contract) can produce the
~1500-word `docs/analysis/over-abstention.md` from this file plus the named sources,
with no further derivation.

All ground-truth below was verified this session against `results/baseline.md`, the
Phase 11 AC-8 result, and live `rag-inspect` output — **do not re-derive or recompute**
(NFR-4 / AC-12: this phase computes no new numbers).

---

## Architecture

This is a **content architecture**, not a software one. Data flow of _evidence_ into the
artifact:

```
results/baseline.md ──── three-way numbers (recall/precision/faithfulness/abstain/cost)
                              │
Phase 11 AC-8 result ──── 90.46% (gold-overlap) / 99.2% (retrieval-nonempty) over 262
                              │            claude-haiku abstention_error records
                              ▼
rag-inspect qst_0126 ──── featured end-to-end example (gold doc retrieved for all 3;
                              │            gpt + gemini answer, claude abstains)
                              ▼
docs/adr/{0001,0003,0008} ─ inline citation anchors (why the harness can attribute this)
                              │
                              ▼
            docs/analysis/over-abstention.md  (NEW, ~1500w, ≤1700 hard cap)
                              │
                              ▼
            README.md "The Finding" section  (MODIFY: add "Read the full analysis →" link)
```

The piece follows BRAINSTORM **F2 = hybrid framing**: product hook → root-cause
methodology payload → enterprise implication. The README's existing "The Finding"
section already states the 90.46% headline and the `rag-inspect` reproduce note, so the
analysis must go **deeper** (the featured example, the precision/recall mechanism, the
enterprise implication), not restate it (FR-6 / AC-7; see Guardrails).

---

## Content Architecture / Section Outline

Ordered skeleton, ~1500-word target, **≤1700 hard cap** (NFR-1 / AC-2). Word budgets are
a guide; the sum (~1450 prose) leaves headroom under the cap for the two inline tables.
Voice is **third-person**, consistent with README project voice ("the harness shows…",
"this analysis…") — never first-person "I" (resolves DEFINE Open-Q2).

### 1. Hook — the product tradeoff (~150w) — FR-8 / AC-9

Open by naming the tradeoff before any methodology. Three generators score
**near-identical Fact Recall (~24%)** yet present **wildly different risk profiles**:
claude-haiku almost never hallucinates but refuses to answer questions it could answer;
gemini-flash-lite answers more but hallucinates most; gpt-5-nano sits between. Land the
product framing in one sentence: a leaderboard recall column would call these three
models interchangeable — they are not. Pivot line into §2: "the harness makes the
difference visible."

### 2. The three-way table (~120w + table) — FR-2 / AC-3

One short paragraph introducing the table, then the **exact** three-way table (copy
values from the Evidence Map — must match `results/baseline.md` exactly). Columns: Model,
Fact Recall, Fact Precision, Faithfulness, Abstain Precision, Abstain Recall, Cost (USD).
One observation sentence: recall is flat (~24%) across all three; everything interesting
is in the _other_ columns. Do **not** reproduce the per-category breakdown — out of scope.

### 3. The tradeoff axis — abstention ↔ hallucination (~250w) — FR-4 / AC-5

Define the axis: a generator that abstains too readily fails differently from one that
hallucinates, but both fail. Give the **failure-mode counts** (Evidence Map row E5):
claude **262** abstention*error / **10** hallucination; gemini **142** abstention / **46**
hallucination; gpt **179** / **23** — claude at the over-abstain pole, gemini at the
over-answer pole, gpt between. Then the **abstain precision / recall split** as a **small
inline table** (resolves DEFINE Open-Q3 — protects the word ceiling, no standalone
section): abstain precision ~10% for all three (10.5 / 9.7 / 13.6) means \_when a model
abstains, the question was usually answerable*; abstain recall diverges sharply (claude
**93.3%** vs gpt **69.0%** / gemini **70.0%**). Interpret: claude catches nearly every
truly-unanswerable question, but pays for it by over-abstaining on answerable ones — the
two faces of one dial.

Inline table shape:

| Model             | Abstain Precision | Abstain Recall |
| ----------------- | ----------------- | -------------- |
| gpt-5-nano        | 10.5%             | 69.0%          |
| claude-haiku      | 9.7%              | 93.3%          |
| gemini-flash-lite | 13.6%             | 70.0%          |

### 4. Root-cause attribution — the methodology payload (~330w) — FR-3 / FR-7 / AC-4 / AC-8

The credibility core. Claim: the over-abstention is **genuine generator behaviour, not
the 0.45 retrieval gate firing**. Evidence (Evidence Map row E4): exhaustive over **all
262** claude-haiku abstention_error records, **90.46%** had
`did_abstain_retrieval == False` (retrieval did not gate) **AND** non-empty gold overlap
in `retrieval_ranked_ids` (the right doc was in context) **AND** `did_abstain_e2e == True`
(the generator still chose to abstain); a looser retrieval-nonempty proxy gives **99.2%**.
Both clear the 70% bar.

Cite the three ADR anchors inline, each connecting the finding to a decision **designed
to surface exactly this** (FR-7 / AC-8 — each cited at least once):

- **ADR-0008** (rule-based failure-mode taxonomy) — gives `abstention_error` a precise,
  mutually-exclusive definition, so the 262 records are a well-defined population, not a
  hand-wave.
- **ADR-0001** (custom thin per-fact judge) — per-fact recall/precision is what lets the
  harness say the question _was_ answerable from the gold context, distinguishing an
  abstention error from a legitimate refusal.
- **ADR-0003** (generation layer / abstention sentinel) — the structured abstention signal
  is what makes `did_abstain_e2e` observable per record, so abstention is measured, not
  inferred.

Close the section on the methodology point: a leaderboard score cannot separate "the
retriever failed" from "the generator refused"; this harness can, and does so
exhaustively.

### 5. The concrete example — `qst_0126` walked end-to-end (~330w) — FR-5 / AC-6 / AC-10 / NFR-2

Make the pattern legible with one featured question (finalized as **`qst_0126`**, basic
category — resolves DEFINE Open-Q1). Walk it (Evidence Map row E6):

1. **Question:** "For IronCrest Bioinformatics evaluating Redwood, what was the typical
   time to get from signup to receiving the first response token using the self-serve
   quickstart flow?"
2. **Gold fact:** "about 15 to 30 minutes" (gold doc
   `dsid_912991a0a2ce4000a55b1f67bda8c3a3`, category `basic`).
3. **Retrieval:** the gold doc **was retrieved** (gold overlap 1/1) for **all three**
   models — identical context. Retrieval is not the variable here.
4. **gpt-5-nano:** answered correctly (15–30 minutes; `failure_mode=correct`,
   fact_recall 1.0). **gemini-flash-lite:** also answered correctly (15–30 minutes plus
   extra detail).
5. **claude-haiku:** alone abstained — _"I don't have enough information to answer this
   question."_ (`failure_mode=abstention_error`, `did_abstain_retrieval=False`,
   `did_abstain_e2e=True`).

State the punchline: two of three models extracted the answer from the **exact same
retrieved context**; claude refused. Then satisfy NFR-2 / NFR-3 / AC-6 / AC-10 in one
move: name the tool in a sentence ("`rag-inspect` is a read-only inspection command shipped
in Phase 11") and give the reproduce command on its own line —
`rag-inspect --question-id qst_0126`. Explicitly note this example is **drawn from the
262-record pool that the 90.46% pattern quantifies — it is representative, not
cherry-picked** (NFR-3 / AC-6).

> Executor note — backup only if `qst_0126` proves unsuitable at write time: `qst_0166`
> (basic — gpt correct "End of Q1 2027", claude + gemini abstain). **Do not** use
> `qst_0002` — its gpt contrast hallucinated, weakening the argument.

### 6. Enterprise implication / close (~200w) — FR-8 close

What over-abstention means for production RAG: a model marketed as "safe" because it
rarely hallucinates can be its **own failure mode** when it refuses answerable questions —
a support bot that says "I don't have enough information" on a documented answer erodes
trust as surely as a wrong answer. The choice between claude, gemini, and gpt is a
**product decision** (coverage vs. safety vs. cost), and the only way to make it
deliberately is a harness that attributes failures to the right layer. Tie back to the
project differentiator: the value is not a SOTA RAG, it is the eval + observability layer
that turns a flat recall column into an actionable diagnostic. No call-to-action, no
external links (LinkedIn is Out-of-Scope per DEFINE).

---

## Evidence Map

Every cited number → its source, so the executor copies the right value and a reviewer can
trace it without re-running anything (NFR-4 / NFR-5 / AC-12). Sources: `results/baseline.md`
(B), Phase 11 AC-8 result (A8), live `rag-inspect qst_0126` (RI).

| ID  | Section        | Figure(s) to cite                                                                                                                                                                                                                                                                    | Source                                     |
| --- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| E1  | §1 Hook        | Fact Recall ~24% all three (24.6 / 24.1 / 24.0)                                                                                                                                                                                                                                      | B (Overall Summary)                        |
| E2  | §2 Table       | Recall 24.6 / 24.1 / 24.0; Precision 80.3 / 91.4 / 78.2; Faithfulness 88.1 / 92.1 / 78.6; Abstain Prec 10.5 / 9.7 / 13.6; Abstain Recall 69.0 / 93.3 / 70.0                                                                                                                          | B (Overall Summary)                        |
| E3  | §2 Table       | Cost $0.89 / $1.70 / $0.64 (baseline: $0.8861 / $1.7019 / $0.6383)                                                                                                                                                                                                                   | B (Cost & Latency)                         |
| E4  | §4 Root cause  | 90.46% (237/262, gold-overlap) and 99.2% (retrieval-nonempty proxy) of 262 claude-haiku abstention_error records; predicates `did_abstain_retrieval==False`, gold overlap non-empty, `did_abstain_e2e==True`                                                                         | A8                                         |
| E5  | §3 Axis        | Failure-mode counts: claude 262 abstain / 10 halluc; gemini 142 / 46; gpt 179 / 23                                                                                                                                                                                                   | A8                                         |
| E6  | §3 Split table | Abstain Prec 10.5 / 9.7 / 13.6; Abstain Recall 69.0 / 93.3 / 70.0                                                                                                                                                                                                                    | B (Overall Summary)                        |
| E7  | §5 Example     | qst_0126 question text; gold fact "about 15 to 30 minutes"; gold doc `dsid_912991a0a2ce4000a55b1f67bda8c3a3`, category basic; gold overlap 1/1 all three; gpt + gemini correct, claude abstains ("I don't have enough information…"); reproduce `rag-inspect --question-id qst_0126` | RI                                         |
| E8  | §4 ADRs        | ADR-0001 (custom thin per-fact judge), ADR-0003 (generation / abstention sentinel), ADR-0008 (rule-based failure-mode taxonomy)                                                                                                                                                      | `docs/adr/` (titles verified this session) |

**Rounding convention for the executor:** the body uses the rounded percentages from
`results/baseline.md` (e.g. 91.4%, 93.3%) and the rounded cost ($1.70, $0.89, $0.64); the
table must match the baseline values exactly. Do not introduce precision the source does
not have.

---

## File Manifest

Exactly two entries, both **`direct`** — prose has no specialist agent owner.

| File                               | Change                                                                                                                                                                     | Owner  | Phase order |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------- |
| `docs/analysis/over-abstention.md` | NEW (also creates the new `docs/analysis/` directory)                                                                                                                      | direct | 1           |
| `README.md`                        | MODIFY — add a "Read the full analysis →" relative link inside the existing "## The Finding" section (~line 90, after the Verification subsection); no content duplication | direct | 2           |

`docs/analysis/` is a **new directory**, sitting alongside `docs/adr/` and
`docs/architecture/` (FR-1). No `src/`, `eval/`, `observability/`, config, cassette, or
`results/` file is touched (NFR-6 / AC-12).

---

## Implementation Phases

Trivial ordering (the standard data→config→core→eval→obs→tests→docs convention collapses
to docs-only here):

1. **Write `docs/analysis/over-abstention.md`** from the §1–§6 outline using the Evidence
   Map values. Third-person voice. Two inline tables (three-way numbers; abstain
   precision/recall split). Inline ADR citations per E8. Reproduce command for qst_0126.
2. **Add the README link** — one relative-link line inside the existing "## The Finding"
   section pointing to `docs/analysis/over-abstention.md` (FR-6). Do not move or rewrite
   the existing 90.46% / `rag-inspect` content.
3. **Self-check against the AC-13 reviewer checklist** — body word count ≤1700 (NFR-1 /
   AC-2); both tables match `results/baseline.md` exactly (AC-3); root cause framed as
   generator behaviour, never gate-caused (NFR-3 / AC-11); diff touches only the two
   manifest files (AC-12); ADR-0001/0003/0008 each cited (AC-8); featured example
   reproducible and flagged as drawn-from-262 (AC-6).

**No tests.** Per the DEFINE convention note, this prose phase introduces no `src/`
module, so the `tests/<module>/test_*.py` mirroring convention does not apply; the
acceptance gate is the AC-13 reviewer checklist (mirrors Phase 11's AC-9 prose-review
gate).

---

## Infrastructure Gaps

Three-layer detection. **All ready — no new domain, concept, or specialist required.**

| Gap Type           | Area | Detail                                                                                                                                                                                                                                                          | Recommendation |
| ------------------ | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| Missing domain     | —    | All three relevant KB domains exist in `_index.yaml`: `rag-eval`, `observability`, `rag-generation`.                                                                                                                                                            | None           |
| Missing concept    | —    | Concept coverage is sufficient — failure taxonomy / abstention split (`observability`, ADR-0008), per-fact judge (`rag-eval`, ADR-0001), abstention sentinel (`rag-generation`, ADR-0003) are all stabilized. The finding is fully characterized from Phase 11. | None           |
| Missing specialist | —    | No specialist owns prose; manifest entries are `direct`. Phases 11–13 are tech-agnostic writing per the sprint knowledge plan.                                                                                                                                  | None           |

No `/new-kb`, `/update-kb`, or `/new-agent` is warranted (confirms DEFINE Infrastructure
Readiness).

---

## Consistency Check

**Verdict: ✅ CONSISTENT.** This is a 2-file prose phase — effectively single-module — so
the formal 6-pass cross-check is **skipped**; a light DEFINE↔DESIGN↔constitution pass plus
the prose-specific guardrails below stand in. No CRITICAL/HIGH drift found; all FR-1…FR-8
and NFR-1…NFR-6 map to a section + Evidence-Map row.

### Guardrails (prose-specific, must hold in the committed artifact)

| ID  | Severity | Guardrail                                                                                                                                                                                                                                                        | Where enforced                                     |
| --- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| G1  | HIGH     | **No README duplication.** The README "The Finding" section already cites 90.46% + the `rag-inspect` reproduce note. The analysis must _deepen_ (featured example, precision/recall mechanism, enterprise implication), not restate. README change is link-only. | FR-6 / AC-7; §1–§6 add net-new depth               |
| G2  | CRITICAL | **No over-claim.** The piece must state the over-abstention is **generator behaviour**, never that the harness / 0.45 gate caused it — matched to the verified 90.46% / 99.2%.                                                                                   | NFR-3 / AC-11; §4 wording                          |
| G3  | CRITICAL | **Stranger test.** `docs/analysis/over-abstention.md` is a tracked public file — NO personal/career/LinkedIn/salary/budget context. LinkedIn cross-post is Out-of-Scope per DEFINE.                                                                              | CLAUDE.local.md stranger test; DEFINE Out of Scope |
| G4  | MEDIUM   | **Third-person voice** throughout (resolves Open-Q2), consistent with README project voice.                                                                                                                                                                      | §-outline voice note                               |
| G5  | MEDIUM   | **Every number traces to a source.** Each figure maps to an Evidence-Map row (B / A8 / RI). No figure computed this phase (NFR-4).                                                                                                                               | Evidence Map; AC-12                                |

### Coverage (DEFINE requirement → manifest/section)

FR-1→manifest row 1; FR-2→§2/E2-E3; FR-3→§4/E4; FR-4→§3/E6; FR-5→§5/E7; FR-6→manifest row 2;
FR-7→§4/E8; FR-8→§1+§6. NFR-1→Impl phase 3; NFR-2→§5; NFR-3→G2; NFR-4/NFR-5→Evidence Map;
NFR-6→manifest scope. No gaps either direction.

### Constitution alignment

Minimal scope (§ Engineering Behavior) — two files, no speculative content, no code. English,
dates YYYY-MM-DD (§ Conventions). No seam/stranger-test violation. Aligned.

---

## Risks & Trade-offs

- **Word-ceiling pressure.** §4 + §5 are the two heaviest sections (~660w combined) and the
  most valuable; if the draft runs over 1700, trim §1 and §6 first, never the root-cause
  evidence or the example. The inline split table (Open-Q3 resolution) exists specifically
  to keep the precision/recall point cheap on words.
- **README drift risk (G1).** The single most likely defect is restating the README's
  90.46% paragraph. Mitigation: the analysis treats 90.46% as a _cited_ result it builds on
  (via the featured example and the ADR attribution), not as a headline to re-announce.
- **Example fragility.** `qst_0126` is pinned from verified `rag-inspect` output; the backup
  `qst_0166` is named. ACs reference "the featured example" generically, so the artifact is
  not brittle if the executor must fall back.
- **ADR worth.** No new ADR is warranted — this phase records no architectural decision; it
  _cites_ three existing ones. Flagging for completeness of the quality gate: none needed.

---

## Next Step

→ `/implement sprint-4/phase-12-writeup` — no infrastructure gaps to address first.

The implement stage may run in Antigravity / Gemini per the Implement Contract
(AGENTS.md § Implement Contract); **this DESIGN is the contract** — the section outline,
Evidence Map, and Guardrails are sufficient to write the artifact without re-deriving any
number.
