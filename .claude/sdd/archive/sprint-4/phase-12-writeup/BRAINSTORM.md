# BRAINSTORM: sprint-4/phase-12-writeup — Written Analysis: Over-Abstention Finding

**Sprint/Phase:** sprint-4/phase-12-writeup | **Date:** 2026-06-01

---

## Problem Statement

The three-way baseline and the AC-8 verification are published, but the finding — that
retrieval succeeds and hallucination is rare, yet generators (especially claude-haiku)
over-abstain at high rates — is currently buried in the README's "The Finding" section.
A focused ~1500-word written analysis, grounded in the published numbers and one
concrete `rag-inspect` example, is needed to make the finding legible and sharable
for the target audience (hiring managers, AI-systems-architect recruiters).

---

## Suggested Research & KB Work

**None — coverage is sufficient.** Per SPRINT.md's knowledge plan, Phases 11–13 are
tech-agnostic writing; no KB, no deep research. The three relevant domains
(`rag-eval`, `observability`, `rag-generation`) are registered and stable. The finding
itself is fully characterized from Phase 11 (AC-8 exhaustive verification: 90.46%
gold-overlap, 99.2% proxy). No `/new-kb`, `/update-kb`, or `--deep-research` is
warranted.

---

## Approaches Considered

### Fork 1 — Publishing surface / artifact location

| Approach                                   | Description                                                                                   | Pros                                                                                                                                                                | Cons                                                                                                                                      | Effort |
| ------------------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A — Repo-native markdown                   | Committed in-repo at `docs/analysis/over-abstention.md`, linked from README's Finding section | Reviewable on GitHub without leaving the repo; version-controlled; a hiring manager inspecting the repo finds it; zero extra publishing tooling                     | Less reach; no built-in syndication; LinkedIn share needs a URL to the raw GitHub file or repo link                                       | S      |
| B — Repo markdown + external cross-post    | Commit the markdown in-repo AND post to LinkedIn (and optionally dev.to/Medium)               | Maximum reach for the audience that matters (LinkedIn = hiring managers); roadmap explicitly mentions LinkedIn share + resume link; best ROI for the portfolio goal | Adds a publishing step outside the repo; two surfaces to keep in sync if numbers change (unlikely — baseline is fixed)                    | S      |
| C — External only (LinkedIn/Medium/dev.to) | Write directly in the external platform, no in-repo file                                      | Widest reach first                                                                                                                                                  | Not reviewable from the repo; loses the "clone and inspect" chain; no version control; conflicts with the portfolio anchor being the repo | S      |

**Recommendation: Approach B — repo-native markdown as the primary artifact; LinkedIn
cross-post as the distribution step.** The roadmap calls this out explicitly. The file
lives at `docs/analysis/over-abstention.md` (or `docs/writeup/` — confirm at /define);
the README's "The Finding" section gets a "Read the full analysis" link. The LinkedIn
post can be a condensed version or a direct link to the GitHub file. Approach C is
strictly inferior for a portfolio that lives in a repo.

---

### Fork 2 — Narrative angle / framing

| Approach                                                                                              | Description                                                                                                                                                                                                                                                                                              | Pros                                                                                                                                                                                                               | Cons                                                                                                                                                | Effort |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A — Methodology-forward: "the harness caught what a leaderboard score hides"                          | Leads with the fact that all three models share nearly identical Fact Recall (~24%), yet the harness surfaces a sharp differentiation via the abstention↔hallucination axis and root-cause attribution (generator vs. retrieval)                                                                         | Directly demonstrates the project differentiator (eval harness, not SOTA scores); shows the harness design justified the custom tool choice (ADR-0001, ADR-0008); strongest for AI-systems-architect hiring signal | Slightly harder to grab a non-technical reader immediately; requires trusting the reader to care about methodology                                  | M      |
| B — Product-forward: "abstention↔hallucination as a tunable product tradeoff"                         | Leads with the three-way frontier (safety/coverage/cost), positions each model as a product decision, and uses the harness as supporting evidence                                                                                                                                                        | Immediately relatable to product/engineering managers; cost column adds business framing                                                                                                                           | Risks reading as a model benchmark post rather than an eval-harness portfolio piece; the differentiator (the harness attribution) becomes secondary | M      |
| C — Hybrid: opens with the product-tradeoff hook, pivots to root-cause attribution as the key insight | First two paragraphs: "three models, near-identical recall, but completely different risk profiles" (product hook). Central argument: "our harness pinpoints this to the generator, not retrieval" (methodology credibility). Closes with: "this is the kind of diagnostic an enterprise RAG team needs" | Best of both — accessible hook, differentiator is the conclusion; works for both hiring-manager skimmers and technical reviewers                                                                                   | Slightly harder to keep tight at ~1500 words                                                                                                        | M      |

**Recommendation: Approach C — hybrid framing.** The product hook ("same recall, wildly
different abstention profiles") lands quickly; the root-cause attribution ("we verified
this is the generator, not the retrieval gate — here is the `rag-inspect` evidence") is
the payload that earns technical credibility. Closes with a one-paragraph "what this
means for production RAG" that serves the AI-systems-architect audience. All three
ADR anchors (ADR-0001 custom judge, ADR-0008 taxonomy, ADR-0003 abstention sentinel)
can be cited inline without becoming a footnote dump.

---

### Fork 3 — Depth of concrete example

| Approach                                      | Description                                                                                                                                                                                                                                                  | Pros                                                                                                                                                               | Cons                                                                                                                               | Effort |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | ------ |
| A — One featured question walked end-to-end   | Pick one question_id (e.g. `qst_0002`, basic category); show: question text → 10 retrieved docs including gold → claude-haiku abstains ("I don't have enough information") → contrast with gpt-5-nano which answered with 80%+ precision on the same context | Maximum narrative depth; makes the failure viscerally concrete; reader can reproduce it with `rag-inspect --question-id qst_0002`; fits ~1500-word ceiling cleanly | One example cannot be "cherry-picked" appearance — must note it is drawn from 262 candidates                                       | S      |
| B — Small table of 2–3 examples across models | Show a side-by-side for 2–3 question_ids, one per model's failure mode                                                                                                                                                                                       | Demonstrates cross-model contrast more directly                                                                                                                    | Harder to maintain narrative flow; risks feeling like a data table dump rather than an argument; pushes close to 1500-word ceiling | M      |

**Recommendation: Approach A — one featured question walked end-to-end.** The argument
is already proven quantitatively (90.46% over 262 records); the example's function is
to make the pattern emotionally legible, not to prove it statistically. A single
well-chosen question — ideally basic-category, where the failure is hardest to excuse
because the retrieval was clean — is more persuasive than a table. `qst_0002` is a
confirmed candidate (basic category, 10 retrieved docs, gold overlap confirmed, claude
abstains). The exact featured question should be confirmed at /design by reading the
actual `rag-inspect qst_0002` output to verify the question text is vivid and the
gold doc is clearly relevant.

---

## Recommended Approach

Publish at `docs/analysis/over-abstention.md` (repo-native, ~1500 words), linked from
the README "The Finding" section. Framing is hybrid: product hook up front
("same recall score, very different risk profile"), methodology payload in the middle
("the harness attributes the failure to the generator — here is the verification"),
one concrete `rag-inspect` example, closes with the enterprise-RAG-ops implication.
Cross-post to LinkedIn as the distribution step (no separate artifact needed — just
the repo link or a condensed version).

This combination maximizes portfolio signal (differentiator visible in the repo itself)
and reach (LinkedIn for hiring managers), stays within ~1500 words, and is fully
grounded in already-published evidence with no new engineering required.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                                                                                                 |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | ~1500-word written analysis committed at `docs/analysis/over-abstention.md` (or `/docs/writeup/` — confirm at /define)                                                                                                                               |
| Must     | The published three-way numbers table from `results/baseline.md` (fact recall, fact precision, faithfulness, abstain precision, abstain recall, cost)                                                                                                |
| Must     | The verified root cause stated clearly: 90.46% of claude-haiku abstention_errors had `did_abstain_retrieval=False`, gold overlap non-empty, and `did_abstain_e2e=True` — confirmed by exhaustive AC-8                                                |
| Must     | Abstain precision/recall split explained: abstain precision ~10% (when models abstain, the question was usually answerable); abstain recall varies (claude catches 93% of truly unanswerable, but at the cost of over-abstaining on answerable ones) |
| Must     | One concrete `rag-inspect` example showing the failure pattern (question → gold context present → claude-haiku abstains → contrast with answering model)                                                                                             |
| Must     | README "The Finding" section updated with a "Read the full analysis" link pointing to the new file                                                                                                                                                   |
| Should   | ADR citations inline (ADR-0001 custom judge, ADR-0008 taxonomy, ADR-0003 abstention sentinel) to connect the finding to architectural decisions — shows the harness was designed to surface exactly this                                             |
| Should   | Opening hook that names the product tradeoff before diving into methodology, to engage a hiring-manager-level skimmer                                                                                                                                |
| Could    | LinkedIn cross-post (or condensed version) as a distribution step after the commit                                                                                                                                                                   |
| Could    | A brief note on what the `rag-inspect` tool is and how to reproduce the example (one sentence + the command), making the analysis self-contained for non-clone readers                                                                               |
| Won't    | Re-run any eval sweeps, change any metrics, or compute new numbers                                                                                                                                                                                   |
| Won't    | New `rag-inspect` features (e.g. `--enrich-from-index` deferred from Phase 11)                                                                                                                                                                       |
| Won't    | A chart or figure beyond inline text tables (risks scope creep; Markdown tables are sufficient and portable to LinkedIn)                                                                                                                             |
| Won't    | Comprehensive treatment of all failure modes — this is the over-abstention finding only                                                                                                                                                              |
| Won't    | Leaderboard submission (Phase 13)                                                                                                                                                                                                                    |
| Won't    | Exceed ~1500 words — polish is bottomless; one tight, evidence-backed argument ships                                                                                                                                                                 |
| Won't    | Touch any source code                                                                                                                                                                                                                                |

---

## Open Questions

1. **Featured example question_id.** `qst_0002` is a confirmed candidate (basic category,
   262-pool member). Before /define firms up the narrative, the actual `rag-inspect
--question-id qst_0002` output should be read to verify the question text is vivid
   enough to carry an argument (i.e. the question is clearly answerable, the gold doc is
   clearly relevant, and claude's abstention response is clearly unjustified). If `qst_0002`
   is weak, a better candidate should be selected from the 262-pool at /design.

2. **Artifact path convention.** `docs/analysis/over-abstention.md` vs.
   `docs/writeup/over-abstention.md` — which directory name fits the repo's docs
   organization better? The repo currently has `docs/adr/` and `docs/architecture/`;
   there is no `docs/analysis/` or `docs/writeup/` yet. Confirm preferred path at /define.

3. **LinkedIn cross-post scope.** Is the LinkedIn distribution step in-scope for Phase 12,
   or is it treated as a follow-on personal action outside the SDD? (This affects whether
   Phase 12 has a "ship" sub-step or just the committed artifact.) The roadmap mentions
   sharing on LinkedIn + resume link — clarify whether /review should gate on the post
   being live, or just on the committed markdown.

4. **Voice and POV.** First-person singular ("I built…") vs. third-person ("This project…")
   vs. "we" (inclusive of the harness as subject). The README uses third-person for the
   project description. LinkedIn posts read best in first-person. For the in-repo markdown,
   which voice is preferred?

5. **Whether to include the abstain precision/recall split as a named section or weave it
   inline.** The precision (~10%) / recall (claude 93% / gemini 70%) split is the
   quantitative heart of "over-abstention" — it is more precise than just citing abstention
   error counts. It could be a standalone table or woven into the narrative. Confirm
   treatment at /define to avoid ballooning the word count.

---

## Next Step

→ `/define sprint-4/phase-12-writeup`
