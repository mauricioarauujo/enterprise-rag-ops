"""Tests for deterministic stratified sampling."""

import pytest

from enterprise_rag_ops.ingest.sampler import stratified_sample
from enterprise_rag_ops.ingest.schema import Document


def _doc(doc_id: str, source_type: str) -> Document:
    return Document(id=doc_id, source_type=source_type, text="body")


def test_takes_first_n_per_source_by_sorted_id():
    docs = [_doc(f"{src}-{i:02d}", src) for src in ("a", "b") for i in (3, 1, 2, 0)]
    sample = stratified_sample(docs, docs_per_source=2)
    assert [d.id for d in sample] == ["a-00", "a-01", "b-00", "b-01"]


def test_result_ordered_by_source_then_id():
    docs = [_doc("z-1", "z"), _doc("a-2", "a"), _doc("a-1", "a"), _doc("z-0", "z")]
    sample = stratified_sample(docs, docs_per_source=5)
    assert [d.id for d in sample] == ["a-1", "a-2", "z-0", "z-1"]


def test_source_with_fewer_than_n_docs_keeps_all():
    docs = [_doc("a-1", "a"), _doc("b-1", "b"), _doc("b-2", "b")]
    sample = stratified_sample(docs, docs_per_source=10)
    assert sorted(d.id for d in sample) == ["a-1", "b-1", "b-2"]


def test_deterministic_across_runs():
    docs = [_doc(f"s-{i:03d}", "s") for i in range(50)]
    first = [d.id for d in stratified_sample(docs, docs_per_source=7)]
    second = [d.id for d in stratified_sample(reversed(docs), docs_per_source=7)]
    assert first == second


def test_trim_path_preserves_correct_first_n():
    # Far more than 2 * docs_per_source docs per source forces the in-stream trim.
    docs = [_doc(f"s-{i:04d}", "s") for i in range(1000)]
    sample = stratified_sample(reversed(docs), docs_per_source=5)
    assert [d.id for d in sample] == [f"s-{i:04d}" for i in range(5)]


def test_docs_per_source_below_one_raises():
    with pytest.raises(ValueError, match="docs_per_source"):
        stratified_sample([], docs_per_source=0)
