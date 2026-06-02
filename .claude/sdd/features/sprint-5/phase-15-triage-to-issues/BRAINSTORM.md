# BRAINSTORM: sprint-5/phase-15-triage-to-issues — Triage to GitHub Issues

**Sprint/Phase:** sprint-5/phase-15-triage-to-issues | **Date:** 2026-06-01

---

## Problem Statement

Phase 14 (`rag-triage`) ships a deterministic `results/triage.json` artifact — one
`TriageCluster` per `(failure_mode, category)` pair, a `dominant_cluster` pointer, and
a `representative_question_id` per cluster. That artifact currently goes nowhere: the
loop is open. Phase 15 closes it by consuming `triage.json` and drafting one GitHub
Issue per dominant failure cluster, each grounded in real cluster stats and a concrete
`rag-inspect`-style example. Creating a real GitHub Issue is a hard-to-reverse external
action, so dry-run / draft is the default; live creation is explicit opt-in and
idempotent via a deterministic cluster-signature dedup key embedded in the issue body.
ADR-0009 records the integration and idempotency design decisions.

---

## Suggested Research & KB Work

Research is complete (Exa scan run before this brainstorm). No `--deep-research` is
needed for this phase. KB additions are correctly deferred until after ADR-0009 lands.

| Topic                                                                              | Coverage                                                               | Action                                                                               |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| GitHub Issues idempotency — body-marker fingerprint + pre-create search            | sufficient — Exa findings folded in below; no KB entry exists yet      | No `/new-kb` now; `/update-kb rag-eval` after ADR-0009 (Sprint plan)                 |
| `gh` CLI vs PyGithub/REST integration patterns                                     | sufficient — Exa findings folded in; no KB entry exists                | No action now; ADR-0009 records the decision                                         |
| Dry-run / draft-by-default + atomic write (house pattern)                          | sufficient — `classify_cli.py` + `triage_cli.py` are the live examples | Reuse                                                                                |
| Pure-core + thin-CLI split (house pattern)                                         | sufficient — `inspect_cli.py` / `classify_cli.py` / `triage_cli.py`    | Reuse                                                                                |
| `triage.json` contract (`TriageReport`, `TriageCluster`, `SCHEMA_VERSION = "1.0"`) | sufficient — Phase 14 shipped; exact shape confirmed in source         | Reuse: `triage.py` `_report_to_dict`, `SCHEMA_VERSION`, `TriageCluster`              |
| `rag-inspect`-style rendering for the concrete example in each issue body          | sufficient — `inspect_cli.py` is the live example                      | Reuse the rendering pattern (question text, failure mode, representative)            |
| `triage-to-issues` KB concept / pattern (cluster→issue idempotency contract)       | thin — not yet documented                                              | `/update-kb rag-eval` **after ADR-0009 lands** (Phase 15 post-impl, per sprint plan) |

---

## Approaches Considered

### Research grounding (Exa findings — folded in, not re-researched)

Key findings that constrain all three approaches:

- **Dominant idempotency pattern:** embed a deterministic hidden HTML comment
  (`<!-- rag-triage-cluster: <fingerprint> -->`) in the issue body, computed from the
  stable cluster key `(failure_mode, category, schema_version)`. Pre-create search via
  `gh issue list --search "<fingerprint> in:body"` or the REST `search/issues` endpoint.
  If found: skip (or update). If not found: create. This is the production-dominant
  pattern (seen in `gh-aw`, `gastownhall/beads`, `octokit-plugin-unique-issue`).
- **GitHub has no server-side uniqueness** on issues; dedup is best-effort, bounded by
  search-index propagation delay. Acknowledged as a known limitation.
- **`gh` CLI vs PyGithub:** `gh issue create/list --search` uses ambient auth
  (`gh auth`/`GH_TOKEN`), zero new Python deps, subprocess calls. PyGithub gives typed
  `repo.create_issue()`/`repo.get_issues()`, is import-testable without subprocess, but
  adds a new dependency plus token-handling code.
- **LLM-draft vs deterministic template:** the sprint's gadget risk explicitly demands
  issues grounded in real cluster stats. A deterministic template is the safe v1; LLM
  prose belongs behind a seam as a Should/Could, not a Must.
- **Dry-run default and `--create` explicit opt-in** are mandatory given the outward-
  facing side-effect risk (sprint Risks section).

### Axis summary

| Approach                                                | GitHub client                             | Idempotency                                          | Drafting                                     | Dry-run output                                      | Effort |
| ------------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------- | -------------------------------------------- | --------------------------------------------------- | ------ |
| A — `gh` CLI subprocess, no seam                        | `gh` subprocess, direct                   | Body-marker + `gh issue list --search`               | Deterministic template                       | Print draft markdown to stdout; no file write       | S      |
| B — Pure core + thin CLI with client seam (recommended) | Seam (Protocol); `gh` CLI as default impl | Body-marker + pre-create search at the seam boundary | Deterministic template; LLM slot behind seam | Write `results/issues/*.md` drafts + stdout summary | M      |
| C — PyGithub REST client, no seam                       | PyGithub directly                         | Body-marker + `get_issues(state="open")` filter      | Deterministic template                       | Write draft markdown files                          | M      |

---

### Approach A — `gh` CLI subprocess, no seam

**How it works.** A single new `eval/issues_cli.py` calls `subprocess.run(["gh", ...])`.
Issue drafting is inlined in the CLI. Dry-run prints the draft to stdout only; no file
written. No pure-core module boundary.

**Pros.** Smallest file surface; zero new Python dependencies; `gh` ambient auth works
out of the box; fast to ship.

**Cons.** Subprocess calls are hard to test offline without mocking the subprocess
layer; the whole module becomes untestable without `gh` present. No pure-core unit for
`IssueDraft` generation means tests must be integration tests. Inline draft logic in the
CLI cannot be reused or seam-swapped. Violates the house pure-core + thin-CLI split
established by every prior eval module. Dry-run output is not a persistent artifact
(can't be reviewed offline without re-running).

---

### Approach B — New `eval/issues.py` pure core + thin `eval/issues_cli.py` with client seam (recommended)

**How it works.** `eval/issues.py` is a pure, offline module that converts a
`TriageCluster` (plus the `TriageReport` header and a representative `InspectResult`)
into an `IssueDraft` dataclass — title, body (deterministic markdown template grounded
in cluster stats + representative question text), and the body-marker fingerprint
`<!-- rag-triage-cluster: {failure_mode}|{category} schema={schema_version} -->`.
No I/O, no subprocess, no network — fully offline-testable.

`eval/issues_cli.py` is the thin CLI that:

1. Loads `triage.json`, asserts `schema_version == "1.0"`.
2. Determines target clusters (dominant only by default; `--all-clusters` flag widens).
3. Calls `issues.py` to produce `IssueDraft` objects deterministically.
4. Writes draft markdown files to `results/issues/<failure_mode>-<category>.md` atomically.
5. On `--create`: calls the GitHub client (injectable via a `GitHubClient` Protocol seam)
   to search for the fingerprint, skip if found, create if not.

The `GitHubClient` Protocol has two methods: `search_issues(query: str) -> list[dict]`
and `create_issue(title: str, body: str, labels: list[str]) -> str` (returns URL).
Default impl uses `gh` CLI subprocess. Tests inject a stub that never calls the network.

Dry-run (default): write `results/issues/` markdown drafts + print a summary table.
`--create` opt-in: also performs the idempotent GitHub creation.

**Pros.** Matches the house split exactly (mirrors `triage.py` / `triage_cli.py`);
pure core is fully offline-testable; the GitHub-client choice is a localized decision
(ADR-0009 resolves it); LLM-draft can be wired behind the seam later without touching
the CLI; draft markdown artifacts are reviewable offline before any `--create` is run;
consistent with the eval cassette/replay ethos (no live network in tests).

**Cons.** Two new files; the `GitHubClient` Protocol seam adds a small abstraction cost.
The seam is justified here: the `gh` vs PyGithub decision is the sprint's explicit open
question (ADR-0009 call), and the seam makes that swap a localized 10-line change.

---

### Approach C — PyGithub REST client, no seam

**How it works.** Like Approach B's pure core, but the CLI imports `PyGithub` directly
(`from github import Github`). Pre-create search uses `repo.get_issues(state="open")`
filtered by the fingerprint in the body.

**Pros.** Typed Python API; no subprocess; clean `repo.create_issue()`/`repo.get_issues()`
calls testable with mocks.

**Cons.** Adds `PyGithub` as a new runtime dependency (currently not in `pyproject.toml`);
token handling requires an explicit `GITHUB_TOKEN` env var (no ambient auth like `gh
auth`). Locking in PyGithub directly means the `gh` vs REST decision is baked in without
an ADR — the opposite of what the sprint plan calls for. The `get_issues` scan is less
precise than `gh --search "fingerprint in:body"` for a large repo (full body scan vs
indexed search). Fails the sprint requirement: "the integration boundary recorded in
ADR-0009."

---

## Recommended Approach

**Approach B.**

It is the only approach that fully satisfies all sprint Must criteria without violating
the house patterns or the sprint's risk constraints:

- **Gadget risk (sprint):** the pure core drafts from real `TriageCluster` data, not
  generic prose — the deterministic template is grounded in `count`, `rate`,
  `representative_question_id`, `representative_question_text`, and `models_seen`.
- **Outward-facing side-effect risk (sprint):** dry-run is the default; `--create` is
  explicit opt-in; idempotency via body-marker fingerprint is in the pure core (not the
  CLI), so it is unit-testable offline.
- **House structure (AGENTS.md Engineering Behavior):** pure-core + thin-CLI split,
  atomic write, offline test mirror — all inherited from the established pattern.
- **ADR-0009:** the `GitHubClient` seam makes the `gh`-vs-REST decision exactly what
  ADR-0009 records — a localized, named future swap, not premature abstraction.
- **Scope discipline:** LLM-draft sits behind the same seam as a Should/Could; it never
  blocks the deterministic Must path.

---

## Scope (MoSCoW)

| Priority | Item                                                                                                                                                                 |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Must     | `eval/issues.py` — pure core: `IssueDraft` frozen dataclass + `build_issue_draft(cluster, report, inspect_result) -> IssueDraft`; offline, no I/O                    |
| Must     | Deterministic markdown template in `IssueDraft.body`: cluster stats (`count`, `rate`, `failure_mode`, `category`, `models_seen`) + representative question + example |
| Must     | Body-marker fingerprint: `<!-- rag-triage-cluster: {failure_mode}\|{category} schema={schema_version} -->` embedded in the body (the idempotency key)                |
| Must     | `eval/issues_cli.py` — thin CLI: load `triage.json`, assert `schema_version == "1.0"`, produce `IssueDraft`s, write `results/issues/*.md` atomically                 |
| Must     | Dry-run / draft-by-default: write markdown drafts to `results/issues/`, print summary table; no network call                                                         |
| Must     | `--create` explicit opt-in: calls `GitHubClient.search_issues` for the fingerprint; skips if found (idempotent); creates if not                                      |
| Must     | `GitHubClient` Protocol seam with two methods (`search_issues`, `create_issue`); default impl uses `gh` CLI subprocess                                               |
| Must     | `tests/eval/test_issues.py` — offline unit tests; GitHub client stubbed via the seam; no subprocess, no network                                                      |
| Must     | **ADR-0009** — records the integration + idempotency decision (`gh` CLI vs REST, body-marker dedup, dry-run contract)                                                |
| Must     | `rag-issues = "enterprise_rag_ops.eval.issues_cli:main"` registered in `pyproject.toml`                                                                              |
| Should   | Idempotent skip-if-exists on real `--create` (fingerprint search → skip with message if already open)                                                                |
| Should   | `--dominant-only` default (draft for dominant cluster only); `--all-clusters` flag to widen to all clusters in `triage.json`                                         |
| Should   | `models_seen` context rendered in the issue body (e.g. "Observed across: gpt-4o, claude-3-5-sonnet")                                                                 |
| Could    | LLM-drafted prose for the issue body behind the `IssueDraft` seam (a `DraftStrategy` Protocol), never blocking the deterministic Must path                           |
| Could    | Update-existing-issue path (not just skip-if-found; send a comment or edit the body)                                                                                 |
| Could    | Levenshtein fuzzy title dedup as a secondary guard (on top of the body-marker primary)                                                                               |
| Could    | Label management (`--labels` flag passed through to `create_issue`)                                                                                                  |
| Won't    | Phase 16 Phoenix enrichment — independent thread, not a dependency here                                                                                              |
| Won't    | Re-running the eval sweep or rag-classify (consume already-published artifacts only)                                                                                 |
| Won't    | Multi-repo issue creation                                                                                                                                            |
| Won't    | Auto-close / auto-triage / auto-assign automation (scope-creep-into-a-bot, per sprint Risks)                                                                         |
| Won't    | Generic issue bot that drafts without grounding in real cluster data                                                                                                 |
| Won't    | `triage-to-issues` KB entry in this phase (deferred to post-ADR-0009, per sprint plan)                                                                               |

---

## Open Questions

The following questions are decisions for `/define` and ADR-0009. Each has a
recommended default — none is a blocker requiring user input before that stage.

1. **`gh` CLI vs PyGithub (the ADR-0009 axis).** Recommendation: `gh` CLI subprocess as
   the default implementation, PyGithub as the seam's alternative. Rationale: zero new
   runtime deps, ambient auth (`gh auth login`/`GH_TOKEN`), and `gh issue list --search
"fingerprint in:body"` uses GitHub's indexed search (faster/more reliable than full
   body scan). The seam keeps the swap localized. Trade-off: subprocess calls require
   `gh` to be installed; offline tests must stub the seam (which they do regardless).
   ADR-0009 should record this choice explicitly.

2. **Idempotency granularity — dominant cluster only, or all clusters above a
   threshold?** Default recommendation: `--dominant-only` as the default (one issue per
   run unless `--all-clusters` is passed). This avoids generating 5 issues for a
   low-signal sweep and keeps the "grounded in the real finding" framing. The threshold
   approach (e.g. `rate > 0.05`) is a Could. `/define` should confirm the default.

3. **On re-run with an existing open issue: skip, comment, or update-in-place?**
   Recommendation: skip with a log message ("Issue already open: <url>") as the v1
   default; comment/update is a Could. This is the simplest safe behavior and avoids
   the complexity of body diffs. `/define` should make this explicit in the acceptance
   criteria.

4. **Deterministic template vs LLM-draft for v1?** Recommendation: deterministic
   template only for v1 (the Must path). The LLM-draft slot exists behind the seam but
   is not wired. This directly addresses the sprint's gadget risk: grounded stats, not
   AI-generated prose that could hallucinate findings. `/define` should confirm LLM-draft
   stays out of scope for v1.

5. **Dry-run draft output location and fingerprint `schema_version` inclusion.** Default
   recommendation: `results/issues/<failure_mode>-<category>.md` (one file per draft,
   atomic write). The fingerprint should include `schema_version` (e.g. `schema=1.0`)
   for forward compatibility — a v2 cluster shape would have a different fingerprint and
   produce a new issue rather than falsely deduping against a v1 issue.

6. **Auth/permissions boundary and offline test isolation.** The CLI assumes ambient
   `gh auth` / `GH_TOKEN` for live `--create` calls. Offline tests must never invoke a
   real subprocess or network call. The `GitHubClient` Protocol seam is the injection
   point: tests pass a `FakeGitHubClient` stub. This mirrors the cassette/replay ethos
   (ADR-0006) — no live network in the test suite, ever.

---

## Next Step

-> `/define sprint-5/phase-15-triage-to-issues`
