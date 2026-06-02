"""Pure core for drafting GitHub Issues from triage clusters.

Converts a ``TriageCluster`` (plus its ``TriageReport`` header) into a deterministic,
offline ``IssueDraft`` — title, grounded markdown body, and an idempotency fingerprint.
No I/O, network, subprocess, or LLM: every side effect lives in ``issues_cli.py`` and the
``GitHubClient`` seam (``eval/github.py``). Mirrors the ``triage.py`` pure-core ethos.
"""

from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag_ops.eval.triage import TriageCluster, TriageReport


@dataclass(frozen=True, slots=True)
class IssueDraft:
    """A deterministic, grounded GitHub Issue draft for one failure cluster."""

    title: str
    body: str
    fingerprint: str
    labels: list[str]
    failure_mode: str
    category: str


def _cluster_identity(failure_mode: str, category: str, schema_version: str) -> str:
    """Shared identity core feeding BOTH the body marker and the fingerprint.

    Returns the stable ``{failure_mode}|{category} schema={schema_version}`` token so the
    hidden HTML-comment marker and the search fingerprint can never drift apart.
    """
    return f"{failure_mode}|{category} schema={schema_version}"


def _build_marker(failure_mode: str, category: str, schema_version: str) -> str:
    """The hidden HTML comment embedded in the issue body (the dedup anchor)."""
    return (
        f"<!-- rag-triage-cluster: {_cluster_identity(failure_mode, category, schema_version)} -->"
    )


def _build_fingerprint(failure_mode: str, category: str, schema_version: str) -> str:
    """The deterministic search token used to find an existing issue.

    Built so it is a substring of the body marker, so a ``... in:body`` search for the
    fingerprint matches the hidden comment.
    """
    return f"rag-triage-cluster: {_cluster_identity(failure_mode, category, schema_version)}"


def build_issue_draft(
    cluster: TriageCluster,
    report: TriageReport,
    *,
    repo: str | None = None,
    labels: list[str] | None = None,
) -> IssueDraft:
    """Build a deterministic, grounded ``IssueDraft`` for one triage cluster.

    Pure: no I/O, no network, no mutation of inputs. The body is grounded in the real
    cluster stats and representative example carried by ``triage.json`` — never generated
    prose. ``repo`` is accepted for forward-compat (repo-qualified links) but unused in v1.
    """
    schema_version = report.schema_version
    fm = cluster.failure_mode
    cat = cluster.category
    draft_labels = list(labels) if labels is not None else ["rag-triage"]

    title = f"[rag-triage] {fm} in {cat} ({cluster.count} records, {cluster.rate:.1%})"
    marker = _build_marker(fm, cat, schema_version)
    fingerprint = _build_fingerprint(fm, cat, schema_version)

    models = ", ".join(cluster.models_seen) if cluster.models_seen else "(none recorded)"
    rep_text = cluster.representative_question_text or "(question text unavailable)"

    body = f"""\
## Failure cluster: `{fm}` in `{cat}`

`rag-triage` clustered the classified evaluation output by `(failure_mode, category)`.
This issue tracks the **{fm}** failure mode on **{cat}** questions.

### Cluster stats

| Metric                | Value          |
| --------------------- | -------------- |
| Failure mode          | `{fm}` |
| Category              | `{cat}` |
| Records in cluster    | {cluster.count} |
| Share of all records  | {cluster.rate:.1%} |
| Observed across       | {models} |

### Representative example

- **Question id:** `{cluster.representative_question_id}`
- **Question:** {rep_text}

Inspect it end-to-end with:

```
rag-inspect --question-id {cluster.representative_question_id}
```

### Provenance

Drafted from `results/triage.json` (schema `{schema_version}`) by `rag-issues`, grounded in
real cluster stats — not generated prose. Re-running `rag-issues` is idempotent via the
marker below.

{marker}
"""

    return IssueDraft(
        title=title,
        body=body,
        fingerprint=fingerprint,
        labels=draft_labels,
        failure_mode=fm,
        category=cat,
    )
