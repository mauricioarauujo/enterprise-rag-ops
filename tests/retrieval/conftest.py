"""Shared fixtures for retrieval tests.

The synthetic corpus is intentionally tiny (six documents across three source
types) — enough to exercise chunking, BM25 + dense fusion, source-type
filtering, abstention, and doc-level dedup, while keeping `make test` fast.
"""

from __future__ import annotations

import pytest

from enterprise_rag_ops.ingest.schema import Document
from enterprise_rag_ops.retrieval.embedder import StubEmbedder


@pytest.fixture
def synthetic_documents() -> list[Document]:
    """Six documents across three source types.

    Sized so chunking yields more than one chunk per document (so dedup is
    actually exercised), with distinctive lexical anchors so BM25 has signal.
    """
    long_pto = (
        "The PTO policy at the company allows employees to take 20 days off per year. "
        "Unused vacation days roll over up to a maximum of five days into the next year. "
        "Sick leave is tracked separately and is not capped. Holidays are observed per "
        "the published company calendar. Employees should request time off through the HR "
        "portal at least two weeks in advance for any absence longer than three days."
    )
    long_incident = (
        "Our incident response runbook defines four severity levels. SEV1 incidents "
        "require an on-call engineer page within five minutes and a written post-mortem "
        "within 48 hours. Communication channels are the incident Slack room and a status "
        "page update. The incident commander coordinates triage; the scribe records the "
        "timeline. Customer-facing impact is logged separately for the support team."
    )
    return [
        Document(id="doc_pto", source_type="confluence", text=long_pto),
        Document(
            id="doc_holidays",
            source_type="confluence",
            text="The company observes ten paid holidays per year, listed on the HR portal calendar page.",
        ),
        Document(id="doc_incident", source_type="confluence", text=long_incident),
        Document(
            id="doc_jira",
            source_type="jira",
            text="JIRA-1234: Payment gateway timeout on checkout. Steps to reproduce: open cart, click pay, observe 504 after 30s.",
        ),
        Document(
            id="doc_slack",
            source_type="slack",
            text="Reminder: deploy freeze starts Friday at 5pm PT. No production deploys until Monday 9am PT.",
        ),
        Document(
            id="doc_slack_other",
            source_type="slack",
            text="Quick poll: should we move the standup to 10am? React with thumbs up for yes, down for no.",
        ),
    ]


@pytest.fixture
def stub_embedder() -> StubEmbedder:
    """Deterministic stub embedder — same instance everywhere in a test."""
    return StubEmbedder(dim=64)
