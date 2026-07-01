# Review: sprint-4/phase-12-writeup — Written Analysis: Over-Abstention Finding

**Branch:** `sprint-4/phase-12-writeup` | **Date:** 2026-06-01 | **Verdict:** ✅ READY

## Summary

The phase ships `docs/analysis/over-abstention.md` — a 1386-word analysis of one
reproducible finding (generators over-abstain despite good retrieval), plus a link from
the README "The Finding" section. The `code-reviewer` (sonnet) found no blocking issues;
all 13 acceptance criteria pass, the stranger test is clean, and no number is over-claimed
or untraceable. Two defects introduced by the `agy` draft (absolute `file:///Users/...`
ADR links and a stray `cache/` dir) were caught and fixed before commit.

## Mechanical Checks

| Step   | Status | Notes                                                 |
| ------ | ------ | ----------------------------------------------------- |
| Format | PASS   | pre-commit `make format` clean                        |
| Lint   | PASS   | ruff check clean (no code changed)                    |
| Tests  | PASS   | 229 passed, 17 deselected (prose phase, no new tests) |

## Issues

No blocking issues. Defects from the `agy` draft were fixed during implement-review (in
commit `c552941`); recorded here for traceability.

<details>
<summary>🔴 Local-path leak + broken ADR links (fixed pre-commit)</summary>

The `agy` draft rendered the three ADR citations as absolute
`file:///Users/mauricioaraujo/.../docs/adr/*.md` links — a stranger-test leak (local path

- username) and links that would not resolve on GitHub. Rewritten to relative
  `../adr/0001-eval-framework.md` / `0003-generation.md` / `0008-failure-taxonomy.md`,
  verified to resolve from `docs/analysis/`. No `/Users` / `file:///` strings remain
  (grep: 0).

</details>

<details>
<summary>⚠️ Stray <code>cache/projects.json</code> (Antigravity runtime) — removed + gitignored</summary>

`agy` wrote `cache/projects.json` (its own project-id cache, containing the local repo
path) to the repo root; it was not gitignored and would have been committed. Removed, and
`cache/` added to `.gitignore`.

</details>

<details>
<summary>⚠️ "0.45 retrieval fusion threshold" → "0.45 abstention threshold" (fixed)</summary>

`over-abstention.md:41` — the draft mislabeled the 0.45 abstention threshold as a "fusion
threshold". Corrected for technical accuracy. The sentence still correctly _rebuts_ the
gate-caused attribution (G2 holds).

</details>

<details>
<summary>⚠️ <code>.gitignore</code> change rode along in a <code>docs:</code> commit (non-blocking)</summary>

The `cache/` ignore rule is a `chore`-flavoured change committed under the
`docs(analysis):` subject. Minor convention looseness; the primary change is docs, so it
is not a Conventional Commits violation. Noted for future discipline.

</details>

## Acceptance Criteria

| AC    | Criterion                                                                                           | Status  |
| ----- | --------------------------------------------------------------------------------------------------- | ------- |
| AC-1  | `docs/analysis/over-abstention.md` exists, committed                                                | ✅      |
| AC-2  | Body ≤ 1700 words                                                                                   | ✅ 1386 |
| AC-3  | Three-way table matches `results/baseline.md`                                                       | ✅      |
| AC-4  | Root cause quantified (90.46% / 99.2% over 262), generator-behaviour framing                        | ✅      |
| AC-5  | Abstain precision/recall split present + interpreted                                                | ✅      |
| AC-6  | `qst_0126` walked end-to-end + reproduce command + "not cherry-picked"                              | ✅      |
| AC-7  | README link added; analysis does not duplicate the section                                          | ✅      |
| AC-8  | ADR-0001 / ADR-0003 / ADR-0008 each cited inline                                                    | ✅      |
| AC-9  | Opening names the product tradeoff before methodology                                               | ✅      |
| AC-10 | Non-clone reader can follow (`rag-inspect` named, command given)                                    | ✅      |
| AC-11 | No claim the harness/0.45 gate caused the abstention                                                | ✅      |
| AC-12 | Diff scope: only `docs/analysis/`, `README.md`, `.gitignore`; no source/config/eval; no new numbers | ✅      |
| AC-13 | Reviewer checklist (this review is the gate)                                                        | ✅      |

## ADR

None warranted. This phase records no architectural decision — it _cites_ ADR-0001,
ADR-0003, and ADR-0008. DESIGN concluded the same.

## Suggested Next Steps

1. Open the PR for `sprint-4/phase-12-writeup` (branch 1 commit ahead, all gates green).
2. Reminder (CLAUDE.local.md pref): update the Notion-synced study track
   `estudos/enterprise_rag_ops/sprint-4.md` to mark Phase 12 done.
3. Continue Sprint 4 → **Phase 13** (`phase-13-leaderboard`) — submit the published
   results to the EnterpriseRAG-Bench leaderboard. That is the last phase, so
   `/sprint-close sprint-4` follows it.

> Minor harness watch (not yet a proposal): the `agy` draft introduced an absolute
> `file:///` path leak (1st occurrence) and a stray `cache/` dir. The `cache/` case is now
> gitignored. If absolute-path link leaks recur in a future `agy` prose run, that crosses
> the ≥2 threshold and a guardrail (e.g. a stranger-test grep in the review checklist)
> would be worth proposing.
