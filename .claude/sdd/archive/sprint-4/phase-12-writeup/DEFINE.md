# DEFINE: sprint-4/phase-12-writeup — Written Analysis: Over-Abstention Finding

**Sprint/Phase:** sprint-4/phase-12-writeup | **Date:** 2026-06-01

This phase produces ONE focused (~1500-word) written analysis at
`docs/analysis/over-abstention.md` on a single reproducible finding: **retrieval
succeeds and hallucination is rare, yet generators over-abstain** (abstain precision
~10%). The finding is already quantitatively proven (Phase 11 AC-8, exhaustive over all
262 claude-haiku `abstention_error` records). Phase 12 is prose only — **no source-code
changes, no eval re-runs, no new numbers computed.** Every cited figure traces to
`results/baseline.md` or the AC-8 result.

The resolved BRAINSTORM forks are carried (not re-opened): **F1** = repo-native markdown
at `docs/analysis/over-abstention.md`, linked from README; **F2** = hybrid framing
(product hook → root-cause payload → enterprise implication); **F3** = one featured
question walked end-to-end.

---

## Requirements

### Functional

All FRs are checkable by a reviewer reading the committed artifact (it is prose, so
acceptance is reviewer-checklist driven; see AC-13).

- **FR-1 (Must)** — The analysis is a single committed markdown file at
  `docs/analysis/over-abstention.md` (new directory, alongside `docs/adr/` and
  `docs/architecture/`).
- **FR-2 (Must)** — The analysis presents the published **three-way numbers table**
  (gpt-5-nano, claude-haiku-4-5, gemini-2.5-flash-lite) covering Fact Recall, Fact
  Precision, Faithfulness, Abstain Precision, Abstain Recall, and Cost — values matching
  `results/baseline.md` exactly.
- **FR-3 (Must)** — The analysis states the **verified root cause**, quantified: of
  claude-haiku's 262 `abstention_error` records, **90.46%** had
  `did_abstain_retrieval == False` AND non-empty gold overlap in `retrieval_ranked_ids`
  AND `did_abstain_e2e == True` (and **99.2%** on the looser retrieval-nonempty proxy) —
  i.e. genuine generator behaviour, not the 0.45 retrieval gate.
- **FR-4 (Must)** — The analysis explains the **abstain precision / recall split**: when
  models abstain the question was usually answerable (precision ~10%), while abstain
  recall varies sharply (claude 93.3% / gpt 69.0% / gemini 70.0%) — claude catches nearly
  all truly-unanswerable questions but at the cost of over-abstaining on answerable ones.
- **FR-5 (Must)** — The analysis walks **one concrete featured example** end-to-end:
  question text → retrieved context including the gold doc → claude-haiku abstains
  ("I don't have enough information…") → contrast with a model that answered. The example
  is reproducible via a stated `rag-inspect --question-id <id>` command, and the text
  notes it is drawn from the 262-record pool (not cherry-picked).
- **FR-6 (Must)** — The README "The Finding" section gains a **"Read the full analysis"
  link** to `docs/analysis/over-abstention.md`; the analysis does **not** duplicate the
  README section's content (it deepens it).
- **FR-7 (Should)** — The analysis cites the relevant ADR anchors inline — **ADR-0001**
  (custom per-fact judge), **ADR-0003** (generation / abstention sentinel), **ADR-0008**
  (failure taxonomy) — connecting the finding to architectural decisions that were
  designed to surface exactly this.
- **FR-8 (Should)** — The analysis opens with a **hybrid hook**: name the product
  tradeoff ("near-identical recall, very different risk profiles") before pivoting to the
  root-cause methodology payload, closing with the enterprise-RAG implication.

### Non-functional

- **NFR-1 (Word ceiling, checkable)** — Body ≤ **1700 words** (target ~1500). Polish is
  bottomless; one tight, evidence-backed argument ships. Word count is verifiable on the
  committed file.
- **NFR-2 (Self-contained)** — A reader who has **not** cloned the repo can follow the
  argument: the `rag-inspect` tool is named in one sentence and the reproduce command is
  given, so the example stands without local execution.
- **NFR-3 (No over-claim)** — The central claim must not exceed what AC-8 supports. The
  analysis must **not** assert the harness/0.45 gate caused the abstention; it must state
  the opposite (generator behaviour), matched to the verified 90.46% / 99.2%.
- **NFR-4 (No new numbers)** — No figure is computed in this phase. Every cited number
  maps to `results/baseline.md` or the AC-8 result.
- **NFR-5 (Evidence-traceable)** — Each cited number is attributable to its source
  (baseline table or AC-8), so a reviewer can confirm it without re-running anything.
- **NFR-6 (Tech-agnostic, no code)** — No source file, config, cassette, or eval artifact
  is touched. Deliverables are the new markdown file and the README link edit only.

---

## Acceptance Criteria

Each AC maps to an FR / NFR and is reviewer-checkable on the committed artifact.

1. **(FR-1)** `docs/analysis/over-abstention.md` exists and is committed.
2. **(NFR-1)** The analysis body is ≤ 1700 words (target ~1500).
3. **(FR-2)** A three-way numbers table is present and every value matches
   `results/baseline.md` (recall ~24% across all three; precision 80.3 / 91.4 / 78.2;
   faithfulness 88.1 / 92.1 / 78.6; abstain precision 10.5 / 9.7 / 13.6; abstain recall
   69.0 / 93.3 / 70.0; cost $0.89 / $1.70 / $0.64).
4. **(FR-3)** The root-cause claim is present and quantified: **90.46%** (gold-overlap)
   and **99.2%** (retrieval-nonempty proxy) of the 262 claude-haiku `abstention_error`
   records, framed as generator behaviour not the retrieval gate.
5. **(FR-4)** The abstain precision/recall split is present (precision ~10%; recall claude
   93.3% vs gpt/gemini ~69–70%) and interpreted as over-abstention on answerable questions.
6. **(FR-5)** One featured example is walked end-to-end and is reproducible via a stated
   `rag-inspect --question-id <id>` command; the text flags it as drawn from the 262-pool,
   not cherry-picked.
7. **(FR-6)** The README "The Finding" section contains a working relative link to
   `docs/analysis/over-abstention.md`, and the analysis does not copy the README section.
8. **(FR-7)** ADR-0001, ADR-0003, and ADR-0008 are each cited inline at least once.
9. **(FR-8)** The opening names the product tradeoff before the methodology pivot.
10. **(NFR-2)** A non-clone reader can follow the example: `rag-inspect` is named and the
    reproduce command is given.
11. **(NFR-3)** The analysis nowhere claims the harness/0.45 gate caused the abstention;
    the central claim matches the verified 90.46% / 99.2%.
12. **(NFR-4 / NFR-6)** Diff for this phase touches only `docs/analysis/over-abstention.md`
    and the README link — no source, config, cassette, or eval-result files; no new numbers.
13. **(Manual reviewer checklist)** A reviewer confirms AC-1 … AC-12 against the committed
    artifact and records pass/fail per item (mirrors Phase 11's AC-9 prose-review gate).

> **Convention note:** This phase ships prose only and introduces no `src/` module, so
> the `tests/<module>/test_*.py` mirroring convention does not apply — acceptance is the
> AC-13 reviewer checklist, the appropriate gate for a written artifact.

---

## Clarity Score

| Dimension       | Score | Note                                                                                                                                                                          |
| --------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**     | 3     | Root cause with evidence: over-abstention verified exhaustively (AC-8, 90.46% / 99.2% over all 262 records) as generator behaviour, not the 0.45 gate.                        |
| **Users**       | 3     | Named audience with workflow impact: hiring managers / AI-systems-architect reviewers who inspect the repo and skim for the eval-harness differentiator.                      |
| **Success**     | 3     | Measurable, falsifiable: file exists, ≤1700 words, table matches baseline, root cause quantified, example reproducible, README links, no over-claim — all reviewer-checkable. |
| **Scope**       | 3     | MoSCoW with explicit Won't list carried from BRAINSTORM; LinkedIn cross-post placed out-of-scope (see Out of Scope); single finding only, no re-runs, no code.                |
| **Constraints** | 3     | All named: ~1500-word ceiling, evidence-traceable / no-new-numbers, no over-claim beyond AC-8, tech-agnostic / no source changes, self-contained for non-clone readers.       |

**Total: 15/15 — PASS (≥12).** The resolved forks and confirmed ground-truth leave no
ambiguity that would block the gate; no clarifying questions were required.

**Audience (Users dimension):** the primary reader is a hiring manager or
AI-systems-architect reviewer evaluating the portfolio — the analysis must land the
eval-harness differentiator quickly (product hook) and earn technical credibility
(root-cause attribution) within a skim.

---

## Out of Scope (carried + resolved)

- **LinkedIn / external cross-post** — a personal follow-on action **outside the tracked
  SDD scope** (per CLAUDE.local.md stranger test: LinkedIn/resume sharing is personal
  context, not a public-repo concern). `/review` gates only on the committed markdown and
  README link, **not** on any post being live. (Resolves BRAINSTORM Q3.)
- No eval re-runs, metric changes, or new numbers (BRAINSTORM Won't).
- No new `rag-inspect` features (e.g. deferred `--enrich-from-index`).
- No charts/figures beyond inline Markdown tables.
- No comprehensive failure-mode survey — the over-abstention finding only.
- No leaderboard submission (that is Phase 13).
- No source-code changes.

---

## Infrastructure Readiness

| Dependency                                | KB domain        | Specialist                 | Status                                  |
| ----------------------------------------- | ---------------- | -------------------------- | --------------------------------------- |
| Published baseline numbers                | `rag-eval`       | (existing eval context)    | Ready — `results/baseline.md` published |
| Failure-mode taxonomy / abstention split  | `observability`  | (existing obs context)     | Ready — ADR-0008 + Phase 8 classifier   |
| Generator / abstention-sentinel behaviour | `rag-generation` | (existing gen context)     | Ready — registered in Sprint 4 Phase 10 |
| `rag-inspect` example reproduction        | `observability`  | (existing, read-only tool) | Ready — shipped Phase 11                |
| AC-8 root-cause verification result       | `observability`  | n/a                        | Ready — exhaustive over 262 records     |

**All dependencies ready. NO new KB domain and NO new agent required.** Phases 11–13 are
tech-agnostic writing (per SPRINT.md knowledge plan); the three relevant domains
(`rag-eval`, `observability`, `rag-generation`) are registered and stable, and the
finding is fully characterized. No `/new-kb`, `/update-kb`, `/new-agent`, or
`--deep-research` is warranted.

---

## Open Questions for /design (none block Clarity)

1. **Featured example id (vividness check).** `qst_0002` is the working default (basic
   category, 10 retrieved docs incl. gold, claude abstains). At /design, read the actual
   `rag-inspect --question-id qst_0002` output to confirm the question text is vivid and
   the gold doc clearly relevant; if weak, pick another from the 262-pool. The acceptance
   criteria reference "the featured example" generically so they are not brittle to the
   final id.
2. **Voice / POV.** Default: third-person, consistent with the README's project voice.
3. **Precision/recall split presentation.** Default: a small inline table for the
   precision/recall split (avoids a heavy standalone section, protects the word ceiling).

These are light /design refinements; Clarity does not depend on them.

## Next Step

→ `/design sprint-4/phase-12-writeup`
