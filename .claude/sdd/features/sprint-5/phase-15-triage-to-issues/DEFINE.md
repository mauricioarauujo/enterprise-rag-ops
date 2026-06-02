# DEFINE: sprint-5/phase-15-triage-to-issues — Triage to GitHub Issues

**Sprint/Phase:** sprint-5/phase-15-triage-to-issues | **Date:** 2026-06-01
**Approach:** B (from BRAINSTORM) — new `eval/issues.py` pure core + thin `eval/issues_cli.py`
with a `GitHubClient` Protocol seam. ADR-0009 is a deliverable of this phase.

## Problem

Phase 14 (`rag-triage`) ships a deterministic `results/triage.json` — one `TriageCluster`
per `(failure_mode, category)` pair, a `dominant_cluster` pointer, and a representative
example per cluster (`SCHEMA_VERSION = "1.0"`, confirmed in `eval/triage.py`). That artifact
currently goes **nowhere**: the diagnosis loop is open. A maintainer who wants to act on the
dominant failure cluster (e.g. the Sprint-4 over-abstention finding) must hand-author a
GitHub Issue, manually transcribing cluster stats and a concrete example — repetitive, error
-prone, and not reproducible. Phase 15 closes the loop: consume `triage.json` and draft one
GitHub Issue per failure cluster, each **grounded in real cluster stats** (`count`, `rate`,
`models_seen`) plus a concrete `rag-inspect`-style example — never generic prose.

Creating a real GitHub Issue is a hard-to-reverse external action (sprint Risk:
outward-facing side effects), so **dry-run / draft is the default**, live creation is explicit
opt-in, and re-runs are **idempotent** via a deterministic body-marker fingerprint so they
never spam duplicates. The `gh`-CLI-vs-REST integration boundary, the body-marker dedup design,
and the dry-run/`--create` safety contract are recorded in **ADR-0009** — a deliverable here.

## Users / Stakeholders

- **Maintainer (Mauricio) at the CLI** — the primary actor. Runs `rag-issues` after a
  `rag-triage` pass to get reviewable Issue drafts in `results/issues/`, inspects them
  offline, then opts into `--create` to file them. Needs the draft to be trustworthy
  (grounded, deterministic) and the create path to be safe (dry-run default, idempotent).
- **Reviewers of the public repo / hiring signal** — read the filed Issues and the
  `results/issues/*.md` drafts as evidence that the harness _acts on its own findings_
  (the sprint's headline senior signal). Each Issue must read as a real, grounded bug report.
- **Phase 14 (`rag-triage`, shipped)** — the upstream producer. Phase 15 consumes its
  `triage.json` contract read-only and asserts `schema_version == "1.0"`.
- **ADR-0009 / future maintainers** — the `GitHubClient` seam localizes the `gh`-vs-PyGithub
  decision; ADR-0009 records it so a future swap is a documented, bounded change.
- **Future LLM-draft strategy (out of scope for v1)** — the `IssueDraft` seam leaves a slot
  for an LLM-prose `DraftStrategy` later, behind the deterministic Must path.

## Requirements

### Functional

- **FR-1** New pure module `src/enterprise_rag_ops/eval/issues.py` exposing a pure function
  `build_issue_draft(cluster, report, *, repo=None) -> IssueDraft` (and/or a
  `build_issue_drafts(report, clusters)` convenience). No I/O, no network, no subprocess,
  no LLM, no input mutation — fully offline-testable. Mirrors `eval/triage.py`.
- **FR-2** `IssueDraft` is a frozen `@dataclass(frozen=True, slots=True)` (mirroring
  `TriageCluster` / `InspectResult`) carrying at minimum: `title: str`, `body: str`,
  `fingerprint: str`, `labels: list[str]`, and the cluster key fields needed to name the
  draft file (`failure_mode: str`, `category: str`).
- **FR-3** `IssueDraft.title` is deterministic and grounded — derived from the cluster key
  (e.g. `"[rag-triage] {failure_mode} in {category} ({count} records, {rate:.1%})"`). No
  randomness, no LLM.
- **FR-4** `IssueDraft.body` is a **deterministic markdown template** grounded in the real
  cluster fields read from `triage.json`: `failure_mode`, `category`, `count`, `rate`,
  `models_seen`, `representative_question_id`, `representative_question_text`. It reuses the
  `rag-inspect`-style rendering ethos (question id + text + cluster framing) for the concrete
  example. No LLM in v1.
- **FR-5** `IssueDraft.body` embeds the body-marker fingerprint as a hidden HTML comment,
  exactly: `<!-- rag-triage-cluster: {failure_mode}|{category} schema={schema_version} -->`.
  The fingerprint **includes `schema_version`** so a future v2 cluster shape produces a
  distinct fingerprint rather than falsely deduping against a v1 issue (BRAINSTORM OQ-5).
- **FR-6** `IssueDraft.fingerprint` is computed purely from
  `(failure_mode, category, schema_version)` and is the single idempotency key — identical
  inputs always yield the identical fingerprint string (no timestamps, no host state).
- **FR-7** New thin CLI `src/enterprise_rag_ops/eval/issues_cli.py` (`rag-issues`) that:
  loads `triage.json` (default `--triage results/triage.json`), parses it, asserts
  `schema_version == "1.0"`, selects target clusters, builds `IssueDraft`s via `issues.py`,
  writes draft markdown atomically, and prints a summary. Mirrors `triage_cli.py` /
  `classify_cli.py` structure (argparse, `logging`, stderr error → exit 1).
- **FR-8** **Input-contract fail-fast.** If the loaded `triage.json` is missing
  `schema_version` or its value `!= "1.0"`, the CLI exits non-zero with a clear message
  naming the found value and the expected `"1.0"`. No drafts are written.
- **FR-9** **Cluster selection.** Default is **dominant-cluster-only**: draft for
  `report.dominant_cluster` only. `--all-clusters` widens to every cluster in
  `clusters[]` (BRAINSTORM OQ-2 default Confirmed).
- **FR-10** **Empty/degenerate triage.** When `dominant_cluster is null` (empty triage,
  `total_records == 0`), the CLI writes **no drafts**, prints a clear "no clusters to draft"
  message, and exits 0 (clean, not an error).
- **FR-11** **Dry-run / draft by default (no `--create`).** The CLI writes one draft file per
  selected cluster to `results/issues/<failure_mode>-<category>.md` using the house atomic
  write (`tempfile.NamedTemporaryFile` in the target dir → `os.replace`, temp cleanup on
  failure, mirroring `classify_cli.py`), and prints a summary table. **No network/subprocess
  call occurs without `--create`.**
- **FR-12** **`--create` explicit opt-in.** Only when `--create` is passed does the CLI call
  the `GitHubClient` seam. For each selected cluster it: (a) calls `search_issues` for the
  fingerprint; (b) if a matching **open** issue is found, **skips** with a log message
  (`"Issue already open: <url>"`) and does not create; (c) otherwise calls `create_issue` and
  logs the returned URL. Draft files are still written in `--create` mode.
- **FR-13** **`GitHubClient` Protocol seam** in `issues_cli.py` (or a small `eval/github.py`)
  with exactly two methods: `search_issues(query: str) -> list[dict]` and
  `create_issue(title: str, body: str, labels: list[str]) -> str` (returns the issue URL).
  The default concrete impl shells out to the `gh` CLI subprocess (e.g.
  `gh issue list --search "<fingerprint> in:body" --state open`, `gh issue create`). The seam
  is the injection point for tests (a `FakeGitHubClient`) and the ADR-0009 swap axis.
- **FR-14** **No live network/subprocess in tests.** The CLI accepts an injected
  `GitHubClient` (e.g. a `client` parameter on `main`/an internal entry, defaulting to the
  `gh` impl) so `tests/eval/test_issues.py` passes a `FakeGitHubClient` and never spawns a
  subprocess or touches the network (cassette/replay ethos, ADR-0006).
- **FR-15** Register `rag-issues = "enterprise_rag_ops.eval.issues_cli:main"` in
  `pyproject.toml` `[project.scripts]`, alongside the existing `rag-*` scripts.
- **FR-16** CLI flags follow the house pattern: `--triage` (default `results/triage.json`),
  `--output-dir` (default `results/issues/`), `--all-clusters` (default off → dominant only),
  `--create` (default off → dry-run), `--labels` (optional, passthrough to `create_issue`),
  and `--repo` (optional `owner/name` passthrough for the `gh` impl; default = ambient repo).
- **FR-17** **ADR-0009 deliverable.** `docs/adr/0009-triage-to-issues.md` exists, follows the
  house ADR format (Status / Date / Context / Decision / Consequences), records: the `gh`-CLI
  default vs PyGithub/REST alternative, the body-marker fingerprint idempotency design
  (including `schema_version` in the key), and the dry-run-default / `--create`-opt-in /
  skip-on-existing safety contract. It is linked from `docs/adr/README.md`'s index.

### Non-functional

- **NFR-1 Purity / offline core.** `issues.py` performs zero I/O, network, subprocess, or LLM
  calls. All side effects (file read of `triage.json`, file writes, `gh` subprocess) live in
  `issues_cli.py` / the `gh` `GitHubClient` impl. Mirrors `triage.py` / `triage_cli.py`.
- **NFR-2 Determinism.** Same `triage.json` → identical `IssueDraft` objects, identical draft
  markdown bytes, and identical fingerprints across runs and hosts. No timestamps, no dict/set
  iteration-order reliance, no randomness in title/body/fingerprint.
- **NFR-3 Safety-by-default (outward-facing side effects).** No GitHub mutation is possible
  without `--create`. Dry-run is the default; the create path is idempotent (FR-12); a failed
  draft write leaves no partial file (atomic write). This is the sprint's outward-facing-side
  -effect risk control.
- **NFR-4 House structure.** Pure-core + thin-CLI split, atomic write (temp + `os.replace` +
  cleanup), argparse + `logging` + stderr-error-exit-1 — all inherited from `classify_cli.py`
  / `triage_cli.py` / `inspect_cli.py`.
- **NFR-5 Test mirror.** New modules → `tests/eval/test_issues.py` (under the existing
  `tests/eval/` package with its `__init__.py`), offline, no network/subprocess/LLM. The
  `GitHubClient` seam is stubbed. `make lint test` is the gate.
- **NFR-6 No re-run / read-only over artifacts.** Phase 15 consumes already-published
  artifacts only (`triage.json`, optionally gold via `load_questions`). It never re-runs the
  eval sweep, `rag-classify`, or `rag-triage` (sprint no-re-runs guard).
- **NFR-7 Grounded, not a gadget.** Every draft is built from real `TriageCluster` numbers;
  there is no code path that emits an Issue not backed by a cluster in `triage.json` (sprint
  gadget-risk control).
- **NFR-8 Bounded dedup honesty.** GitHub has no server-side uniqueness; the body-marker +
  pre-create search is best-effort (bounded by search-index propagation). ADR-0009 records
  this as a known limitation; behavior degrades to "may create a duplicate if the index has
  not yet propagated," never to a crash.

## Acceptance Criteria

Each AC is checkable by a unit test in `tests/eval/test_issues.py` (or by the ADR/`pyproject`
existence checks for AC-13/AC-14).

- **AC-1 Pure draft from a cluster.** Given a `TriageCluster` + `TriageReport` header,
  `build_issue_draft` returns an `IssueDraft` whose `failure_mode`/`category` match the
  cluster and whose `title` and `body` contain the cluster's `count`, `rate`, and
  `failure_mode`. No I/O occurs (verified by no filesystem/network use in the test).
- **AC-2 Grounded body.** The `IssueDraft.body` contains the real
  `representative_question_id` and `representative_question_text` and the `models_seen`
  context (e.g. "Observed across: gpt-4o, claude-3-5-sonnet"), all sourced from the cluster.
- **AC-3 Fingerprint format + content.** `IssueDraft.body` contains exactly
  `<!-- rag-triage-cluster: {failure_mode}|{category} schema=1.0 -->`, and
  `IssueDraft.fingerprint` is the deterministic string built from
  `(failure_mode, category, schema_version)`.
- **AC-4 Fingerprint includes schema_version.** Two clusters with identical
  `(failure_mode, category)` but different `schema_version` produce **different**
  fingerprints (forward-compat: v2 won't falsely dedup against v1).
- **AC-5 Determinism.** Building a draft twice from the same cluster yields byte-identical
  `title`, `body`, and `fingerprint`.
- **AC-6 Schema gate (happy path).** `issues_cli.main(["--triage", <valid 1.0 file>])` exits 0
  and writes the expected draft file(s).
- **AC-7 Schema gate (fail-fast).** Given a `triage.json` with `schema_version` absent or
  `!= "1.0"`, `main` exits non-zero, the stderr message names the found value and `"1.0"`, and
  **no** draft files are written.
- **AC-8 Dominant-only default vs `--all-clusters`.** Default run drafts exactly one file (for
  `dominant_cluster`); with `--all-clusters` it drafts one file per cluster in `clusters[]`.
- **AC-9 Empty triage.** Given a `triage.json` with `dominant_cluster: null` and
  `total_records: 0`, `main` writes no drafts, prints a "no clusters" message, and exits 0.
- **AC-10 Atomic draft write.** Drafts land at `results/issues/<failure_mode>-<category>.md`;
  on a simulated write failure no partial/target file remains and the temp file is cleaned up
  (mirrors the `classify_cli` atomic-write test).
- **AC-11 Dry-run = no side effects beyond drafts.** Without `--create`, `main` runs to
  completion writing only the draft markdown file(s); the injected `GitHubClient` is **never**
  called (assert zero `search_issues`/`create_issue` invocations).
- **AC-12 `--create` idempotency.** With `--create` and a `FakeGitHubClient` whose
  `search_issues` returns a matching open issue, `create_issue` is **not** called and a
  "already open" message with the URL is logged/printed; when `search_issues` returns empty,
  `create_issue` **is** called once per selected cluster with the draft's title/body/labels,
  and the returned URL is reported.
- **AC-13 Offline guarantee.** The full `tests/eval/test_issues.py` suite passes with no
  network access and no real subprocess spawned — the `gh` impl is never instantiated in
  tests; only `FakeGitHubClient` is.
- **AC-14 Console script.** `rag-issues` resolves to `eval.issues_cli:main` and
  `rag-issues --help` exits 0.
- **AC-15 ADR-0009 exists and is linked.** `docs/adr/0009-triage-to-issues.md` exists with the
  house sections (Status / Date / Context / Decision / Consequences), records the `gh`-vs-REST
  decision + the body-marker idempotency design + the dry-run/`--create` safety contract, and
  appears in the `docs/adr/README.md` index table.

## Resolved Decisions

The 6 BRAINSTORM open questions — all resolved to their recommended defaults. None was a
blocker requiring user input (the outward-facing-side-effect items were already settled in
BRAINSTORM and the sprint Risks section), so none was escalated as a clarifying question.

1. **`gh` CLI vs PyGithub (the ADR-0009 axis).** `gh` CLI subprocess as the default
   `GitHubClient` impl; PyGithub/REST is the documented seam alternative. Rationale: zero new
   runtime deps, ambient auth (`gh auth` / `GH_TOKEN`), indexed `gh issue list --search
"fingerprint in:body"`. The seam keeps the swap localized; ADR-0009 records the choice.
   **Confirmed.**
2. **Idempotency granularity — dominant only or all clusters?** `--dominant-only` is the
   default (one issue per run); `--all-clusters` widens. Avoids spamming N issues on a
   low-signal sweep and keeps the "grounded in the real finding" framing. A `rate`-threshold
   selector stays a Could. **Confirmed.**
3. **On re-run with an existing open issue: skip, comment, or update?** **Skip** with a log
   message (`"Issue already open: <url>"`) for v1. Simplest safe behavior; comment/update is a
   Could (deferred). **Confirmed.**
4. **Deterministic template vs LLM-draft for v1?** **Deterministic template only** for v1 (the
   Must path). The LLM `DraftStrategy` slot exists behind the `IssueDraft` seam but is **not
   wired** — directly addresses the gadget risk (grounded stats, not hallucinated prose).
   **Confirmed.**
5. **Draft output location + fingerprint `schema_version` inclusion.**
   `results/issues/<failure_mode>-<category>.md`, one file per draft, atomic write. The
   fingerprint **includes** `schema_version` (`schema=1.0`) for forward compatibility (v2
   cluster shape → new issue, not a false dedup). **Confirmed.**
6. **Auth / offline-test isolation.** Live `--create` assumes ambient `gh auth` / `GH_TOKEN`.
   Offline tests never invoke a real subprocess or network call — the `GitHubClient` Protocol
   seam is the injection point (`FakeGitHubClient`), mirroring the cassette/replay ethos
   (ADR-0006). **Confirmed.**

**Scoped note (representative-example richness).** `triage.json` already carries
`representative_question_id` + `representative_question_text`, so the v1 deterministic body is
built **without re-streaming gold** — no `load_questions` re-join is required for the Must
path (avoids a network/HF stream). A richer `rag-inspect`-style example (gold facts, expected
doc ids, the failing answer) would require a gold re-join and/or the original JSONL; that
enrichment is **deferred** (Could) and is _not_ part of v1. If `/design` finds the grounded
example too thin without it, the gold re-join is an additive change at the CLI boundary only
(the pure core stays offline). Flagged here so `/design` can confirm v1 stays gold-free.

## Dependencies + Infrastructure Readiness

| Dependency                                                                                              | Type          | KB domain                                               | Specialist   | Status                                                                                                                         |
| ------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `eval/triage.py` (`TriageReport`, `TriageCluster`, `SCHEMA_VERSION="1.0"`, `_report_to_dict` key order) | module        | rag-eval (`eval-record-schema`)                         | kb-architect | Ready — Phase 14 shipped; exact field names + key order confirmed in source                                                    |
| `results/triage.json` (the input artifact)                                                              | artifact      | rag-eval                                                | —            | Ready — produced by `rag-triage`; consumed read-only with a `schema_version == "1.0"` gate                                     |
| `inspect_cli.py` (rendering ethos for the grounded example)                                             | module        | rag-eval                                                | —            | Ready — reuse the question-id/text framing; no live dependency                                                                 |
| `classify_cli.py` / `triage_cli.py` (house pattern source)                                              | module        | rag-eval                                                | —            | Ready — pure-core + thin-CLI + atomic-write + `--dry-run` patterns to mirror                                                   |
| `eval/questions.py` (`load_questions`, `Question`)                                                      | module        | rag-eval                                                | —            | Ready but **not needed for v1** — `representative_question_text` is already in `triage.json`; gold re-join deferred (Could)    |
| `pyproject.toml` `[project.scripts]`                                                                    | config        | —                                                       | —            | Ready — append `rag-issues` alongside existing `rag-*` scripts                                                                 |
| `gh` CLI (default `GitHubClient` impl, `--create` path only)                                            | external tool | —                                                       | —            | Runtime-only for live `--create`; tests stub the seam (never invoked offline). ADR-0009 records the choice                     |
| ADR-0009 (`docs/adr/0009-triage-to-issues.md`)                                                          | ADR           | —                                                       | —            | **Deliverable of this phase** — house format confirmed from ADR-0008 + `docs/adr/README.md`                                    |
| GitHub-integration / `triage-to-issues` KB concept                                                      | KB concept    | rag-eval (future `failure-triage` + `triage-to-issues`) | kb-architect | **Correctly deferred (not a Phase-15 gap)** — `/update-kb rag-eval` lands _after_ ADR-0009, per the Sprint-Wide Knowledge Plan |

**No new KB, agent, command, or `--deep-research` needed for this phase.** The GitHub-Issues
idempotency / `gh`-vs-REST research is complete (Exa, folded into BRAINSTORM) and its KB
landing is **deliberately post-ADR-0009** per the sprint plan — so the absence of a
GitHub-integration KB domain in `_index.yaml` is expected, not a readiness gap. The house
pure-core/thin-CLI/atomic-write patterns and the `triage.json` contract fully cover the build.

## Out of Scope (Won't — Phase 15)

- **LLM-drafted issue prose** (the `DraftStrategy` seam slot stays unwired) — gadget-risk
  control; deterministic template is the Must path.
- **Comment-on / update-in-place** of an existing open issue (v1 skips with a message).
- **Re-running the eval sweep, `rag-classify`, or `rag-triage`** — consume published artifacts
  only (no-re-runs guard).
- **Phase 16 Phoenix `--enrich-from-index`** — independent thread, not a dependency here.
- **Multi-repo issue creation**; **auto-close / auto-assign / auto-triage automation**
  (scope-creep-into-a-bot, per sprint Risks).
- **A generic issue bot** that drafts without grounding in real cluster data.
- **`rate`-threshold cluster selection** and **Levenshtein fuzzy title dedup** (Could,
  deferred — body-marker is the v1 primary key).
- **Gold re-join for a richer example** (`load_questions`) — deferred Could; v1 uses the
  `representative_question_text` already in `triage.json`.
- **`triage-to-issues` KB entry** — deferred to post-ADR-0009, per the Sprint-Wide Knowledge
  Plan.

## Clarity Score

| Dimension        | Score          | Note                                                                                                                              |
| ---------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Problem          | 3              | Root cause + evidence: `triage.json` exists (Phase 14 shipped) but goes nowhere; manual Issue authoring is the open loop.         |
| Users            | 3              | Named roles with workflow impact: maintainer at CLI (primary), public-repo reviewer, Phase 14 producer, ADR-0009/future swap.     |
| Success          | 3              | 15 falsifiable ACs, each unit-testable; offline guarantee, idempotency, atomic write, schema-gate, and ADR-existence all checked. |
| Scope            | 3              | MoSCoW inherited from BRAINSTORM with the explicit Won't list reproduced; dry-run/`--create`/skip already resolved.               |
| Constraints      | 3              | All named: pure/offline core, determinism, safety-by-default, house split + atomic write, test seam (no live network), no re-run. |
| **Total: 15/15** | **PASS (≥12)** |                                                                                                                                   |

## Next Step

→ `/design sprint-5/phase-15-triage-to-issues`
