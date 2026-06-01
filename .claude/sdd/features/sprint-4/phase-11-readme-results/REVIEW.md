# Review: sprint-4/phase-11-readme-results — README Pass + Published Results + rag-inspect

**Branch:** `sprint-4/phase-11-readme-results` | **Date:** 2026-06-01 | **Verdict:** ✅ READY

## Summary

The phase publishes the canonical 1499-record three-way baseline, ships a thin read-only
`rag-inspect` CLI, and rewrites the README results-first — all backed by the AC-8
verification gate (the over-abstention finding is genuine generator behaviour, not the
0.45 retrieval gate). The `code-reviewer` agent found one blocking stranger-test leak and
three non-blocking nits; all four were fixed in the same commit (amended). Mechanical
checks green, all 10 acceptance criteria met.

## Mechanical Checks

| Step   | Status | Notes                                               |
| ------ | ------ | --------------------------------------------------- |
| Format | PASS   | pre-commit `make format` clean on amend             |
| Lint   | PASS   | ruff check clean                                    |
| Tests  | PASS   | 229 passed, 17 deselected (corpus/smoke) in ~15–38s |

## Issues

All issues raised by the `code-reviewer` agent have been **resolved** in commit `f69900f`.

<details>
<summary>🔴 1. Stranger-test leak: personal time budget in tracked DESIGN.md — FIXED</summary>

`DESIGN.md:242,249` carried the `~5h/week budget` / "protect the time budget" phrasing
from `CLAUDE.local.md` — the same personal-context leak flagged blocking in the
sprint-2/phase-6 and sprint-3/phase-8 reviews. Rewritten to project-scope justification
("keep scope minimal"; dropped the budget clause). Verified absent from the committed tree.

</details>

<details>
<summary>⚠️ 2. AC-7 smoke test asserted only exit 0, not stdout content — FIXED</summary>

`tests/eval/test_inspect_cli.py:130` — DESIGN Phase 6 step 8 requires asserting stdout
contains the question text + a model row. Switched the unused `tmp_path` fixture to
`capsys` and added `assert "qst_0008" in captured.out` / `assert "MODEL:" in captured.out`.
This closes the silent-empty-output gap (issues 2 and 3 fixed together).

</details>

<details>
<summary>⚠️ 4. AC-8 gate test did not record which measurement method ran — FIXED</summary>

`tests/eval/test_inspect_cli.py` — the test prints the genuine-pattern fraction but did not
say whether it used the exact gold-overlap path (online `load_questions`) or the offline
proxy. Added a `Measurement method:` print line, and a one-clause README note clarifying
that 90.46% is the gold-overlap figure and 99.2% the looser proxy — both well past 70%.

</details>

<details>
<summary>⚠️ 5. frozen dataclasses with list/set fields — ACKNOWLEDGED, no change</summary>

`inspect_cli.py:18–43` — `ModelInspection`/`InspectResult` are `frozen=True` but hold
`list`/`set` fields (mutable internals, unhashable). This mirrors the repo-wide convention
in `eval/questions.py:Question`; not a new violation. Left as-is for consistency; a
repo-wide `tuple`/`frozenset` cleanup can be a future one-off.

</details>

## Acceptance Criteria

| AC    | Requirement                                | Status | Evidence                                                                                                                |
| ----- | ------------------------------------------ | ------ | ----------------------------------------------------------------------------------------------------------------------- |
| AC-1  | `baseline.jsonl` = 1499 records, 3 models  | ✅     | parsed: 1499 recs; `gpt-5-nano-2025-08-07` (499), `claude-haiku-4-5-20251001` (500), `gemini-2.5-flash-lite` (500)      |
| AC-2  | Reports regenerated, all 3 models          | ✅     | `baseline.md`/`.html` regenerated via `rag-eval report`; all 3 model names present                                      |
| AC-3  | `rag-inspect` registered + per-model story | ✅     | console script wired; output carries question text, gold facts, expected ids, per-model answer/ranked-ids/flags/metrics |
| AC-4  | No new dep, no corpus dependency           | ✅     | stdlib + existing modules only; reads JSONL + gold questions, never `corpus.jsonl`/index                                |
| AC-5  | Read-only                                  | ✅     | no `tempfile`/`os.replace`/write-mode `open` anywhere in `inspect_cli.py`                                               |
| AC-6  | Pure join/format unit-tested               | ✅     | `test_inspect_question_pure` — offline constructed records, gold-overlap + flags asserted                               |
| AC-7  | CLI smoke                                  | ✅     | `test_rag_inspect_cli_smoke` — exit 0 + stdout content assertions                                                       |
| AC-8  | Verification gate (≥70%, exhaustive)       | ✅     | all 262 claude-haiku abstention_errors; 90.46% gold-overlap / 99.2% proxy ≥ 70% — gate test asserts it                  |
| AC-9  | README section checklist (~150–200 lines)  | ✅     | 159 lines, sections in order; ADR index covers ADR-0001…0008                                                            |
| AC-10 | Reproduce path from clean clone            | ✅     | `git clone` → `uv sync` → `make dash`, ~15 min, no API keys, documented                                                 |

## KB Staleness

None blocking. No documented API/enum/constraint changed — `rag-inspect` is a read-only
sibling of `rag-classify` reusing existing schema and loaders.

Optional completeness (non-blocking): `observability/quick-reference.md` has a CLI
inventory table listing `rag-classify`; `rag-inspect` could be added there for a complete
tool roster. Defer to `/update-kb` if/when the observability domain is next touched — not
worth a standalone edit now.

## Knowledge Capture Suggestions

Marginal, optional — the "pure function + thin CLI over a JSONL+gold join" pattern is now
used twice (`classify_cli` writes atomically; `inspect_cli` is read-only). The reusable
distinction (read-only inspect vs. atomic-write classify, and the verify-the-finding-before-
publishing methodology) could become a one-paragraph `rag-eval` pattern note. Low value for
a polish phase; raise only if a third such CLI appears.

## ADR

None warranted. DESIGN concluded the same: this phase publishes and documents
already-decided substrate (the publish-strategy choice was a BRAINSTORM fork, not a durable
architectural decision); no new seam or interface.

## Suggested Next Steps

1. Open the PR for `sprint-4/phase-11-readme-results` (branch is 1 commit ahead, all gates green).
2. Remind: update the Notion-synced study track `estudos/enterprise_rag_ops/sprint-4.md` (per CLAUDE.local.md working preferences).
3. Continue Sprint 4 → next phase (Phase 12 written analysis, which reuses `rag-inspect` evidence and may pick up the deferred `--enrich-from-index`).
