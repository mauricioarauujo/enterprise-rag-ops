"""GitHub client seam for ``rag-issues`` — the only subprocess-touching module.

Defines the ``GitHubClient`` Protocol and the default ``GhCliClient`` implementation that
shells out to the ``gh`` CLI (ambient auth). This is the ADR-0009 swap axis (``gh`` CLI vs
PyGithub/REST) and the injection point for offline tests, which supply a fake at the seam
and never import this implementation.
"""

from __future__ import annotations

import json
import subprocess
from typing import Protocol


class GitHubClient(Protocol):
    """The two operations ``rag-issues`` needs from a GitHub backend."""

    def search_issues(self, query: str) -> list[dict]:
        """Return open issues whose body matches ``query`` (best-effort search)."""
        ...

    def create_issue(self, title: str, body: str, labels: list[str]) -> str:
        """Create an issue and return its URL."""
        ...


class GhCliClient:
    """Default ``GitHubClient`` backed by the ``gh`` CLI.

    All invocations use ``subprocess.run`` with an argument list (never a shell string),
    so the markdown body and fingerprint are passed verbatim with no quoting hazard. This
    class is never imported or instantiated by the test suite — tests inject a fake.
    """

    def __init__(self, repo: str | None = None) -> None:
        self._repo = repo

    def _repo_args(self) -> list[str]:
        return ["--repo", self._repo] if self._repo else []

    def search_issues(self, query: str) -> list[dict]:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--search",
                f"{query} in:body",
                "--state",
                "open",
                "--json",
                "url,title",
                *self._repo_args(),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else []

    def create_issue(self, title: str, body: str, labels: list[str]) -> str:
        label_args: list[str] = []
        for label in labels:
            label_args += ["--label", label]
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                title,
                "--body",
                body,
                *label_args,
                *self._repo_args(),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
