"""Tests for the ingest CLI's record-adaptation step."""

from collections import Counter

import pytest

from enterprise_rag_ops.ingest.cli import adapt_records
from enterprise_rag_ops.ingest.schema import Document, UnknownSourceTypeError


def _raw(doc_id: str, source_type: str = "slack", content: str = "body") -> dict:
    return {"doc_id": doc_id, "source_type": source_type, "title": "T", "content": content}


def test_adapt_records_yields_documents_for_valid_input():
    skipped: Counter = Counter()
    docs = list(adapt_records(iter([_raw("d1"), _raw("d2")]), skipped))
    assert [d.id for d in docs] == ["d1", "d2"]
    assert all(isinstance(d, Document) for d in docs)
    assert skipped == Counter()


def test_adapt_records_skips_and_counts_invalid_records():
    raw = [_raw("d1"), _raw("d2", content=""), _raw("d3", content="   ")]
    skipped: Counter = Counter()
    docs = list(adapt_records(iter(raw), skipped))
    assert [d.id for d in docs] == ["d1"]
    assert skipped == Counter({"slack": 2})


def test_adapt_records_propagates_unknown_source_type():
    skipped: Counter = Counter()
    with pytest.raises(UnknownSourceTypeError):
        list(adapt_records(iter([_raw("d1", source_type="notion")]), skipped))
