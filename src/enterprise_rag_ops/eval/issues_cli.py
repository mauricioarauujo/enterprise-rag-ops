"""Command-line interface for drafting GitHub Issues from a triage report.

Thin CLI: loads ``results/triage.json``, gates on ``schema_version == "1.0"``, builds
deterministic ``IssueDraft`` objects (``eval/issues.py``), writes markdown drafts to
``results/issues/`` atomically, and — only with ``--create`` — files them idempotently
through the ``GitHubClient`` seam. Dry-run / draft is the default; no network call occurs
without ``--create``. Mirrors ``triage_cli.py`` / ``classify_cli.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from enterprise_rag_ops.eval.github import GhCliClient, GitHubClient
from enterprise_rag_ops.eval.issues import IssueDraft, build_issue_draft
from enterprise_rag_ops.eval.triage import SCHEMA_VERSION, TriageCluster, TriageReport

logger = logging.getLogger("enterprise_rag_ops.eval.issues_cli")


def _cluster_from_dict(d: dict) -> TriageCluster:
    """Inverse of ``triage._cluster_to_dict`` — same field order."""
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
    """Inverse of ``triage._report_to_dict`` — same field order."""
    dom = data["dominant_cluster"]
    return TriageReport(
        schema_version=data["schema_version"],
        total_records=data["total_records"],
        models_seen=data["models_seen"],
        dominant_cluster=_cluster_from_dict(dom) if dom is not None else None,
        clusters=[_cluster_from_dict(c) for c in data["clusters"]],
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for rag-issues."""
    parser = argparse.ArgumentParser(
        prog="rag-issues",
        description="Draft GitHub Issues from a rag-triage report (dry-run by default).",
    )
    parser.add_argument(
        "--triage",
        default="results/triage.json",
        help="Path to the triage report JSON (default: results/triage.json).",
    )
    parser.add_argument(
        "--output-dir",
        default="results/issues",
        help="Directory for draft markdown files (default: results/issues).",
    )
    parser.add_argument(
        "--all-clusters",
        action="store_true",
        help="Draft one issue per cluster (default: dominant cluster only).",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create issues on GitHub (default: dry-run, drafts only — no network).",
    )
    parser.add_argument(
        "--labels",
        default=None,
        help="Comma-separated issue labels (default: rag-triage).",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Target repo owner/name for --create (default: ambient gh repo).",
    )
    return parser


def _draft_filename(draft: IssueDraft) -> str:
    # Guard against path separators in cluster keys turning the draft into a subdirectory.
    fm = draft.failure_mode.replace("/", "_").replace(" ", "_")
    cat = draft.category.replace("/", "_").replace(" ", "_")
    return f"{fm}-{cat}.md"


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write ``content`` to ``path`` (temp file + os.replace, cleanup on fail)."""
    output_dir = path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=output_dir,
        delete=False,
        prefix=".rag-issues-tmp-",
        suffix=".md",
        encoding="utf-8",
    ) as tmp_file:
        temp_path = Path(tmp_file.name)
        try:
            tmp_file.write(content)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    try:
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def main(argv: list[str] | None = None, *, client: GitHubClient | None = None) -> int:
    """CLI entrypoint — returns 0 on success, prints errors to stderr and returns 1."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    triage_path = Path(args.triage)
    output_dir = Path(args.output_dir)
    labels = (
        [s.strip() for s in args.labels.split(",") if s.strip()] if args.labels else ["rag-triage"]
    )

    try:
        if not triage_path.exists():
            raise FileNotFoundError(f"Triage report not found: {triage_path}")

        with open(triage_path, encoding="utf-8") as f:
            data = json.load(f)

        found = data.get("schema_version")
        if found != SCHEMA_VERSION:
            print(
                f"Error: unsupported triage schema_version {found!r}; expected {SCHEMA_VERSION!r}.",
                file=sys.stderr,
            )
            return 1

        report = _report_from_dict(data)

        # Cluster selection: dominant-only by default; --all-clusters widens.
        if args.all_clusters:
            selected = list(report.clusters)
        elif report.dominant_cluster is not None:
            selected = [report.dominant_cluster]
        else:
            selected = []

        if not selected:
            print("No clusters to draft (empty triage report).")
            return 0

        drafts = [build_issue_draft(c, report, labels=labels) for c in selected]

        # Draft markdown files are always written (dry-run and --create alike).
        print("=" * 80)
        print(f"RAG-ISSUES — {len(drafts)} draft(s) (schema {report.schema_version})")
        print("=" * 80)
        for draft in drafts:
            out_path = output_dir / _draft_filename(draft)
            _atomic_write(out_path, draft.body)
            print(f"  drafted: {out_path}  —  {draft.title}")
        print("=" * 80)

        if not args.create:
            logger.info("Dry-run (no --create): wrote %d draft(s), no GitHub calls.", len(drafts))
            return 0

        # --create: idempotent GitHub creation through the seam (constructed here only).
        gh = client or GhCliClient(repo=args.repo)
        for draft in drafts:
            existing = gh.search_issues(draft.fingerprint)
            if existing:
                url = existing[0].get("url", "<unknown>")
                print(f"  skip (already open): {url}  —  {draft.title}")
                logger.info("Issue already open: %s", url)
                continue
            url = gh.create_issue(draft.title, draft.body, draft.labels)
            print(f"  created: {url}  —  {draft.title}")
            logger.info("Created issue: %s", url)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
