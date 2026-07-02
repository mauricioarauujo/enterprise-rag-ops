# DESIGN: sprint-5/phase-15-triage-to-issues — Triage to GitHub Issues

**Sprint/Phase:** sprint-5/phase-15-triage-to-issues | **Date:** 2026-06-02
**Branch:** `sprint-5/phase-15-triage-to-issues`
**Approach:** B (BRAINSTORM) — pure `eval/issues.py` core + thin `eval/issues_cli.py` +
`GitHubClient` Protocol seam. ADR-0009 is a deliverable of this phase.

## Architecture

Phase 15 closes the triage loop: it consumes the read-only `results/triage.json` artifact
produced by `rag-triage` (Phase 14) and emits grounded GitHub Issue drafts.

### Data flow

```
results/triage.json
   │  (CLI side, issues_cli.py)
   ▼
json.load → dict ──── schema gate: assert data["schema_version"] == "1.0"  (FR-8/AC-7)
   │                       │ fail → stderr "...found <v>, expected '1.0'" → return 1, no writes
   ▼
_cluster_from_dict(d) for each cluster dict  ──►  TriageCluster (re-imported from eval.triage)
_report_from_dict(data)                       ──►  TriageReport  (header + clusters + dominant)
   │
   ▼
select clusters:  dominant-only (default) | --all-clusters  (FR-9/AC-8)
   │  (dominant is None & total_records==0 → no drafts, "no clusters" msg, return 0)  (FR-10/AC-9)
   ▼
   │  (PURE core, issues.py — no I/O, no network)
build_issue_draft(cluster, report, *, repo=None, labels=None) ──► IssueDraft  (FR-1/FR-2)
   │
   ├─► atomic write: results/issues/<failure_mode>-<category>.md          (FR-11/AC-10)
   │       tempfile.NamedTemporaryFile(dir=output_dir) → os.replace → cleanup-on-fail
   │       (mirrors classify_cli.py lines 110–136)
   └─► stdout summary table
   │
   ▼  (only if --create — FR-12/AC-12; draft files are ALSO written in this mode)
for each selected IssueDraft:
    client.search_issues(draft.fingerprint)        ── GitHubClient seam (injected; FR-13/FR-14)
        ├─ matching OPEN issue found → log "Issue already open: <url>", SKIP (no create)
        └─ none found → url = client.create_issue(title, body, labels); log url
```

The **pure core** (`issues.py`) never touches the filesystem, network, subprocess, or an
LLM. Every side effect (reading `triage.json`, writing drafts, the `gh` subprocess) lives in
`issues_cli.py` / the `gh` `GitHubClient` impl. This mirrors the `triage.py` / `triage_cli.py`
split exactly (NFR-1).

### Schema-gate / parse detail (confirmed against `eval/triage.py`)

`triage.py` exposes **no public `from-dict` / load helper** — only the private
`_cluster_to_dict` / `_report_to_dict` _serializers_ (lines 125–150) used by Phase 14 to
write `triage.json`. Therefore `issues_cli.py` MUST parse the JSON dict directly into the
fields the pure core needs. The cleanest design re-imports the **frozen dataclasses**
`TriageCluster` / `TriageReport` and `SCHEMA_VERSION` from `enterprise_rag_ops.eval.triage`
and reconstructs them with two private inverse helpers in `issues_cli.py`:

```python
from enterprise_rag_ops.eval.triage import SCHEMA_VERSION, TriageCluster, TriageReport

def _cluster_from_dict(d: dict) -> TriageCluster:
    return TriageCluster(
        failure_mode=d["failure_mode"],
        category=d["category"],
        count=d["count"],
        rate=d["rate"],
        representative_question_id=d["representative_question_id"],
        representative_question_text=d["representative_question_text"],
        models_seen=d["models_seen"],
    )

def _report_from_dict(data: dict) -> TriageReport:
    dom = data["dominant_cluster"]
    return TriageReport(
        schema_version=data["schema_version"],
        total_records=data["total_records"],
        models_seen=data["models_seen"],
        dominant_cluster=_cluster_from_dict(dom) if dom is not None else None,
        clusters=[_cluster_from_dict(c) for c in data["clusters"]],
    )
```

Field names + key order are taken verbatim from `_cluster_to_dict` / `_report_to_dict` —
the parse is the exact inverse of the Phase-14 serializer, so the contract cannot drift.
The schema gate runs **before** any reconstruction: `data = json.load(f)`, then
`if data.get("schema_version") != "1.0": raise ValueError(...)` naming the found value and
the expected `"1.0"` (FR-8). Re-using `SCHEMA_VERSION` as the gate constant keeps it SSoT'd.

### `IssueDraft` (pure core — FR-2)

```python
@dataclass(frozen=True, slots=True)
class IssueDraft:
    title: str            # FR-3, deterministic, grounded
    body: str             # FR-4, deterministic markdown + embedded fingerprint comment (FR-5)
    fingerprint: str      # FR-6, single idempotency key
    labels: list[str]     # passthrough to create_issue (default e.g. ["rag-triage"])
    failure_mode: str     # cluster key — names the draft file
    category: str         # cluster key — names the draft file
```

Mirrors the frozen-dataclass ethos of `TriageCluster` and `InspectResult`
(`@dataclass(frozen=True, slots=True)`).

### Title / fingerprint / body templates (deterministic — NFR-2)

- **Title (FR-3):** `f"[rag-triage] {failure_mode} in {category} ({count} records, {rate:.1%})"`.
  No randomness, no LLM — derived purely from cluster key + stats.
- **Fingerprint string (FR-6):** built purely from `(failure_mode, category, schema_version)`.
  Recommended exact value: `f"rag-triage-cluster:{failure_mode}|{category}|schema={schema_version}"`
  — a stable, greppable token usable as the `gh issue list --search "<fingerprint> in:body"`
  query. Includes `schema_version` so a v2 cluster shape yields a _distinct_ fingerprint
  (AC-4) and never falsely dedups against a v1 issue.
- **Body marker (FR-5):** the body embeds the hidden HTML comment **exactly**:
  `<!-- rag-triage-cluster: {failure_mode}|{category} schema={schema_version} -->`
  (note: with `schema=1.0`, AC-3 asserts `schema=1.0` literally). The body-marker comment and
  the `fingerprint` field share the same `(failure_mode, category, schema_version)` identity but
  are distinct strings — the comment is the human-invisible dedup anchor in the rendered issue;
  the `fingerprint` field is the search query. The `search_issues` query string passed by the
  CLI must match what `gh --search ... in:body` can find inside the comment (the CLI passes
  `draft.fingerprint`; the `gh` impl searches the body, which contains the marker). **Build
  the marker and the fingerprint from one shared helper** so they cannot drift (a single
  `_cluster_identity(failure_mode, category, schema_version)` formatting the `|`/`schema=` core).
- **Body (FR-4):** deterministic markdown grounded in the real cluster fields
  (`failure_mode`, `category`, `count`, `rate`, `models_seen`, `representative_question_id`,
  `representative_question_text`), reusing the `rag-inspect` rendering ethos (question id +
  text + cluster framing) for the concrete example. Renders `models_seen` as
  `"Observed across: <comma-joined>"` (AC-2). Ends with the hidden fingerprint comment. No LLM.

### `GitHubClient` Protocol seam (FR-13) — location decision

**Decision: put the `GitHubClient` Protocol, the `gh`-CLI default impl (`GhCliClient`), and
keep `FakeGitHubClient` in the test file.** Recommended **location: a small new
`src/enterprise_rag_ops/eval/github.py`** rather than inline in `issues_cli.py`.

Justification (FR-13 explicitly allows either):

- **Testability / import hygiene.** `issues.py` stays pure and `github.py` isolates the only
  subprocess-touching code. `test_issues.py` imports the `GitHubClient` Protocol type and
  defines its own `FakeGitHubClient`, and _never_ imports/instantiates `GhCliClient`
  (AC-13 offline guarantee). A separate module makes "the `gh` impl is never instantiated in
  tests" a one-line, auditable fact.
- **Seam clarity for ADR-0009.** The `gh`-vs-PyGithub swap axis is a single file — exactly the
  "localized, named future change" the ADR records.
- **Cost:** one extra file (~40 lines). Net positive vs. inlining subprocess code in the CLI.

```python
# eval/github.py
from typing import Protocol

class GitHubClient(Protocol):
    def search_issues(self, query: str) -> list[dict]: ...
    def create_issue(self, title: str, body: str, labels: list[str]) -> str: ...

class GhCliClient:  # default production impl — NEVER imported by tests
    def __init__(self, repo: str | None = None) -> None: ...
    def search_issues(self, query: str) -> list[dict]:
        # subprocess.run(["gh", "issue", "list", "--search", f"{query} in:body",
        #                 "--state", "open", "--json", "url,title", ...], ...) — arg LIST, never shell
        ...
    def create_issue(self, title: str, body: str, labels: list[str]) -> str:
        # subprocess.run(["gh", "issue", "create", "--title", title, "--body", body,
        #                 *("--label", l for l in labels), ...]) → return stdout URL
        ...
```

`FakeGitHubClient` (in `tests/eval/test_issues.py`) records calls and returns a programmable
`search_issues` result — the AC-11/AC-12/AC-13 injection point.

### `main` injection mechanism (FR-14 — crux of offline testability)

```python
def main(argv: list[str] | None = None, *, client: GitHubClient | None = None) -> int:
```

In production `--create`, when `client is None`, `main` lazily constructs
`GhCliClient(repo=args.repo)` **only inside the `--create` branch** (so no `gh` impl is even
referenced in dry-run). Tests always pass `client=FakeGitHubClient(...)`, so no subprocess or
network is ever spawned (AC-13). The keyword-only `client` param keeps the production CLI
signature (`rag-issues ...`) unchanged while making the seam injectable.

## File Manifest

| File                                        | Change             | Owner (agent / direct) | Phase order           |
| ------------------------------------------- | ------------------ | ---------------------- | --------------------- |
| `src/enterprise_rag_ops/eval/issues.py`     | new                | direct                 | 1 — core logic        |
| `src/enterprise_rag_ops/eval/github.py`     | new                | direct                 | 1 — core logic (seam) |
| `pyproject.toml`                            | edit               | direct                 | 2 — config            |
| `src/enterprise_rag_ops/eval/issues_cli.py` | new                | direct                 | 3 — CLI wiring        |
| `tests/eval/test_issues.py`                 | new                | direct                 | 4 — tests             |
| `tests/eval/__init__.py`                    | no-change (exists) | direct                 | 4 — tests             |
| `docs/adr/0009-triage-to-issues.md`         | new                | direct                 | 5 — ADR/docs          |
| `docs/adr/README.md`                        | edit               | direct                 | 5 — ADR/docs          |

Notes:

- There is **no triage/issues specialist agent**; everything is `direct`. `kb-architect` owns
  the (deferred, post-ADR) KB landing only — no KB file is touched this phase.
- `tests/eval/__init__.py` is **confirmed present** (verified via glob) — no change.
- `github.py` is grouped in Phase order 1 because the `GitHubClient` Protocol type is imported
  by both `issues_cli.py` (for the `client` param type) and the test double; it carries no
  cluster logic but is core-layer infrastructure.

## Implementation Phases

Ordered per the convention (no data-schema/dataset step — `triage.json` is consumed read-only;
the schema is owned upstream by Phase 14).

### Phase 1 — Core module logic (`src/`)

**`eval/issues.py`** (pure, offline — NFR-1):

- `IssueDraft` frozen dataclass (fields above) — **FR-2** → AC-1.
- `_cluster_identity(failure_mode, category, schema_version) -> str` — shared core for the
  marker + fingerprint (prevents drift) — **FR-5/FR-6** → AC-3, AC-4.
- `build_issue_draft(cluster: TriageCluster, report: TriageReport, *, repo: str | None = None,
labels: list[str] | None = None) -> IssueDraft` — pure builder; computes title (FR-3), body
  (FR-4, embeds the FR-5 marker), fingerprint (FR-6); no input mutation — **FR-1** →
  AC-1, AC-2, AC-5.
- Optional convenience `build_issue_drafts(report, clusters) -> list[IssueDraft]` (FR-1).

**`eval/github.py`** (the seam):

- `GitHubClient` Protocol (`search_issues`, `create_issue`) — **FR-13**.
- `GhCliClient` default impl shelling to `gh` via `subprocess.run([...])` **arg list, never a
  shell string** — **FR-13** (covered by AC-13's "gh impl never instantiated in tests": this
  file is import-clean but never exercised by the suite).

### Phase 2 — Config (`pyproject.toml`)

Append to `[project.scripts]` (exact insertion point: after line 35
`rag-triage = "enterprise_rag_ops.eval.triage_cli:main"`):

```toml
rag-issues = "enterprise_rag_ops.eval.issues_cli:main"
```

**FR-15** → AC-14.

### Phase 3 — CLI wiring (`src/enterprise_rag_ops/eval/issues_cli.py`)

Thin CLI mirroring `triage_cli.py` / `classify_cli.py` (argparse, `logging`, stderr-error →
`return 1`, `main(argv=None)->int`, `if __name__=="__main__": sys.exit(main())`):

- `_build_parser()` flags (**FR-16**): `--triage` (default `results/triage.json`),
  `--output-dir` (default `results/issues/`), `--all-clusters` (`store_true`, default off →
  dominant only), `--create` (`store_true`, default off → dry-run), `--labels` (optional,
  passthrough), `--repo` (optional `owner/name` passthrough to `GhCliClient`).
- `_cluster_from_dict` / `_report_from_dict` inverse parsers (see Architecture) — **FR-7**.
- `main(argv=None, *, client: GitHubClient | None = None) -> int`:
  1. `json.load` the `--triage` file; schema gate `!= "1.0"` → stderr message names found vs
     `"1.0"`, `return 1`, no drafts — **FR-7/FR-8** → AC-7.
  2. `_report_from_dict`; select clusters: dominant-only default / `--all-clusters` — **FR-9**
     → AC-8.
  3. Empty/degenerate (`dominant_cluster is None`, `total_records == 0`): print "no clusters to
     draft", `return 0`, no writes — **FR-10** → AC-9.
  4. For each selected cluster: `build_issue_draft(...)`; atomic write to
     `results/issues/<failure_mode>-<category>.md` (tempfile in `output_dir` →
     `os.replace`, cleanup-on-failure — the `classify_cli.py` lines 110–136 idiom) — **FR-11**
     → AC-6, AC-10. Print summary table.
  5. If `--create` (**FR-12** → AC-11, AC-12): `client = client or GhCliClient(repo=args.repo)`;
     per draft → `search_issues(draft.fingerprint)`; matching open issue → log
     `"Issue already open: <url>"`, skip; else `create_issue(title, body, labels)`, log URL.
     In dry-run (no `--create`) the client is **never** referenced (AC-11).

### Phase 4 — Tests (`tests/eval/test_issues.py`)

Offline (`unittest.mock.patch` + `tmp_path` + `capsys`), no network/subprocess/LLM — mirrors
`test_triage.py` / `test_inspect_cli.py`. Helpers: a `make_cluster(...)` /
`make_triage_json(tmp_path, ...)` fixture builder and a `FakeGitHubClient` recording calls.

| AC | Test | Mechanism |
| ----- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| AC-1 | `test_pure_draft_from_cluster` | `build_issue_draft` returns `IssueDraft`; title+body contain `count`/`rate`/`failure_mode`; no fs/net |
| AC-2 | `test_grounded_body` | body contains rep qid + text + "Observed across: …" |
| AC-3 | `test_fingerprint_format` | body has exact `<!-- rag-triage-cluster: fm                                                                                                                                       | cat schema=1.0 -->`; `fingerprint`from`(fm, cat, schema)` |
| AC-4 | `test_fingerprint_includes_schema` | same `(fm,cat)`, different `schema_version` → different fingerprints |
| AC-5 | `test_determinism` | two builds → byte-identical title/body/fingerprint |
| AC-6 | `test_schema_gate_happy_path` | `main(["--triage", valid_1.0])` → exit 0, draft file(s) written |
| AC-7 | `test_schema_gate_fail_fast` | missing / `!= "1.0"` → exit ≠ 0, stderr names found + `"1.0"`, no drafts |
| AC-8 | `test_dominant_only_vs_all_clusters` | default → 1 file; `--all-clusters` → 1 per cluster |
| AC-9 | `test_empty_triage` | `dominant_cluster: null`, `total_records: 0` → no drafts, "no clusters" msg, exit 0 |
| AC-10 | `test_atomic_write_cleanup` | simulate write failure → no partial/target file, temp cleaned (mirrors `test_triage` AC-12) |
| AC-11 | `test_dry_run_no_side_effects` | no `--create` → `FakeGitHubClient` never called (0 search/create) |
| AC-12 | `test_create_idempotency` | `--create` + Fake returning open issue → no `create_issue`, "already open" logged; Fake returning empty → `create_issue` called once/cluster with title/body/labels, URL reported |
| AC-13 | `test_offline_guarantee` | suite runs with no network/subprocess; only `FakeGitHubClient` instantiated (assert `GhCliClient` not built) — optional subprocess import-check mirroring `test_triage` AC-15 |
| AC-14 | `test_console_script_and_help` | `main(["--help"])` → `SystemExit(0)`; assert `rag-issues = "enterprise_rag_ops.eval.issues_cli:main"` literal in `pyproject.toml` |
| AC-15 | `test_adr_exists_and_linked` | `docs/adr/0009-triage-to-issues.md` exists with house sections; appears in `docs/adr/README.md` index |

(AC-14/AC-15 are existence checks read off `pyproject.toml` / the ADR + README, matching the
`test_triage.py` AC-16 pattern.)

### Phase 5 — ADR + docs

**`docs/adr/0009-triage-to-issues.md`** (**FR-17** → AC-15), house format (Status / Date /
Context / Decision / Consequences), **Status: accepted**, Date: 2026-06-02. Records: (a) `gh`
CLI default vs PyGithub/REST alternative + the `GitHubClient` seam; (b) the body-marker
fingerprint idempotency design **including `schema_version`** in the key; (c) the
dry-run-default / `--create`-opt-in / skip-on-existing safety contract; (d) the NFR-8 bounded
dedup honesty (search-index propagation, best-effort, degrades to "may create a duplicate,"
never crash).

**`docs/adr/README.md`** index edit (**AC-15**): the index table currently lists only
0001–0007 — **ADR-0008 is missing from it** (the file `0008-failure-taxonomy.md` exists and is
`accepted`, dated 2026-05-30). **Decision: add BOTH rows** — fix the pre-existing 0008 gap and
add the new 0009 row — since the manifest already edits this file and leaving 0008 unlisted
would be a known-broken index. Rows to add:

```
| 0008 | [Rule-Based Failure-Mode Taxonomy and Classifier](0008-failure-taxonomy.md) | accepted | 2026-05-30 |
| 0009 | [Triage to GitHub Issues — gh-CLI Client, Body-Marker Idempotency, Dry-Run Default](0009-triage-to-issues.md) | accepted | 2026-06-02 |
```

(The 0008 backfill is a one-line surgical fix of an existing index bug, scoped to the file the
manifest already touches — not unrelated-legacy cleanup.)

## Infrastructure Gaps

Three-layer check against `.claude/kb/_index.yaml` and `.claude/agents/`:

| Gap Type           | Area                                              | Detail                                                                      | Recommendation                                                                                                                                               |
| ------------------ | ------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Missing domain     | GitHub integration (`gh`-CLI / issue idempotency) | No KB domain covers GitHub-Issues idempotency or the `gh`-vs-REST boundary. | **Deferred, not a gap** — per the Sprint-Wide Knowledge Plan the landing is `/update-kb rag-eval` _after_ ADR-0009. Confirmed expected, not a readiness gap. |
| Missing concept    | rag-eval                                          | No `triage-to-issues` concept/pattern in `rag-eval` `concepts`/`patterns`.  | **Deferred** — `/update-kb rag-eval` post-ADR-0009 (kb-architect). Not blocking this phase.                                                                  |
| Missing specialist | triage/issues                                     | No triage/issues specialist agent exists.                                   | **None needed** — house pure-core/thin-CLI/atomic-write patterns + the `triage.json` contract fully cover the build; everything is `direct`.                 |

**Confirmed (not merely restated):** `_index.yaml` has exactly four domains — `rag-eval`,
`observability`, `rag-generation`, `rag-retrieval` — none mentions GitHub integration. The
`.claude/agents/` set is workflow + KB only (`brainstorm/define/design-agent`, `code-reviewer`,
`kb-architect`, `_specialist-template`); there is no eval/issues specialist. Both absences are
the _expected_ state per DEFINE's Dependencies table and the sprint plan — the GitHub-Issues
research (Exa) is complete and folded into BRAINSTORM, and its KB landing is deliberately
post-ADR-0009. **No `/new-kb`, `/new-agent`, `/new-command`, or `--deep-research` is required
for this phase.**

## Consistency Check

**Verdict: ✅ CONSISTENT.** Multi-file phase (2 src modules + seam + tests + ADR + 2 doc edits,
15 ACs, outward-facing side-effect surface) → full 6-pass review run.

| ID | Severity | Pass | Location | Finding | Suggested fix |
| --- | -------- | -------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | --- | ----------------------------------------------------------------------------------------- |
| C-1 | LOW | 1 Duplication | FR-5 vs FR-6 / DESIGN | Marker comment and `fingerprint` field both encode `(fm, cat, schema_version)` — risk of two slightly-different strings drifting. | Resolved in design: a single `_cluster_identity` helper feeds both. No spec change. |
| C-2 | LOW | 2 Ambiguity | FR-6 / AC-3 | DEFINE fixes the _marker comment_ exactly but says `fingerprint` is "the deterministic string built from (fm, cat, schema_version)" without pinning its literal format. | Design pins a concrete `fingerprint` literal (`rag-triage-cluster:fm                                                                            | cat | schema=…`); any deterministic form passes AC-3/AC-5. Flag for implementer to keep stable. |
| C-3 | LOW | 3 Underspecification | FR-16 `--labels` | DEFINE says `--labels` "optional, passthrough" without arity (single vs comma-list vs `nargs`). | Implementer choice; recommend `--labels` repeatable or comma-split → `list[str]`, default `["rag-triage"]`. Non-blocking. |
| C-4 | — | 4 Constitution | `GitHubClient` seam | Seam justified by a **named, likely** change (the ADR-0009 `gh`-vs-PyGithub/REST swap), not "in case". | **Passes** AGENTS.md Engineering Behavior. Not a violation. |
| C-5 | — | 4 Constitution | `issues.py` purity / gold-free v1 | Pure core pulls **no** `load_questions`; uses `representative_question_text` already in `triage.json`. No re-run of sweep/classify/triage. | **Passes** NFR-1/NFR-6 and the gold-free scoped note. Confirmed: design keeps core offline. |
| C-6 | — | 4 Constitution | cassette/replay ethos (ADR-0006) | No mocked LLM API; the `GitHubClient` seam is the injected test double, never a real subprocess. | **Passes** the "no live network in tests" ethos. |
| C-7 | — | 5 Coverage | FR-1..17 / NFR-1..8 | Every FR/NFR maps to ≥1 manifest entry + AC + phase (FR-1/2/3/4/5/6→issues.py; FR-7/8/9/10/11/12/16→issues_cli.py; FR-13/14→github.py+main; FR-15→pyproject; FR-17→ADR/README). | No gap either direction. |
| C-8 | LOW | 6 Inconsistency | DEFINE FR-1 vs BRAINSTORM | BRAINSTORM `build_issue_draft(cluster, report, inspect_result)` includes an `inspect_result` arg; DEFINE/v1 drop it (gold-free — no `InspectResult` join). | Design follows DEFINE (no `inspect_result` param) — DEFINE supersedes BRAINSTORM. Terminology aligned. |
| C-9 | LOW | 6 Inconsistency | DEFINE NFR-6 wording | NFR-6 mentions "optionally gold via `load_questions`" while the scoped note + FR-1 forbid it in v1. | Design resolves to **no** `load_questions` in v1 (the binding scoped note). The NFR-6 "optionally" is the deferred-Could caveat, not a v1 path. |

**Stranger-test (pass 4):** every file the manifest creates (`issues.py`, `github.py`,
`issues_cli.py`, `test_issues.py`, ADR-0009, README rows) is about the _system_; no
personal/career content. No leak.

No CRITICAL or HIGH findings; all LOW items are resolved in-design or are implementer-latitude.

## Risks & Trade-offs

- **`gh` subprocess quoting/escaping (the `--create` path).** Fingerprints and the full
  markdown body are passed to `gh issue create` / `gh issue list --search`. **Always invoke via
  `subprocess.run([...])` with an argument list — never a shell string / `shell=True`.** The
  body contains markdown, `|`, and the HTML comment; a shell string would be an injection/escape
  hazard. The arg-list form passes bytes verbatim. (Design mandates this in `github.py`.)
- **Bounded dedup honesty (NFR-8).** GitHub has no server-side issue uniqueness; the
  body-marker + pre-create `search_issues` is best-effort, bounded by search-index propagation
  delay. Behavior degrades to "may create a duplicate if the index has not propagated," never to
  a crash. ADR-0009 records this as a known limitation.
- **Schema-version coupling.** The fingerprint embeds `schema_version`, so a Phase-N triage
  schema bump (`"2.0"`) deliberately re-files issues rather than deduping — correct forward-compat
  (AC-4) but worth noting in ADR-0009 so a future maintainer expects the re-file.
- **ADR posture.** ADR-0009 **is** the architectural decision record for this phase and is
  authored as **accepted** (the `gh`-vs-REST, idempotency, and safety-contract decisions are made
  here — unlike Phase 14, which needed no ADR). The `GitHubClient` seam is the localized swap
  axis the ADR points at.
- **Pre-existing index bug surfaced.** ADR-0008 is missing from `docs/adr/README.md`; this design
  backfills it alongside the 0009 row (a one-line fix in a file the manifest already edits).

## Next Step

→ `/implement sprint-5/phase-15-triage-to-issues` — address gaps first (none blocking; KB
landing is deliberately deferred post-ADR-0009). The implement stage normally runs in
Antigravity / Gemini against this `DESIGN.md` as the cross-tool contract (AGENTS.md § Implement
Contract).
