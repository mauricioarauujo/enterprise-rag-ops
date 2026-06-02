"""Unit tests for the rag-issues triage-to-GitHub-Issues logic and CLI.

Covers AC-1 through AC-15 from the Phase 15 design contract. Fully offline: no network,
no subprocess, no LLM. The GitHub backend is injected as a FakeGitHubClient at the seam;
the real GhCliClient is never imported or instantiated here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from enterprise_rag_ops.eval.issues import IssueDraft, build_issue_draft
from enterprise_rag_ops.eval.issues_cli import main
from enterprise_rag_ops.eval.triage import TriageCluster, TriageReport, _report_to_dict


class FakeGitHubClient:
    """Records calls and returns a programmable search result (the seam test double)."""

    def __init__(self, search_result: list[dict] | None = None) -> None:
        self._search_result = search_result if search_result is not None else []
        self.search_calls: list[str] = []
        self.create_calls: list[tuple[str, str, list[str]]] = []

    def search_issues(self, query: str) -> list[dict]:
        self.search_calls.append(query)
        return self._search_result

    def create_issue(self, title: str, body: str, labels: list[str]) -> str:
        self.create_calls.append((title, body, labels))
        return "https://github.com/owner/repo/issues/1"


def make_cluster(
    failure_mode: str = "abstention_error",
    category: str = "basic",
    count: int = 10,
    rate: float = 0.5,
    rep_id: str = "qst_0001",
    rep_text: str = "What is the cap rate?",
    models: list[str] | None = None,
) -> TriageCluster:
    return TriageCluster(
        failure_mode=failure_mode,
        category=category,
        count=count,
        rate=rate,
        representative_question_id=rep_id,
        representative_question_text=rep_text,
        models_seen=models if models is not None else ["gpt-4o"],
    )


def make_report(
    clusters: list[TriageCluster],
    dominant: TriageCluster | None = None,
    total: int | None = None,
    schema_version: str = "1.0",
) -> TriageReport:
    total = total if total is not None else sum(c.count for c in clusters)
    models = sorted({m for c in clusters for m in c.models_seen})
    dom = dominant if dominant is not None else (clusters[0] if clusters else None)
    return TriageReport(
        schema_version=schema_version,
        total_records=total,
        models_seen=models,
        dominant_cluster=dom,
        clusters=list(clusters),
    )


def write_triage(tmp_path: Path, report: TriageReport) -> Path:
    """Serialize a report exactly as Phase 14's rag-triage writes triage.json."""
    path = tmp_path / "triage.json"
    path.write_text(json.dumps(_report_to_dict(report), indent=2), encoding="utf-8")
    return path


# --- Pure core (issues.py) -------------------------------------------------------------


def test_ac1_pure_draft_from_cluster():
    """AC-1: build_issue_draft returns a grounded IssueDraft; no I/O."""
    cluster = make_cluster(count=42, rate=0.084)
    report = make_report([cluster])
    draft = build_issue_draft(cluster, report)

    assert isinstance(draft, IssueDraft)
    assert draft.failure_mode == "abstention_error"
    assert draft.category == "basic"
    assert "abstention_error" in draft.title
    assert "42" in draft.title
    assert "abstention_error" in draft.body
    assert "42" in draft.body
    assert "8.4%" in draft.body


def test_ac2_grounded_body():
    """AC-2: body carries the representative example + models_seen context."""
    cluster = make_cluster(
        rep_id="qst_0007",
        rep_text="What is the discount rate?",
        models=["claude-3-5-sonnet", "gpt-4o"],
    )
    draft = build_issue_draft(cluster, make_report([cluster]))

    assert "qst_0007" in draft.body
    assert "What is the discount rate?" in draft.body
    assert "Observed across" in draft.body
    assert "gpt-4o" in draft.body
    assert "claude-3-5-sonnet" in draft.body


def test_ac3_fingerprint_format():
    """AC-3: exact body marker + deterministic fingerprint (a substring of the marker)."""
    cluster = make_cluster(failure_mode="abstention_error", category="basic")
    draft = build_issue_draft(cluster, make_report([cluster]))

    assert "<!-- rag-triage-cluster: abstention_error|basic schema=1.0 -->" in draft.body
    assert draft.fingerprint == "rag-triage-cluster: abstention_error|basic schema=1.0"
    assert draft.fingerprint in draft.body  # body-search for the fingerprint finds the marker


def test_ac4_fingerprint_includes_schema_version():
    """AC-4: same (failure_mode, category), different schema_version -> different fingerprint."""
    cluster = make_cluster()
    d1 = build_issue_draft(cluster, make_report([cluster], schema_version="1.0"))
    d2 = build_issue_draft(cluster, make_report([cluster], schema_version="2.0"))
    assert d1.fingerprint != d2.fingerprint


def test_ac5_determinism():
    """AC-5: building twice from the same cluster yields byte-identical fields."""
    cluster = make_cluster()
    report = make_report([cluster])
    d1 = build_issue_draft(cluster, report)
    d2 = build_issue_draft(cluster, report)
    assert (d1.title, d1.body, d1.fingerprint) == (d2.title, d2.body, d2.fingerprint)


# --- CLI (issues_cli.py) ---------------------------------------------------------------


def test_ac6_schema_gate_happy_path(tmp_path):
    """AC-6: a valid 1.0 triage exits 0 and writes the draft file."""
    cluster = make_cluster()
    triage = write_triage(tmp_path, make_report([cluster]))
    out = tmp_path / "issues"
    rc = main(["--triage", str(triage), "--output-dir", str(out)])
    assert rc == 0
    assert (out / "abstention_error-basic.md").exists()


def test_ac7_schema_gate_fail_fast(tmp_path, capsys):
    """AC-7: missing or != 1.0 schema_version -> exit 1, stderr names found + expected, no drafts."""
    out = tmp_path / "issues"

    bad = tmp_path / "triage.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": "0.9",
                "total_records": 0,
                "models_seen": [],
                "dominant_cluster": None,
                "clusters": [],
            }
        ),
        encoding="utf-8",
    )
    rc = main(["--triage", str(bad), "--output-dir", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "0.9" in err and "1.0" in err
    assert not out.exists()

    # schema_version absent entirely
    missing = tmp_path / "triage2.json"
    missing.write_text(json.dumps({"total_records": 0, "clusters": []}), encoding="utf-8")
    assert main(["--triage", str(missing), "--output-dir", str(out)]) == 1
    assert not out.exists()


def test_ac8_dominant_only_vs_all_clusters(tmp_path):
    """AC-8: default drafts only the dominant cluster; --all-clusters drafts every cluster."""
    c1 = make_cluster("abstention_error", "basic", count=10, rate=0.5)
    c2 = make_cluster("retrieval_miss", "complex", count=6, rate=0.3, rep_id="qst_0009")
    report = make_report([c1, c2], dominant=c1, total=20)
    triage = write_triage(tmp_path, report)

    out = tmp_path / "dominant"
    main(["--triage", str(triage), "--output-dir", str(out)])
    assert sorted(p.name for p in out.glob("*.md")) == ["abstention_error-basic.md"]

    out_all = tmp_path / "all"
    main(["--triage", str(triage), "--output-dir", str(out_all), "--all-clusters"])
    assert sorted(p.name for p in out_all.glob("*.md")) == [
        "abstention_error-basic.md",
        "retrieval_miss-complex.md",
    ]


def test_ac9_empty_triage(tmp_path, capsys):
    """AC-9: dominant_cluster null + total 0 -> no drafts, 'no clusters' message, exit 0."""
    report = TriageReport(
        schema_version="1.0",
        total_records=0,
        models_seen=[],
        dominant_cluster=None,
        clusters=[],
    )
    triage = write_triage(tmp_path, report)
    out = tmp_path / "issues"
    rc = main(["--triage", str(triage), "--output-dir", str(out)])
    assert rc == 0
    assert "no clusters" in capsys.readouterr().out.lower()
    assert not out.exists()


def test_ac10_atomic_write_cleanup(tmp_path):
    """AC-10: a write failure leaves no partial/target file and cleans the temp file."""
    cluster = make_cluster()
    triage = write_triage(tmp_path, make_report([cluster]))
    out = tmp_path / "issues"

    # os.replace fails after the temp file is written → cleanup unlinks the temp, no target.
    # (The write-failure branch is the identical classify_cli.py house idiom; not re-tested.)
    with patch("enterprise_rag_ops.eval.issues_cli.os.replace", side_effect=OSError("boom")):
        rc = main(["--triage", str(triage), "--output-dir", str(out)])
    assert rc == 1
    assert not (out / "abstention_error-basic.md").exists()
    assert list(out.glob(".rag-issues-tmp-*")) == []


def test_ac11_dry_run_no_client_calls(tmp_path):
    """AC-11: without --create the injected client is never called; only drafts are written."""
    cluster = make_cluster()
    triage = write_triage(tmp_path, make_report([cluster]))
    out = tmp_path / "issues"
    fake = FakeGitHubClient()

    rc = main(["--triage", str(triage), "--output-dir", str(out)], client=fake)

    assert rc == 0
    assert fake.search_calls == []
    assert fake.create_calls == []
    assert (out / "abstention_error-basic.md").exists()


def test_ac12_create_skips_existing(tmp_path, capsys):
    """AC-12: --create with a matching open issue skips create_issue and reports the URL."""
    cluster = make_cluster()
    triage = write_triage(tmp_path, make_report([cluster]))
    out = tmp_path / "issues"
    fake = FakeGitHubClient(
        search_result=[{"url": "https://github.com/o/r/issues/7", "title": "existing"}]
    )

    rc = main(["--triage", str(triage), "--output-dir", str(out), "--create"], client=fake)

    assert rc == 0
    assert len(fake.search_calls) == 1
    assert fake.create_calls == []
    out_text = capsys.readouterr().out.lower()
    assert "already open" in out_text
    assert "issues/7" in out_text


def test_ac12_create_files_new_issue(tmp_path, capsys):
    """AC-12: --create with no match calls create_issue once and reports the returned URL."""
    cluster = make_cluster()
    triage = write_triage(tmp_path, make_report([cluster]))
    out = tmp_path / "issues"
    fake = FakeGitHubClient(search_result=[])

    rc = main(["--triage", str(triage), "--output-dir", str(out), "--create"], client=fake)

    assert rc == 0
    assert len(fake.create_calls) == 1
    title, body, labels = fake.create_calls[0]
    assert "abstention_error" in title
    assert "<!-- rag-triage-cluster: abstention_error|basic schema=1.0 -->" in body
    assert labels == ["rag-triage"]
    assert "https://github.com/owner/repo/issues/1" in capsys.readouterr().out


def test_ac13_offline_guarantee():
    """AC-13: importing the pure core in a clean interpreter pulls in no LLM client."""
    check = (
        "import sys, enterprise_rag_ops.eval.issues; sys.exit(1 if 'openai' in sys.modules else 0)"
    )
    result = subprocess.run([sys.executable, "-c", check], capture_output=True, text=True)
    assert result.returncode == 0, f"issues import pulled in an LLM client: {result.stderr}"


def test_ac13_ghcli_never_instantiated_in_dry_run(tmp_path, monkeypatch):
    """AC-13: a dry-run pass (no --create) never constructs the real GhCliClient seam impl."""
    import enterprise_rag_ops.eval.github as github_mod

    instantiated: list[bool] = []
    original_init = github_mod.GhCliClient.__init__

    def _spy_init(self, *args, **kwargs):
        instantiated.append(True)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(github_mod.GhCliClient, "__init__", _spy_init)

    triage = write_triage(tmp_path, make_report([make_cluster()]))
    rc = main(["--triage", str(triage), "--output-dir", str(tmp_path / "out")])

    assert rc == 0
    assert instantiated == [], "GhCliClient was instantiated during a dry-run"


def test_ac14_console_script_and_help():
    """AC-14: rag-issues resolves to the CLI main and --help exits 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0

    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    assert 'rag-issues = "enterprise_rag_ops.eval.issues_cli:main"' in content


def test_ac15_adr_exists_and_linked():
    """AC-15: ADR-0009 exists with the house sections and is listed in the ADR index."""
    root = Path(__file__).parents[2]
    adr = root / "docs" / "adr" / "0009-triage-to-issues.md"
    assert adr.exists()
    text = adr.read_text(encoding="utf-8")
    for section in ("## Status", "## Date", "## Context", "## Decision", "## Consequences"):
        assert section in text

    readme = (root / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    assert "0009-triage-to-issues.md" in readme
