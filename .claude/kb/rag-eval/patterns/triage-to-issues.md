# Triage to GitHub Issues: Body-Marker Idempotency + Dry-Run Safety

> **Purpose**: Translate a `TriageReport` cluster into a grounded, idempotent GitHub
> Issue draft — and file it safely. Covers the `GitHubClient` Protocol seam, body-marker
> fingerprint, dry-run default, schema gate, and offline testability.
> **ADR**: `docs/adr/0009-triage-to-issues.md`

## When to Use

- Turning the dominant failure cluster (or all clusters) from `results/triage.json`
  into actionable GitHub Issues.
- Any outward-facing action off a triage report that needs safe-by-default + replay.
- Adding a new GitHub backend (PyGithub/REST) — swap behind the existing seam.

## Architecture: Pure Core + Thin CLI + Protocol Seam

```
eval/issues.py       — pure core: IssueDraft, build_issue_draft, _cluster_identity
eval/github.py       — GitHubClient Protocol + GhCliClient (only subprocess-touching file)
eval/issues_cli.py   — thin CLI: schema gate, inverse parsers, cluster selection,
                        atomic draft write, --create opt-in
```

`build_issue_draft` is side-effect-free. `GhCliClient` is the only subprocess
caller. Tests inject a `FakeGitHubClient`; `GhCliClient` is never instantiated in
the suite (cassette/replay ethos — see `[[cassette-replay-eval]]`).

## The GitHubClient Protocol Seam

```python
class GitHubClient(Protocol):
    def search_issues(self, query: str) -> list[dict]: ...
    def create_issue(self, title: str, body: str, labels: list[str]) -> str: ...
```

`GhCliClient` implements this with `subprocess.run([...])` **arg lists** — never
shell strings, so markdown body and fingerprint are passed verbatim with no
quoting/injection hazard. The Protocol is the ADR-0009 swap axis: moving to
PyGithub/REST is a single-file change behind this seam.

## Body-Marker Fingerprint Idempotency

A single `_cluster_identity` helper feeds **both** the hidden HTML marker and the
search fingerprint, so they cannot drift:

```python
def _cluster_identity(failure_mode, category, schema_version) -> str:
    # raises ValueError if '|' in either field (| is GitHub search's OR operator)
    return f"{failure_mode}|{category} schema={schema_version}"

# body marker (embedded in the issue body):
marker = f"<!-- rag-triage-cluster: {identity} -->"

# search fingerprint (substring of the marker, so in:body finds it):
fingerprint = f"rag-triage-cluster: {identity}"
```

The `schema_version` is part of the key on purpose: a future `"2.0"` triage report
produces a distinct fingerprint and re-files, rather than falsely deduping against
a v1 Issue.

## Dry-Run Default / `--create` Opt-In / Skip-on-Existing

```
rag-issues --triage results/triage.json          # dry-run: writes drafts, no network
rag-issues --triage results/triage.json --create # files idempotently via gh CLI
rag-issues ... --all-clusters                    # draft all clusters (default: dominant only)
```

The CLI always writes atomic markdown drafts (`results/issues/<failure_mode>-<category>.md`,
temp file + `os.replace`). `--create` adds the search-then-create step:

```python
def main(argv=None, *, client: GitHubClient | None = None) -> int:
    ...
    gh = client or GhCliClient(repo=args.repo)
    for draft in drafts:
        existing = gh.search_issues(draft.fingerprint)
        if existing:
            url = existing[0].get("url", "<unknown>")
            print(f"  skip (already open): {url}  —  {draft.title}")
            continue
        url = gh.create_issue(draft.title, draft.body, draft.labels)
        print(f"  created: {url}  —  {draft.title}")
```

The `client=None` parameter is the injection point for tests — pass a
`FakeGitHubClient` there; the real `GhCliClient` is only constructed inside `main`
when `--create` is active.

## Schema Gate (Input Contract)

```python
found = data.get("schema_version")
if found != SCHEMA_VERSION:   # SCHEMA_VERSION = "1.0"
    print(f"Error: unsupported triage schema_version {found!r}; expected {SCHEMA_VERSION!r}.",
          file=sys.stderr)
    return 1
```

The CLI hard-rejects any `triage.json` whose `schema_version` does not exactly
equal `"1.0"`. Inverse parsers (`_cluster_from_dict` / `_report_from_dict`) restore
the frozen dataclasses from the JSON dict.

## Grounded Body: No Generated Prose

`build_issue_draft` assembles the issue body from real `TriageCluster` fields only —
`count`, `rate`, `models_seen`, `representative_question_id`, `representative_question_text`.
There is no LLM call and no invented text. Every issue includes:

```
## Failure cluster: `{fm}` in `{cat}`

### Cluster stats   (table of count / rate / models)
### Representative example  (question text + rag-inspect one-liner)
### Provenance  (triage.json path + schema version)
<!-- rag-triage-cluster: {identity} -->   ← hidden dedup anchor
```

## Best-Effort Dedup (Known Limitation)

The `search_issues` + `create_issue` pattern is **best-effort**. GitHub has no
server-side Issue uniqueness. If the search index has not yet propagated a freshly
created Issue, a concurrent re-run may create a duplicate. This degrades to "may
create a duplicate," never to a crash. Concurrent creators are out of scope.

## Offline Testing

```python
class FakeGitHubClient:
    def __init__(self, existing: list[str] | None = None):
        self.created: list[dict] = []
        self._existing = existing or []

    def search_issues(self, query: str) -> list[dict]:
        return [{"url": u, "title": ""} for u in self._existing if query in u]

    def create_issue(self, title: str, body: str, labels: list[str]) -> str:
        url = f"https://github.com/fake/repo/issues/{len(self.created) + 1}"
        self.created.append({"title": title, "body": body, "labels": labels})
        return url
```

Pass `FakeGitHubClient` to `main(argv=[..., "--create"], client=fake)`.
`GhCliClient` is never imported or instantiated in the test suite.

## Configuration

| Flag / Arg       | Default               | Effect                                     |
| ---------------- | --------------------- | ------------------------------------------ |
| `--triage`       | `results/triage.json` | Source triage report                       |
| `--output-dir`   | `results/issues`      | Destination for draft markdown files       |
| `--all-clusters` | off (dominant only)   | Draft one issue per cluster                |
| `--create`       | off (dry-run)         | File issues via GitHub; requires `gh auth` |
| `--labels`       | `rag-triage`          | Comma-separated issue labels               |
| `--repo`         | ambient `gh` repo     | Override target repo (`owner/name`)        |

## Related

- [failure-triage.md](../concepts/failure-triage.md) — `TriageReport` / `TriageCluster` shape
- [eval-record-schema.md](../concepts/eval-record-schema.md) — upstream JSONL format
- [cassette-replay-eval.md](cassette-replay-eval.md) — offline test ethos
- `eval/issues.py`, `eval/github.py`, `eval/issues_cli.py`
- `docs/adr/0009-triage-to-issues.md`
